"""Mellipi Sound Recorder: capture on demand and save local WAV recordings."""
import array
from collections import deque
from datetime import datetime
import fcntl
import os
from pathlib import Path
import stat
import struct
import sys
import tempfile
from threading import Condition
import uuid
import wave

os.environ['ORBIT_QT'] = '6'
os.environ['QT_WAYLAND_SHELL_INTEGRATION'] = 'xdg-shell'
os.environ.pop('QT_WAYLAND_DISABLE_WINDOWDECORATION', None)

from PyQt6.QtCore import QEvent, QFile, QSignalBlocker, QStandardPaths, Qt, QThread, QTimer, QUrl
from PyQt6.QtGui import QIcon
from PyQt6.QtMultimedia import (QAudio, QAudioFormat, QAudioOutput, QAudioSource,
                                QMediaDevices, QMediaPlayer)
from PyQt6.QtWidgets import (QApplication, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QFrame, QHBoxLayout,
                             QLabel, QListWidget, QListWidgetItem, QMenu, QProgressBar,
                             QPushButton, QVBoxLayout)

import icon_theme
from app_palette import adjust_contrast
from desktop_icons import rename_no_replace
from file_chooser import FileChooser
from file_transfers import identity
from qt_app import AppWindow, ThemedInput, exec_owned_dialog, style_dialog, themed_prompt


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
        self.lease = os.dup(self.stream.fileno())
        fcntl.flock(self.lease, fcntl.LOCK_EX)
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
        cleanup = False
        try:
            self.wav.close()
            if preserve and self.frames:
                self.stream.flush()
                os.fsync(self.stream.fileno())
            self.stream.close()
            if preserve and self.frames:
                os.link(self.staging, self.path)
                cleanup = True
                return self.path
            cleanup = not preserve or self.staging.stat().st_size <= 44
            return None
        finally:
            try:
                self.stream.close()
            finally:
                # A failed close or publish must not unlink the last copy.
                try:
                    if cleanup:
                        self.staging.unlink(missing_ok=True)
                finally:
                    os.close(self.lease)


class CaptureWriter(QThread):
    """Disk I/O owns its queue and never stalls the Qt audio callbacks."""
    def __init__(self, recording, parent=None):
        super().__init__(parent)
        self.recording = recording
        self.condition = Condition()
        self.chunks = deque()
        self.pending_bytes = self.peak = 0
        self.ending = False
        self.preserve = True
        self.issue = self.error = ''
        self.path = None

    def submit(self, chunk):
        with self.condition:
            if self.ending:
                return False
            if self.pending_bytes + len(chunk) > 1024 * 1024:
                self.stop('Storage could not keep up. The audio already captured will be saved.')
                return False
            if chunk:
                self.chunks.append(chunk)
                self.pending_bytes += len(chunk)
                self.condition.notify()
            return True

    def stop(self, issue='', preserve=True):
        with self.condition:
            if not self.ending:
                self.ending, self.issue, self.preserve = True, issue, preserve
                self.condition.notify()

    def take_peak(self):
        with self.condition:
            value, self.peak = self.peak, 0
            return value

    def run(self):
        try:
            while not self.recording.at_limit:
                with self.condition:
                    self.condition.wait_for(lambda: self.ending or self.chunks)
                    if not self.chunks:
                        break
                    chunk = self.chunks.popleft()
                    self.pending_bytes -= len(chunk)
                peak = self.recording.append(chunk)
                with self.condition:
                    self.peak = max(peak, self.peak)
            if self.recording.at_limit:
                self.stop('Reached the WAV size limit.')
        except (OSError, wave.Error) as error:
            with self.condition:
                self.ending = True
                self.issue = f'Recording stopped after a write error: {error}'
        try:
            self.path = self.recording.finish(preserve=self.preserve)
        except (OSError, wave.Error) as error:
            self.error = str(error)


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


WAV_HEADER = struct.Struct('<4sI4s4sIHHIIHH4sI')


def recover_recording(path):
    """Repair the PCM header when an interruption left complete frames on disk."""
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as stream:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError('Not a regular recording file.')
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError('This recording is still in use.') from error
        header = stream.read(WAV_HEADER.size)
        if len(header) != WAV_HEADER.size:
            raise ValueError('No playable audio header. The original file has been kept.')
        riff, riff_bytes, wav, fmt, fmt_len, pcm, channels, rate, byte_rate, align, bits, data, declared = WAV_HEADER.unpack(header)
        if ((riff, wav, fmt, data) != (b'RIFF', b'WAVE', b'fmt ', b'data') or
                (fmt_len, pcm, bits) != (16, 1, 16) or not 1 <= channels <= 64 or
                not 1 <= rate <= 768000 or align != channels * 2 or byte_rate != rate * align):
            raise ValueError('The audio format is not a supported recording. The original file has been kept.')
        actual = min(info.st_size - WAV_HEADER.size, RIFF_MAX_DATA_BYTES)
        actual -= actual % align
        if not actual:
            raise ValueError('No complete audio frames. The original file has been kept.')
        destination = path.with_name(f'Recovered {uuid.uuid4().hex[:8]}.wav')
        if (info.st_dev, info.st_ino) != (path.lstat().st_dev, path.lstat().st_ino):
            raise ValueError('The recording changed. Try again.')
        if declared == actual and riff_bytes == actual + 36 and info.st_size == actual + WAV_HEADER.size:
            os.link(path, destination, follow_symlinks=False)
        else:
            # Copy only whole frames into a new private file. A failed recovery
            # or power loss leaves the original staging file untouched.
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.recovering-') as repaired:
                repaired.write(WAV_HEADER.pack(riff, actual + 36, wav, fmt, fmt_len, pcm,
                                               channels, rate, byte_rate, align, bits, data, actual))
                remaining = actual
                while remaining:
                    chunk = stream.read(min(remaining, 256 * 1024))
                    if not chunk:
                        raise OSError('The recovery file changed while reading it.')
                    repaired.write(chunk)
                    remaining -= len(chunk)
                repaired.flush()
                os.fsync(repaired.fileno())
                os.link(repaired.name, destination)
        # Keep the recovery source if the name changed during publication.
        current = path.lstat()
        if (info.st_dev, info.st_ino) == (current.st_dev, current.st_ino):
            path.unlink()
        return destination


class RecoveryJob(QThread):
    def __init__(self, path, parent, operation=None):
        super().__init__(parent)
        self.source, self.path, self.error = path, None, ''
        self.operation = operation or (lambda: recover_recording(self.source))

    def run(self):
        try:
            self.path = self.operation()
        except (OSError, ValueError, wave.Error, EOFError) as error:
            self.error = str(error)


def trim_recording(source, destination, first, last, expected):
    """Copy whole PCM frames into a new WAV; refuse stale sources and existing outputs."""
    source, destination = Path(source), Path(destination)
    if identity(source) != expected:
        raise ValueError('This recording changed. Select it again before trimming.')
    fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError('Choose a regular WAV recording.')
        if (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns) != expected:
            raise ValueError('This recording changed. Select it again before trimming.')
        with wave.open(stream, 'rb') as original:
            if not (type(first) is int and type(last) is int and 0 <= first < last <= original.getnframes()):
                raise ValueError('Choose a start and end inside the recording.')
            original.setpos(first)
            frame_bytes = original.getnchannels() * original.getsampwidth()
            with tempfile.TemporaryDirectory(prefix='.mellipi-trim-', dir=destination.parent) as directory:
                draft = Path(directory) / 'trimmed.wav'
                with draft.open('xb') as output:
                    with wave.open(output, 'wb') as recording:
                        recording.setparams(original.getparams())
                        remaining = last - first
                        while remaining:
                            count = min(remaining, max(1, (256 * 1024) // frame_bytes))
                            data = original.readframes(count)
                            if len(data) != count * frame_bytes:
                                raise ValueError('The recording ended before the selected range.')
                            recording.writeframesraw(data)
                            remaining -= count
                    output.flush()
                    os.fsync(output.fileno())
                if identity(source) != expected:
                    raise ValueError('This recording changed during export.')
                rename_no_replace(draft, destination)
    return destination


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
        self.source = self.audio_device = self.recording = self.writer = self.current_file = None
        self.recovery_job = None
        self.close_after_recording = False

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
        self.record_button = self.button('Record', 'microphone', self.toggle_record)
        self.record_button.setObjectName('recordAction')
        self.record_button.setMinimumWidth(108)
        self.themeChanged.connect(self.style_capture)
        capture_actions = QHBoxLayout()
        capture_actions.addStretch()
        capture_actions.addWidget(self.record_button)
        meter_layout.addLayout(capture_actions)
        self.content.addWidget(meter_panel)

        library_header = QHBoxLayout()
        library_heading = QLabel('&Recordings')
        library_header.addWidget(library_heading)
        library_header.addStretch()
        self.play_button = self.button('', 'play', self.toggle_playback)
        self.open_button = self.button('', 'folder', self.open_recording)
        self.open_button.setAccessibleName('Open WAV…')
        self.open_button.setToolTip('Open WAV…')
        self.library_menu = QPushButton()
        self.library_menu.setAccessibleName('Recording actions')
        self.library_menu.setToolTip('Recording actions')
        self.library_menu.setProperty('mellipiSymbolicIcon', 'open-menu')
        menu = QMenu(self.library_menu)
        self.refresh_button = menu.addAction('Refresh recordings', self.refresh_library)
        menu.addAction('Recover unfinished recording…', self.recover_unfinished)
        self.recording_menu = QMenu(self)
        self.rename_button = self.recording_menu.addAction('Rename selected recording…', self.rename_selected)
        self.trim_button = self.recording_menu.addAction('Export trimmed copy…', self.trim_selected)
        self.trash_button = self.recording_menu.addAction('Move selected recording to Trash…', self.trash_selected)
        self.library_menu.setMenu(menu)
        for button in (self.play_button, self.open_button, self.library_menu):
            button.setMinimumSize(32, 32)
            library_header.addWidget(button)
        self.content.addLayout(library_header)
        self.space_controls(input_row, library_header)
        self.library = QListWidget()
        self.library.setMinimumHeight(88)
        self.library.setAccessibleName('Saved recordings')
        self.library.setUniformItemSizes(True)
        self.library.setAlternatingRowColors(True)
        library_heading.setBuddy(self.library)
        self.library.currentItemChanged.connect(self.select_library_item)
        self.library.itemActivated.connect(self.play_library_item)
        self.library.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.library.customContextMenuRequested.connect(self.recording_context)
        for action, key in ((self.rename_button, 'F2'), (self.trash_button, 'Delete')):
            action.setShortcut(key)
            action.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
            self.library.addAction(action)
        self.content.addWidget(self.library, 1)
        self.library_empty = QLabel('New recordings appear here.')
        self.library_empty.setObjectName('muted')
        self.content.addWidget(self.library_empty)
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
        active = self.recording is not None or self.recovery_job is not None
        finishing = self.recovery_job is not None or active and self.writer is not None and self.writer.ending
        playing = self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        self.inputs.setEnabled(not active and self.inputs.count() > 0)
        self.record_button.setEnabled(not finishing and (active or self.inputs.count() > 0))
        self.record_button.setText('Working…' if self.recovery_job else
                                   'Saving…' if finishing else 'Stop recording' if active else 'Record')
        self.record_button.setProperty('mellipiSymbolicIcon', 'stop' if active else 'microphone')
        self.play_button.setEnabled(self.current_file is not None and not active)
        playback_label = 'Stop playback' if playing else 'Play selected recording'
        self.play_button.setAccessibleName(playback_label)
        self.play_button.setToolTip(playback_label)
        self.play_button.setProperty('mellipiSymbolicIcon', 'stop' if playing else 'play')
        self.open_button.setEnabled(not active)
        self.library.setEnabled(not active)
        self.library_menu.setEnabled(not active)
        selected = self.selected_recording()
        self.rename_button.setEnabled(not active and selected is not None)
        self.trim_button.setEnabled(not active and selected is not None)
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
        writer = self.writer = CaptureWriter(self.recording, self)
        writer.finished.connect(lambda: self.capture_finished(writer))
        writer.start()
        source = QAudioSource(device, sample, self)
        self.source = source
        self.audio_device = source.start()
        if not self.audio_device or source.error() != QAudio.Error.NoError:
            self.finish_recording('Could not open the microphone.')
            return
        source.stateChanged.connect(self.capture_state)
        self.audio_device.readyRead.connect(self.read_audio)
        self.elapsed.setText('00:00')
        self.status.setText('Recording…')
        self.timer.start()
        self.update_controls()

    def capture_state(self, state):
        source = self.sender()
        if (source is self.source and state == QAudio.State.StoppedState and self.recording
                and source.error() != QAudio.Error.NoError):
            self.finish_recording('The microphone stopped unexpectedly.')

    def read_audio(self):
        if self.writer is None or self.audio_device is None:
            return
        if not self.writer.submit(bytes(self.audio_device.readAll())):
            self.finish_recording(drain=False)

    def update_meter(self):
        if self.recording is None:
            return
        self.show_time(self.recording.frames // self.recording.rate)
        self.meter.setValue(self.writer.take_peak())

    def show_time(self, seconds):
        self.elapsed.setText(f'{seconds // 60:02}:{seconds % 60:02}')

    def finish_recording(self, error='', preserve=True, *, drain=True):
        if self.writer is None:
            return
        io = self.audio_device
        if io is not None and preserve and drain:
            self.writer.submit(bytes(io.readAll()))
        self.stop_input()
        self.writer.stop(error, preserve)
        self.status.setText('Saving recording…')
        self.update_controls()

    def stop_input(self):
        source, self.source = self.source, None
        self.audio_device = None
        self.timer.stop()
        if source is not None:
            source.stop()
            source.deleteLater()

    def capture_finished(self, writer):
        self.stop_input()
        recording, self.recording = self.recording, None
        self.writer = None
        path = writer.path
        if writer.error:
            self.status.setText(f'Could not save recording: {writer.error}\nRecovery file: {recording.staging}')
        elif path is not None:
            self.set_recording(path)
            self.refresh_library()
            self.status.setText(f'{writer.issue} Saved {path.name}' if writer.issue else f'Saved {path.name}')
        elif recording.staging.exists():
            self.status.setText(f'{writer.issue or "Recording could not be finalized."}\nRecovery file: {recording.staging}')
        else:
            self.status.setText(writer.issue or 'No audio was captured.')
        self.show_time(recording.frames // recording.rate)
        self.meter.setValue(0)
        self.update_controls()
        pending, self.close_after_recording = self.close_after_recording, False
        writer.deleteLater()
        if pending and not writer.error and not recording.staging.exists():
            QTimer.singleShot(0, self.close)

    def set_recording(self, path):
        self.player.stop()
        self.current_file = path
        self.player.setSource(QUrl.fromLocalFile(str(path)) if path is not None else QUrl())
        self.update_controls()

    def selected_recording(self):
        row = self.library.currentItem()
        return row.data(Qt.ItemDataRole.UserRole) if row else None

    def recover_unfinished(self):
        if self.recording is not None or self.recovery_job is not None:
            return
        try:
            names = sorted((path.name for path in self.directory.glob('.recording-*.part')), reverse=True)[:100]
            if not names:
                self.status.setText('No unfinished recordings found.')
                return
            name, accepted = ThemedInput.getItem(self, 'Recover unfinished recording', 'Recording', names, 0, False)
            if not accepted or name not in names:
                return
        except OSError as error:
            self.status.setText(f'Could not recover recording: {error}')
            return
        job = self.recovery_job = RecoveryJob(self.directory / name, self)
        job.finished.connect(lambda: self.recovery_finished(job))
        self.status.setText('Recovering audio…')
        self.update_controls()
        job.start()

    def recovery_finished(self, job):
        self.recovery_job = None
        job.deleteLater()
        path = job.path
        if path is None:
            self.status.setText(f'Could not recover recording: {job.error}')
            self.update_controls()
            return
        self.set_recording(path)
        self.refresh_library()
        self.status.setText(f'Recovered {path.name}')

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

    def recording_context(self, position):
        item = self.library.itemAt(position)
        if item is not None:
            self.library.setCurrentItem(item)
            self.recording_menu.popup(self.library.viewport().mapToGlobal(position))

    def rename_selected(self):
        path = self.selected_recording()
        if path is None or self.recording is not None:
            return
        try:
            original = identity(path)
        except OSError:
            self.refresh_library()
            self.status.setText('This recording is no longer available.')
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
        try:
            if identity(path) != original:
                raise ValueError()
        except (OSError, ValueError):
            self.refresh_library()
            self.status.setText('This recording changed. Select it again before renaming.')
            return
        self.set_recording(None)
        try:
            rename_no_replace(path, destination)
        except (OSError, ValueError):
            self.set_recording(path)
            self.status.setText('Could not rename this recording. Check the name and folder permissions.')
            return
        self.set_recording(destination)
        self.refresh_library()
        self.status.setText(f'Renamed to {destination.name}')

    def trim_selected(self):
        source = self.selected_recording()
        if source is None or self.recording is not None or self.recovery_job is not None:
            return
        try:
            expected = identity(source)
            fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, 'rb') as stream, wave.open(stream, 'rb') as recording:
                rate, frames = recording.getframerate(), recording.getnframes()
                if not rate or not frames:
                    raise ValueError('This WAV has no playable audio.')
        except (OSError, wave.Error, ValueError, EOFError) as error:
            self.status.setText(f'Could not read recording: {error}')
            return
        dialog = QDialog(self)
        dialog.setWindowTitle('Export trimmed copy')
        form = QFormLayout(dialog)
        start, end = QDoubleSpinBox(), QDoubleSpinBox()
        for control in (start, end):
            control.setDecimals(3)
            control.setRange(0, frames / rate)
            control.setSuffix(' s')
        end.setValue(frames / rate)
        form.addRow('Start', start)
        form.addRow('End', end)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        style_dialog(dialog, self)
        accepted = exec_owned_dialog(dialog)
        first = round(start.value() * rate)
        last = frames if end.value() == end.maximum() else round(end.value() * rate)
        dialog.deleteLater()
        if accepted != QDialog.DialogCode.Accepted:
            return
        if last <= first:
            self.status.setText('The end must be after the start.')
            return
        proposed = source.with_name(source.stem + ' — trimmed.wav')
        value, _ = FileChooser.getSaveFileName(self, 'Save trimmed copy', str(proposed), 'WAV recordings (*.wav)',
                                               options=FileChooser.Option.DontConfirmOverwrite)
        if not value:
            return
        destination = Path(value)
        if destination.suffix.lower() != '.wav':
            destination = destination.with_name(destination.name + '.wav')
        job = self.recovery_job = RecoveryJob(source, self, lambda: trim_recording(source, destination, first, last, expected))
        self.status.setText('Exporting trimmed audio…')
        def finished():
            self.recovery_job = None
            job.deleteLater()
            self.refresh_library()
            self.status.setText(f'Saved trimmed copy to {destination.name}' if job.path is not None
                                else f'Could not export recording: {job.error}')
        job.finished.connect(finished)
        self.update_controls()
        job.start()

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
        if self.recovery_job is not None:
            self.status.setText('Wait for the file operation to finish before closing.')
            event.ignore()
            return
        if self.recording is not None:
            event.ignore()
            if self.writer.ending:
                self.close_after_recording = True
            elif themed_prompt(self, 'Stop recording?', 'Save the recording and close Sound Recorder?',
                               'Save and close', 'Keep recording'):
                self.close_after_recording = True
                self.finish_recording()
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
