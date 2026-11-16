"""Mellipi Sound Recorder: capture on demand and save local WAV recordings."""
import array
from datetime import datetime
import os
from pathlib import Path
import stat
import sys
import tempfile
import uuid
import wave

os.environ['ORBIT_QT'] = '6'
os.environ['QT_WAYLAND_SHELL_INTEGRATION'] = 'xdg-shell'
os.environ.pop('QT_WAYLAND_DISABLE_WINDOWDECORATION', None)

from PyQt6.QtCore import QEvent, QFile, QSignalBlocker, QStandardPaths, Qt, QTimer, QUrl
from PyQt6.QtGui import QIcon
from PyQt6.QtMultimedia import (QAudio, QAudioFormat, QAudioOutput, QAudioSource,
                                QMediaDevices, QMediaPlayer)
from PyQt6.QtWidgets import (QApplication, QComboBox, QFrame, QHBoxLayout,
                             QLabel, QListWidget, QListWidgetItem, QProgressBar,
                             QPushButton, QVBoxLayout)

import icon_theme
from app_palette import adjust_contrast
from file_chooser import FileChooser
from qt_app import AppWindow, ThemedInput, themed_prompt


RIFF_MAX_DATA_BYTES = (1 << 32) - 1 - 36


def level(samples):
    if not samples:
        return 0
    values = array.array('h', samples)
    return round(max(abs(min(values)), abs(max(values))) * 100 / 32768)


class Recording:
    """Write a private staging file and expose a uniquely named WAV after finalization."""

    def __init__(self, directory, rate, channels):
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path = directory / (datetime.now().strftime('Recording %Y-%m-%d %H-%M-%S')
                                 + f' {uuid.uuid4().hex[:8]}.wav')
        self.stream = tempfile.NamedTemporaryFile(dir=directory, prefix='.recording-',
                                                 suffix='.part', delete=False)
        self.staging = Path(self.stream.name)
        self.rate = rate
        self.frame_size = channels * 2
        self.frames = 0
        self.max_frames = RIFF_MAX_DATA_BYTES // self.frame_size
        self.pending = b''
        self.wav = wave.open(self.stream, 'wb')
        self.wav.setparams((channels, 2, rate, 0, 'NONE', 'not compressed'))

    @property
    def at_limit(self):
        return self.frames >= self.max_frames

    def append(self, data):
        data = self.pending + data
        end = min(self.max_frames - self.frames, len(data) // self.frame_size) * self.frame_size
        self.pending = data[end:] if self.frames + end // self.frame_size < self.max_frames else b''
        if not end:
            return 0
        # Qt sends samples in native byte order; WAV always uses little endian.
        self.wav.writeframesraw(data[:end])
        self.frames += end // self.frame_size
        return level(data[:end])

    def finish(self, *, preserve=True):
        try:
            self.wav.close()
            self.stream.close()
            if preserve and self.frames:
                os.link(self.staging, self.path)
                return self.path
            return None
        finally:
            self.stream.close()
            self.staging.unlink(missing_ok=True)


def record_format(device):
    native = device.preferredFormat()
    for rate, channels in ((48000, 1), (44100, 1),
                           (native.sampleRate(), native.channelCount()), (48000, 2)):
        sample = QAudioFormat()
        sample.setSampleRate(rate)
        sample.setChannelCount(channels)
        sample.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        if rate > 0 and channels > 0 and device.isFormatSupported(sample):
            return sample
    return None


def saved_recordings(directory):
    """List completed regular WAVs, newest first; skip temporary audio and symlinks."""
    rows = []
    try:
        for path in directory.iterdir():
            if path.name.startswith('.') or path.suffix.lower() != '.wav':
                continue
            try:
                info = path.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISREG(info.st_mode):
                rows.append((info.st_mtime_ns, path))
    except FileNotFoundError:
        return []
    return [path for _, path in sorted(rows, reverse=True)]


class RecordingStatus(QLabel):
    """Include wrapped status height in the window's layout minimum."""

    def __init__(self):
        super().__init__()
        self.setWordWrap(True)
        self.setTextFormat(Qt.TextFormat.PlainText)

    def update_required_height(self):
        if self.width() > 0:
            height = self.heightForWidth(self.width()) if self.text() else 0
            if height != self.minimumHeight():
                self.setMinimumHeight(height)

    def setText(self, text):
        super().setText(text)
        self.update_required_height()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_required_height()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self.update_required_height()


class Recorder(AppWindow):
    extra_style = """
        QFrame#captureMeter { background: %(raised)s; border-radius: %(radius)dpx; }
        QLabel#captureTime { font-weight: 700; }
        QPushButton#recordAction:enabled { background: %(accent)s; color: %(accent_text)s; font-weight: 600; }
        QPushButton#recordAction:hover:enabled { border-color: %(focus)s; }
        QPushButton#recordAction:focus { border: 2px solid %(accent_text)s; }
    """

    def __init__(self, directory=None):
        super().__init__('Sound Recorder')
        self.resize(490, 410)
        base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.MusicLocation)
        self.directory = directory if directory is not None else (
            Path(base or (Path.home() / 'Music')) / 'Recordings')
        self.source = self.audio_device = self.recording = self.current_file = None
        self.peak = 0

        input_row = QHBoxLayout()
        label = QLabel('&Input')
        input_row.addWidget(label)
        self.inputs = QComboBox()
        self.inputs.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.inputs.setMinimumContentsLength(14)
        self.inputs.setPlaceholderText('No microphone')
        label.setBuddy(self.inputs)
        self.inputs.setAccessibleName('Recording input')
        input_row.addWidget(self.inputs, 1)
        self.content.addLayout(input_row)
        self.devices = QMediaDevices(self)
        self.devices.audioInputsChanged.connect(self.refresh_inputs)

        self.meter = QProgressBar()
        self.meter.setRange(0, 100)
        self.meter.setValue(0)
        self.meter.setTextVisible(False)
        self.meter.setAccessibleName('Input level')
        meter_panel = QFrame()
        meter_panel.setObjectName('captureMeter')
        meter_layout = QVBoxLayout(meter_panel)
        meter_layout.setContentsMargins(12, 9, 12, 9)
        meter_layout.setSpacing(6)
        meter_row = QHBoxLayout()
        self.meter_state = QLabel('Input level')
        meter_row.addWidget(self.meter_state)
        meter_row.addStretch()
        self.elapsed = QLabel('00:00')
        self.elapsed.setObjectName('captureTime')
        self.elapsed.setAccessibleName('Recording time')
        meter_row.addWidget(self.elapsed)
        meter_layout.addLayout(meter_row)
        self.meter.setFixedHeight(6)
        meter_layout.addWidget(self.meter)
        self.content.addWidget(meter_panel)

        self.record_button = self.button('Record', 'microphone', self.toggle_record)
        self.record_button.setObjectName('recordAction')
        self.record_button.setMinimumWidth(108)
        self.themeChanged.connect(self.style_capture)
        self.play_button = self.button('Play', 'play', self.toggle_playback)
        self.open_button = self.button('Open WAV…', 'folder', self.open_recording)
        actions = QHBoxLayout()
        actions.addWidget(self.record_button)
        actions.addStretch()
        actions.addWidget(self.play_button)
        actions.addWidget(self.open_button)
        self.content.addLayout(actions)

        library_header = QHBoxLayout()
        library_heading = QLabel('&Recordings')
        library_header.addWidget(library_heading)
        library_header.addStretch()
        self.refresh_button = self.button('', 'view-refresh', self.refresh_library)
        self.refresh_button.setAccessibleName('Refresh recordings')
        self.refresh_button.setToolTip('Refresh recordings')
        library_header.addWidget(self.refresh_button)
        self.content.addLayout(library_header)
        self.library = QListWidget()
        self.library.setMinimumHeight(88)
        self.library.setAccessibleName('Saved recordings')
        self.library.setUniformItemSizes(True)
        self.library.setAlternatingRowColors(True)
        library_heading.setBuddy(self.library)
        self.library.currentItemChanged.connect(self.select_library_item)
        self.library.itemActivated.connect(self.play_library_item)
        self.content.addWidget(self.library, 1)
        self.library_empty = QLabel('New recordings appear here.')
        self.library_empty.setObjectName('muted')
        self.content.addWidget(self.library_empty)
        library_actions = QHBoxLayout()
        library_actions.addStretch()
        self.rename_button = self.button('Rename…', 'edit', self.rename_selected)
        self.trash_button = self.button('Move to Trash', 'trash', self.trash_selected)
        library_actions.addWidget(self.rename_button)
        library_actions.addWidget(self.trash_button)
        self.content.addLayout(library_actions)
        self.space_controls(actions, library_header, library_actions)

        self.status = RecordingStatus()
        self.status.setObjectName('muted')
        self.content.addWidget(self.status)

        self.player = QMediaPlayer(self)
        self.player.setAudioOutput(QAudioOutput(self.player))
        self.player.playbackStateChanged.connect(self.update_controls)
        self.player.errorOccurred.connect(self.playback_error)
        self.timer = QTimer(self, interval=100)
        self.timer.timeout.connect(self.update_meter)
        self.refresh_inputs()
        self.refresh_library()
        if not self.inputs.count():
            self.status.setText('No microphone detected. Connect one to record.')

    def button(self, text, icon, slot):
        button = QPushButton(text)
        button.setProperty('mellipiSymbolicIcon', icon)
        button.clicked.connect(slot)
        return button

    def refresh_inputs(self):
        available = self.devices.audioInputs()
        previous = self.inputs.currentData()
        default = self.devices.defaultAudioInput()
        self.inputs.clear()
        if available:
            self.inputs.addItem(f'Default — {default.description()}' if not default.isNull()
                                else 'Default input', None)
        for device in available:
            self.inputs.addItem(device.description(), bytes(device.id()))
        for index in range(self.inputs.count()):
            self.inputs.setItemData(index, self.inputs.itemText(index), Qt.ItemDataRole.ToolTipRole)
        if previous is not None:
            index = self.inputs.findData(previous)
            if index >= 0:
                self.inputs.setCurrentIndex(index)
        self.update_controls()

    def style_capture(self):
        tokens = self.theme
        active = self.recording is not None
        role = adjust_contrast('#cc5147', [tokens['raised'], tokens['surface']], 4.5,
                               '#000000' if self.theme_watch.preferences.values['mode'] == 'light' else '#ffffff')
        self.meter_state.setText('● Recording' if active else 'Input level')
        self.meter_state.setStyleSheet(f'color: {role}; font-weight: 600;' if active else '')
        ink = role if active else tokens['accent_ink']
        self.meter.setStyleSheet(
            f'QProgressBar {{background: {tokens["surface"]}; border-radius: 3px;}}'
            f'QProgressBar::chunk {{background: {ink}; border-radius: 3px;}}')
        # The primary face uses accent-text rather than the standard icon ink.
        from qt_app import symbolic_icon
        self.record_button.setIcon(symbolic_icon('stop' if active else 'microphone', tokens['accent_text']))

    def update_controls(self):
        active = self.recording is not None
        playing = self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        self.inputs.setEnabled(not active and self.inputs.count() > 0)
        self.record_button.setEnabled(active or self.inputs.count() > 0)
        self.record_button.setText('Stop recording' if active else 'Record')
        self.record_button.setProperty('mellipiSymbolicIcon', 'stop' if active else 'microphone')
        self.play_button.setEnabled(self.current_file is not None and not active)
        self.play_button.setText('Stop playback' if playing else 'Play')
        self.play_button.setProperty('mellipiSymbolicIcon', 'stop' if playing else 'play')
        self.open_button.setEnabled(not active)
        self.library.setEnabled(not active)
        self.refresh_button.setEnabled(not active)
        selected = self.selected_recording()
        self.rename_button.setEnabled(not active and selected is not None)
        self.trash_button.setEnabled(not active and selected is not None)
        self.refresh_icons()
        self.style_capture()

    def toggle_record(self):
        if self.recording is not None:
            self.finish_recording()
            return
        key = self.inputs.currentData()
        device = (self.devices.defaultAudioInput() if key is None else
                  next((item for item in self.devices.audioInputs() if bytes(item.id()) == key), None))
        if device is None or device.isNull():
            self.status.setText('No microphone is available.')
            return
        sample = record_format(device)
        if sample is None:
            self.status.setText('This microphone does not provide a supported PCM format.')
            return
        self.player.stop()
        try:
            self.recording = Recording(self.directory, sample.sampleRate(), sample.channelCount())
        except OSError as exc:
            self.status.setText(f'Could not start recording: {exc}')
            return
        source = QAudioSource(device, sample, self)
        self.source = source
        self.audio_device = source.start()
        if not self.audio_device or source.error() != QAudio.Error.NoError:
            self.finish_recording('Could not open the microphone.')
            return
        source.stateChanged.connect(self.capture_state)
        self.audio_device.readyRead.connect(self.read_audio)
        self.elapsed.setText('00:00')
        self.peak = 0
        self.status.setText('Recording…')
        self.timer.start()
        self.update_controls()

    def capture_state(self, state):
        source = self.sender()
        if (source is self.source and state == QAudio.State.StoppedState and self.recording
                and source.error() != QAudio.Error.NoError):
            self.finish_recording('The microphone stopped unexpectedly.')

    def read_audio(self):
        if self.recording is None or self.audio_device is None:
            return
        try:
            self.peak = max(self.peak, self.recording.append(bytes(self.audio_device.readAll())))
            if self.recording.at_limit:
                self.finish_recording('Reached the WAV size limit.')
        except (OSError, wave.Error) as exc:
            self.finish_recording(f'Could not write recording: {exc}', preserve=False)

    def update_meter(self):
        if self.recording is None:
            return
        self.show_time(self.recording.frames // self.recording.rate)
        self.meter.setValue(self.peak)
        self.peak = 0

    def show_time(self, seconds):
        self.elapsed.setText(f'{seconds // 60:02}:{seconds % 60:02}')

    def finish_recording(self, error='', preserve=True):
        if self.recording is None:
            return True
        recording, self.recording = self.recording, None
        source, self.source = self.source, None
        io, self.audio_device = self.audio_device, None
        self.timer.stop()
        try:
            if io is not None and preserve and not recording.at_limit:
                recording.append(bytes(io.readAll()))
        except (OSError, wave.Error) as exc:
            error = f'Could not finish recording: {exc}'
            preserve = False
        if source is not None:
            source.stop()
            source.deleteLater()
        try:
            path = recording.finish(preserve=preserve)
        except (OSError, wave.Error) as exc:
            self.status.setText(f'Could not save recording: {exc}')
            result = False
        else:
            if path is not None:
                self.set_recording(path)
                self.refresh_library()
                self.status.setText(f'{error} Saved {path.name}' if error else f'Saved {path.name}')
            else:
                self.status.setText(error or 'No audio was captured.')
            result = bool(path or not error)
        self.show_time(recording.frames // recording.rate)
        self.meter.setValue(0)
        self.update_controls()
        return result

    def set_recording(self, path):
        self.player.stop()
        self.current_file = path
        self.player.setSource(QUrl.fromLocalFile(str(path)) if path is not None else QUrl())
        self.update_controls()

    def selected_recording(self):
        row = self.library.currentItem()
        return row.data(Qt.ItemDataRole.UserRole) if row else None

    def refresh_library(self):
        if self.recording is not None:
            return
        try:
            paths = saved_recordings(self.directory)
        except OSError:
            self.library_empty.setText('Could not read the recordings folder.')
            paths = []
        else:
            self.library_empty.setText('New recordings appear here.')
        with QSignalBlocker(self.library):
            self.library.clear()
            for path in paths:
                item = QListWidgetItem(path.stem, self.library)
                item.setToolTip(path.name)
                item.setData(Qt.ItemDataRole.UserRole, path)
                if path == self.current_file:
                    self.library.setCurrentItem(item)
        self.library_empty.setVisible(not paths)
        self.update_controls()

    def select_library_item(self):
        if self.recording is None and (path := self.selected_recording()) is not None:
            self.set_recording(path)
        self.update_controls()

    def play_library_item(self, item):
        if self.recording is None:
            path = item.data(Qt.ItemDataRole.UserRole)
            if path != self.current_file:
                self.set_recording(path)
            self.player.play()

    def rename_selected(self):
        path = self.selected_recording()
        if path is None or self.recording is not None:
            return
        name, accepted = ThemedInput.getText(self, 'Rename recording', 'Name', text=path.stem)
        if not accepted:
            return
        name = name.strip()
        if not name or name.startswith('.') or '/' in name or '\\' in name or any(ord(c) < 32 for c in name):
            self.status.setText('Choose a name without slashes or control characters.')
            return
        destination = path.with_name(name + ('' if name.lower().endswith('.wav') else '.wav'))
        if destination == path:
            return
        self.set_recording(None)
        if not QFile(str(path)).rename(str(destination)):
            self.set_recording(path)
            self.status.setText('Could not rename this recording. Check the name and folder permissions.')
            return
        self.set_recording(destination)
        self.refresh_library()
        self.status.setText(f'Renamed to {destination.name}')

    def trash_selected(self):
        path = self.selected_recording()
        if path is None or self.recording is not None:
            return
        from file_transfers import identity
        try:
            original = identity(path)
        except OSError:
            self.refresh_library()
            self.status.setText('This recording is no longer available.')
            return
        if not themed_prompt(self, 'Move recording to Trash?', path.name, 'Move to Trash', 'Cancel'):
            return
        try:
            current = identity(path)
        except OSError:
            current = None
        if current != original:
            self.refresh_library()
            self.status.setText('This recording changed. Select it again before moving it to Trash.')
            return
        self.set_recording(None)
        if not QFile(str(path)).moveToTrash():
            self.set_recording(path)
            self.status.setText('Could not move this recording to Trash.')
            return
        self.refresh_library()
        self.status.setText(f'Moved {path.name} to Trash')

    def open_recording(self):
        path, _ = FileChooser.getOpenFileName(self, 'Open recording', str(self.directory),
                                              'WAV recordings (*.wav *.WAV)')
        if path:
            self.set_recording(Path(path))
            self.refresh_library()
            if self.player.error() == QMediaPlayer.Error.NoError:
                self.status.setText(str(path))

    def toggle_playback(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.stop()
        elif self.current_file is not None:
            self.player.play()

    def playback_error(self, error, message):
        if error != QMediaPlayer.Error.NoError:
            self.status.setText(f'Could not play recording: {message}')

    def closeEvent(self, event):
        if self.recording is not None:
            if not themed_prompt(self, 'Stop recording?', 'Save the recording and close Sound Recorder?',
                                 'Save and close', 'Keep recording') or not self.finish_recording():
                event.ignore()
                return
        self.player.stop()
        super().closeEvent(event)


def main():
    app = QApplication([sys.argv[0]])
    app.setApplicationName('Sound Recorder')
    app.setOrganizationName('Mellipi')
    app.setDesktopFileName('mellipi-recorder')
    icon_theme.configure()
    app.setWindowIcon(QIcon.fromTheme('mellipi-recorder'))
    window = Recorder()
    window.show()
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
