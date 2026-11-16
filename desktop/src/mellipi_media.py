"""Mellipi Media: local audio and video with native MPRIS integration."""
import os
from pathlib import Path
import sys

os.environ['ORBIT_QT'] = '6'
os.environ['QT_WAYLAND_SHELL_INTEGRATION'] = 'xdg-shell'
os.environ.pop('QT_WAYLAND_DISABLE_WINDOWDECORATION', None)

import dbus
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop
from PyQt6.QtCore import Qt, QUrl, QSize
from PyQt6.QtGui import QActionGroup, QShortcut, QIcon, QKeySequence
from PyQt6.QtMultimedia import QAudioOutput, QMediaMetaData, QMediaPlayer
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtWidgets import (QSizePolicy, QApplication, QHBoxLayout, QLabel,
                             QListWidget, QListWidgetItem, QMenu, QSlider, QStackedWidget,
                             QPushButton, QToolButton, QVBoxLayout, QWidget)

import icon_theme
from app_palette import adjust_contrast
from file_chooser import FileChooser
from qt_app import AppWindow, ElidingLabel, symbolic_icon

MPRIS = 'org.mpris.MediaPlayer2'
PLAYER = MPRIS + '.Player'
PROPS = 'org.freedesktop.DBus.Properties'
TRACK = dbus.ObjectPath('/org/mpris/MediaPlayer2/Track/current')
MAX_QUEUE_ITEMS = 500
NO_TRACK = dbus.ObjectPath('/org/mpris/MediaPlayer2/TrackList/NoTrack')
EXTS = '*.mp3 *.wav *.flac *.ogg *.opus *.aac *.m4a *.mp4 *.mkv *.webm *.mov *.avi *.mpeg *.mpg'
REPEAT_MODES = {'None': 'Repeat off', 'Track': 'Repeat track', 'Playlist': 'Repeat queue'}


class PlayerBus(dbus.service.Object):
    def __init__(self, window):
        self.window = window
        self.name = dbus.service.BusName(MPRIS + '.MellipiMedia.instance' + str(os.getpid()),
                                         bus=dbus.SessionBus(mainloop=DBusGMainLoop()))
        super().__init__(self.name, '/org/mpris/MediaPlayer2')
        self.last = {}
    def values(self):
        w = self.window
        player = w.player
        metadata = {'mpris:trackid': w.track_id()}
        if w.path:
            metadata.update({'xesam:title': w.current_title(), 'xesam:url': w.path_url.toString()})
            if player.duration():
                metadata['mpris:length'] = dbus.Int64(player.duration() * 1000)
        return dict(
            PlaybackStatus={QMediaPlayer.PlaybackState.PlayingState: 'Playing',
                            QMediaPlayer.PlaybackState.PausedState: 'Paused'}.get(player.playbackState(), 'Stopped'),
            LoopStatus=w.repeat_mode, Rate=1.0, Shuffle=False,
            Metadata=dbus.Dictionary(metadata, signature='sv'),
            Volume=w.audio_output.volume(), Position=dbus.Int64(player.position() * 1000),
            MinimumRate=1.0, MaximumRate=1.0, CanGoNext=w.can_next(), CanGoPrevious=w.can_previous(),
            CanPlay=bool(w.path), CanPause=bool(w.path), CanSeek=player.isSeekable(), CanControl=True)

    @dbus.service.method(PROPS, in_signature='s', out_signature='a{sv}')
    def GetAll(self, interface):
        if interface == PLAYER:
            return self.values()
        if interface == MPRIS:
            return dict(CanQuit=True, CanRaise=True, HasTrackList=False,
                        Identity='Mellipi Media', DesktopEntry='mellipi-media',
                        SupportedUriSchemes=dbus.Array(['file'], signature='s'),
                        SupportedMimeTypes=dbus.Array(['audio/mpeg', 'video/mp4', 'video/webm'], signature='s'))
        raise dbus.DBusException('Unknown MPRIS interface', name='org.freedesktop.DBus.Error.UnknownInterface')

    @dbus.service.method(PROPS, in_signature='ss', out_signature='v')
    def Get(self, interface, name):
        try:
            return self.GetAll(interface)[name]
        except KeyError:
            raise dbus.DBusException('Unknown property', name='org.freedesktop.DBus.Error.UnknownProperty')

    @dbus.service.method(PROPS, in_signature='ssv')
    def Set(self, interface, name, value):
        if interface == PLAYER and name == 'Volume':
            self.window.audio_output.setVolume(min(1.0, max(0.0, float(value))))
            return
        if interface == PLAYER and name == 'LoopStatus':
            if isinstance(value, str) and value in REPEAT_MODES:
                self.window.set_repeat(value)
                return
            raise dbus.DBusException('Invalid repeat mode', name='org.freedesktop.DBus.Error.InvalidArgs')
        if interface == PLAYER and name in ('Rate', 'Shuffle') and value == self.values()[name]:
            return
        raise dbus.DBusException('Unsupported property setting', name='org.freedesktop.DBus.Error.PropertyReadOnly')

    @dbus.service.signal(PROPS, signature='sa{sv}as')
    def PropertiesChanged(self, interface, changes, invalidated):
        pass

    @dbus.service.signal(PLAYER, signature='x')
    def Seeked(self, position):
        pass

    def publish(self):
        current = self.values()
        current.pop('Position')
        changed = {key: value for key, value in current.items() if self.last.get(key) != value}
        if changed:
            self.PropertiesChanged(PLAYER, changed, [])
            self.last = current

    @dbus.service.method(MPRIS)
    def Raise(self):
        self.window.showNormal() if self.window.isMinimized() else self.window.show()
        self.window.raise_()
        self.window.activateWindow()

    @dbus.service.method(MPRIS)
    def Quit(self):
        self.window.close()

    @dbus.service.method(PLAYER)
    def Play(self):
        if self.window.path:
            self.window.player.play()

    @dbus.service.method(PLAYER)
    def Pause(self):
        self.window.player.pause()

    @dbus.service.method(PLAYER)
    def PlayPause(self):
        self.window.toggle()

    @dbus.service.method(PLAYER)
    def Stop(self):
        self.window.player.stop()

    @dbus.service.method(PLAYER)
    def Previous(self):
        self.window.advance(-1)

    @dbus.service.method(PLAYER)
    def Next(self):
        self.window.advance(1)

    @dbus.service.method(PLAYER, in_signature='x')
    def Seek(self, offset):
        self.window.seek(self.window.player.position() + int(offset) // 1000)

    @dbus.service.method(PLAYER, in_signature='ox')
    def SetPosition(self, track, position):
        if track == self.window.track_id() and self.window.path and 0 <= int(position) // 1000 <= self.window.player.duration():
            self.window.seek(int(position) // 1000)

    @dbus.service.method(PLAYER, in_signature='s')
    def OpenUri(self, uri):
        url = QUrl(uri)
        if url.isLocalFile() and not url.host():
            self.window.set_queue([url.toLocalFile()])


def elapsed(ms):
    minutes, seconds = divmod(max(0, ms) // 1000, 60)
    hours, minutes = divmod(minutes, 60)
    return f'{hours}:{minutes:02}:{seconds:02}' if hours else f'{minutes}:{seconds:02}'


class Media(AppWindow):
    extra_style = """
        QLabel#mediaQueueHeading { color: %(text)s; font-weight: 600; }
        QLabel#mediaPosition { color: %(muted)s; }
        QListWidget::item { padding: %(padding)dpx 8px; }
        QToolButton#mediaPrimary { background: %(selected_surface)s; }
        QLabel#mediaStageIcon { background: %(selected_surface)s; border-radius: %(radius)dpx; }
        QLabel#mediaStageTitle { color: %(text)s; font-weight: 600; }
        QLabel#mediaStageDetail { color: %(muted)s; }
        QToolButton#mediaPrimary:checked { background: %(accent)s; }
        QToolButton#mediaPrimary:hover:!checked { background: %(hover)s; }
        QToolButton#mediaRepeat:checked { background: %(selected_surface)s; border-color: %(focus)s; }
    """

    def __init__(self, paths=()):
        super().__init__('Media')
        self.setWindowIcon(QIcon.fromTheme('mellipi-media', QIcon.fromTheme('applications-multimedia')))
        self.resize(760, 470)
        self.setMinimumSize(420, 290)
        self.path, self.queue, self.index = None, [], -1
        self.repeat_mode = 'None'
        self.path_url = QUrl()
        self.track_number = 0
        self.bus = None
        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.audio_output.setVolume(.7)
        self.player.setAudioOutput(self.audio_output)

        self.open_button = self.tool('document-open', 'Open media', self.choose)
        self.header.addWidget(self.open_button)
        self.queue_toggle = self.tool('view-list', 'Show queue (Ctrl+L)', self.toggle_queue)
        self.queue_toggle.setCheckable(True)
        self.header.addWidget(self.queue_toggle)
        stage = QStackedWidget()
        self.stage = stage
        self.content.addWidget(stage, 1)
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        self.title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.summary = QWidget()
        status = QVBoxLayout(self.summary)
        status.setContentsMargins(12, 4, 12, 4)
        status.setSpacing(6)
        status.addStretch()
        self.stage_icon = QLabel()
        self.stage_icon.setObjectName('mediaStageIcon')
        self.stage_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        status.addWidget(self.stage_icon, alignment=Qt.AlignmentFlag.AlignHCenter)
        self.message = ElidingLabel('Open an audio or video file')
        self.message.setObjectName('mediaStageTitle')
        self.message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        status.addWidget(self.message)
        self.stage_detail = ElidingLabel()
        self.stage_detail.setObjectName('mediaStageDetail')
        self.stage_detail.setTextFormat(Qt.TextFormat.PlainText)
        self.stage_detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        status.addWidget(self.stage_detail)
        self.stage_open = QPushButton('Open media…')
        self.stage_open.setObjectName('emptyStageAction')
        self.stage_open.clicked.connect(self.choose)
        status.addWidget(self.stage_open, alignment=Qt.AlignmentFlag.AlignHCenter)
        status.addStretch()
        stage.addWidget(self.summary)
        self.video = QVideoWidget()
        self.video.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
        stage.addWidget(self.video)
        self.player.setVideoOutput(self.video)
        self.queue_panel = QWidget()
        queue_layout = QVBoxLayout(self.queue_panel)
        queue_layout.setContentsMargins(0, 0, 0, 0)
        queue_layout.setSpacing(4)
        queue_actions = QHBoxLayout()
        self.queue_title = QLabel('Queue')
        self.queue_title.setObjectName('mediaQueueHeading')
        queue_actions.addWidget(self.queue_title, 1)
        self.queue_add = self.tool('tab-new', 'Add files to queue', self.choose_append)
        self.queue_play = self.tool('media-playback-start', 'Play selected track', self.play_selected)
        self.queue_remove = self.tool('edit-delete', 'Remove selected track', self.remove_selected)
        for button in (self.queue_add, self.queue_play, self.queue_remove):
            queue_actions.addWidget(button)
        queue_layout.addLayout(queue_actions)
        self.queue_view = QListWidget()
        self.queue_view.setAccessibleName('Playback queue')
        self.queue_view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.queue_view.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.queue_view.setUniformItemSizes(True)
        self.queue_view.currentRowChanged.connect(self.update_queue_actions)
        self.queue_view.itemActivated.connect(lambda item: self.load(self.queue_view.row(item)))
        queue_layout.addWidget(self.queue_view, 1)
        self.content.addWidget(self.queue_panel, 1)
        self.queue_panel.hide()

        seek_controls = QHBoxLayout()
        seek_controls.setSpacing(10)
        controls = QHBoxLayout()
        self.space_controls(controls, seek_controls)
        self.content.addLayout(seek_controls)
        self.content.addLayout(controls)
        self.previous = self.tool('media-skip-backward', 'Previous', lambda: self.advance(-1))
        self.play = self.tool('media-playback-start', 'Play', self.toggle)
        self.next = self.tool('media-skip-forward', 'Next', lambda: self.advance(1))
        self.stop = self.tool('media-playback-stop', 'Stop', self.player.stop)
        for button in (self.previous, self.play, self.stop, self.next):
            controls.addWidget(button)
        self.repeat_button = self.tool('view-refresh', 'Repeat off', lambda: None)
        self.repeat_button.setObjectName('mediaRepeat')
        self.repeat_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.repeat_button.setCheckable(True)
        repeat_menu = QMenu(self.repeat_button)
        repeat_group = QActionGroup(repeat_menu)
        self.repeat_actions = {}
        for mode, label in REPEAT_MODES.items():
            choice = repeat_menu.addAction(label)
            choice.setCheckable(True)
            repeat_group.addAction(choice)
            choice.triggered.connect(lambda _checked=False, mode=mode: self.set_repeat(mode))
            self.repeat_actions[mode] = choice
        self.repeat_actions[self.repeat_mode].setChecked(True)
        self.repeat_button.setMenu(repeat_menu)
        controls.addWidget(self.repeat_button)
        self.time = QLabel('0:00 / 0:00')
        self.time.setObjectName('mediaPosition')
        self.time.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.time.setAccessibleName('Elapsed time and duration')
        self.timeline = QSlider(Qt.Orientation.Horizontal)
        self.timeline.setAccessibleName('Playback position')
        self.timeline.sliderMoved.connect(self.seek)
        self.timeline.actionTriggered.connect(
            lambda _: self.seek(self.timeline.sliderPosition()) if not self.timeline.isSliderDown() else None)
        seek_controls.addWidget(self.timeline, 1)
        seek_controls.addWidget(self.time)
        controls.addStretch(1)
        self.play.setObjectName('mediaPrimary')
        self.play.setCheckable(True)
        self.mute = self.tool('audio-volume-high', 'Mute', lambda: self.audio_output.setMuted(not self.audio_output.isMuted()))
        controls.addWidget(self.mute)
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setAccessibleName('Playback volume')
        self.volume.setRange(0, 100)
        self.volume.setValue(round(self.audio_output.volume() * 100))
        self.volume.valueChanged.connect(lambda value: self.audio_output.setVolume(value / 100))
        controls.addWidget(self.volume)
        self.audio_output.volumeChanged.connect(lambda value: self.volume.setValue(round(value * 100)))
        self.audio_output.volumeChanged.connect(self.publish)
        self.audio_output.mutedChanged.connect(self.update_controls)
        self.player.playbackStateChanged.connect(self.update_controls)
        self.player.hasVideoChanged.connect(self.update_controls)
        self.player.seekableChanged.connect(self.update_controls)
        self.player.metaDataChanged.connect(self.update_controls)
        self.player.durationChanged.connect(self.duration_changed)
        self.player.positionChanged.connect(self.position_changed)
        self.player.mediaStatusChanged.connect(self.media_status)
        self.player.errorOccurred.connect(self.error)
        QShortcut(QKeySequence.StandardKey.Open, self).activated.connect(self.choose)
        self.space = QShortcut(QKeySequence(Qt.Key.Key_Space), self.stage)
        self.space.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.space.activated.connect(self.toggle)
        self.stage.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.stage.setFocus()
        try:
            self.bus = PlayerBus(self)
        except dbus.DBusException:
            pass
        self.themeChanged.connect(self.apply_control_metrics)
        self.apply_control_metrics()
        self.refresh_icons()
        self.update_controls()
        self.update_queue_actions()
        QShortcut(QKeySequence('Ctrl+L'), self).activated.connect(self.queue_toggle.click)
        if paths:
            self.set_queue(paths)

    def apply_control_metrics(self):
        scale = self.theme['text_scale']
        self.queue_panel.setMaximumHeight(round(160 + 45 * max(0, scale - 1)))
        queue_row_height = self.queue_view.fontMetrics().height() + 2 * self.theme['padding']
        self.queue_view.setMinimumHeight(2 * (queue_row_height + 1) + 2 * self.queue_view.frameWidth())
        badge = round(42 * min(1.25, scale))
        self.stage_icon.setFixedSize(badge, badge)
        self.message.setStyleSheet(f"font-size: {round(self.theme['font_size'] * 1.25)}px;")
        self.refresh_stage_icon()
        if self.play.isChecked():
            self.play.setIcon(symbolic_icon('media-playback-pause', self.theme['accent_text']))
        self.volume.setMinimumWidth(64)
        self.volume.setMaximumWidth(round(90 * min(1.25, scale)))
        side = max(16, round(16 * scale))
        for button in self.findChildren(QToolButton):
            button.setIconSize(QSize(side, side))
            button.setMinimumSize(max(30, side+10), max(30, side+10))

    def refresh_stage_icon(self):
        surface = self.theme['selected_surface']
        base = self.theme['text']
        endpoint = '#000000' if self.theme_watch.preferences.values['mode'] == 'light' else '#ffffff'
        ink = adjust_contrast('#648ddc', [surface], 4.5, endpoint)
        if self.theme_watch.preferences.appearance()['highContrast']:
            ink = base
        size = round(self.stage_icon.width() * .56)
        art = symbolic_icon('audio-x-generic', ink)
        if art.isNull():
            art = symbolic_icon('media-playback-start', ink)
        self.stage_icon.setPixmap(art.pixmap(size, size))

    def tool(self, name, label, action):
        button = QToolButton()
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.configure_tool(button, name, label)
        button.clicked.connect(action)
        return button

    def configure_tool(self, button, name, label):
        button.setProperty('mellipiSymbolicIcon', name)
        icon = symbolic_icon(name, self.theme['accent_ink'])
        button.setIcon(icon)
        button.setText(label)
        button.setAccessibleName(label)
        button.setToolTip(label)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly if icon.isNull() else Qt.ToolButtonStyle.ToolButtonIconOnly)

    def choose(self):
        files = FileChooser.getOpenFileNames(self, 'Open media', '', f'Media files ({EXTS});;All files (*)')[0]
        if files:
            self.set_queue(files)

    def choose_append(self):
        files = FileChooser.getOpenFileNames(self, 'Add to queue', '', f'Media files ({EXTS});;All files (*)')[0]
        if files:
            self.append_queue(files)

    @staticmethod
    def local_tracks(files, limit):
        tracks = []
        for name in files[:MAX_QUEUE_ITEMS]:
            if len(tracks) >= limit:
                break
            url = QUrl(name)
            if name.startswith('file:'):
                if not url.isLocalFile() or url.host():
                    continue
                name = url.toLocalFile()
            try:
                path = Path(name).resolve()
                if path.is_file():
                    tracks.append(path)
            except (OSError, RuntimeError):
                continue
        return tracks

    def set_queue(self, files):
        queue = self.local_tracks(files, MAX_QUEUE_ITEMS)
        if not queue:
            if not self.path:
                self.stage.setCurrentWidget(self.summary)
                self.message.setText('Select a local audio or video file.')
            return
        self.queue = queue
        self.load(0)

    def append_queue(self, files):
        tracks = self.local_tracks(files, MAX_QUEUE_ITEMS - len(self.queue))
        if not tracks:
            return
        if not self.queue:
            self.queue = tracks
            self.load(0)
        else:
            selection = self.queue_view.currentRow()
            self.queue.extend(tracks)
            self.sync_loops()
            self.refresh_queue(selection)
            self.update_controls()

    def toggle_queue(self, showing):
        self.queue_panel.setVisible(showing)
        title = 'Hide queue (Ctrl+L)' if showing else 'Show queue (Ctrl+L)'
        self.queue_toggle.setAccessibleName(title)
        self.queue_toggle.setToolTip(title)
        self.refresh_queue(self.index)
        if showing:
            self.queue_view.setFocus()
        else:
            self.stage.setFocus()

    def refresh_queue(self, selected):
        self.queue_view.clear()
        for index, path in enumerate(self.queue):
            title = path.name + (' — Current track' if index == self.index else '')
            item = QListWidgetItem(title)
            item.setToolTip(str(path))
            self.queue_view.addItem(item)
        if self.queue:
            self.queue_view.setCurrentRow(max(0, min(selected, len(self.queue) - 1)))
        self.queue_title.setText(f'Queue · {len(self.queue)}')
        self.queue_title.setToolTip(f'{len(self.queue)} of {MAX_QUEUE_ITEMS} track slots used')
        self.update_queue_actions()

    def update_queue_actions(self, *_):
        row = self.queue_view.currentRow()
        valid = 0 <= row < len(self.queue)
        self.queue_play.setEnabled(valid)
        self.queue_remove.setEnabled(valid and row != self.index)

    def play_selected(self):
        row = self.queue_view.currentRow()
        if row == self.index and self.path:
            self.player.play()
        else:
            self.load(row)

    def remove_selected(self):
        row = self.queue_view.currentRow()
        if not 0 <= row < len(self.queue) or row == self.index:
            return
        self.queue.pop(row)
        self.sync_loops()
        if row < self.index:
            self.index -= 1
        self.refresh_queue(row)
        self.update_controls()

    def load(self, index):
        if not 0 <= index < len(self.queue):
            return
        self.index = index
        self.track_number += 1
        self.path = self.queue[index]
        self.path_url = QUrl.fromLocalFile(str(self.path))
        self.sync_loops()
        self.player.setSource(self.path_url)
        self.player.play()
        self.refresh_queue(index)
        self.update_controls()

    def track_id(self):
        return dbus.ObjectPath(str(TRACK) + str(self.track_number)) if self.path else NO_TRACK

    def can_next(self):
        return self.next_index(1) is not None

    def can_previous(self):
        return self.next_index(-1) is not None

    def next_index(self, delta):
        total = len(self.queue)
        if not 0 <= self.index < total:
            return None
        index = self.index + delta
        if 0 <= index < total:
            return index
        if self.repeat_mode == 'Playlist' and total > 1:
            return index % total
        return None

    def advance(self, delta):
        index = self.next_index(delta)
        if index is not None:
            self.load(index)

    def set_repeat(self, mode):
        if mode not in REPEAT_MODES or mode == self.repeat_mode:
            return
        self.repeat_mode = mode
        self.repeat_actions[mode].setChecked(True)
        self.repeat_button.setChecked(mode != 'None')
        self.configure_tool(self.repeat_button, 'view-refresh', REPEAT_MODES[mode])
        self.sync_loops()
        self.update_controls()

    def sync_loops(self):
        repeat_current = self.repeat_mode == 'Track' or (
            self.repeat_mode == 'Playlist' and len(self.queue) == 1)
        self.player.setLoops(QMediaPlayer.Loops.Infinite.value if repeat_current else 1)

    def toggle(self):
        if self.path:
            if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                self.player.pause()
            else:
                self.player.play()

    def current_title(self):
        value = self.player.metaData().value(QMediaMetaData.Key.Title) or (self.path.name if self.path else 'Media')
        return ' '.join(str(value).split())[:300] or 'Media'

    def seek(self, value):
        if not self.player.isSeekable():
            return
        position = min(self.player.duration(), max(0, int(value)))
        self.player.setPosition(position)
        if self.bus:
            self.bus.Seeked(position * 1000)

    def duration_changed(self, value):
        self.timeline.setMaximum(min(value, 2_147_483_647))
        self.position_changed(self.player.position())
        self.publish()

    def position_changed(self, value):
        if not self.timeline.isSliderDown():
            self.timeline.setValue(min(value, self.timeline.maximum()))
        self.time.setText(f'{elapsed(value)} / {elapsed(self.player.duration())}')

    def media_status(self, status):
        if status == QMediaPlayer.MediaStatus.EndOfMedia and self.can_next():
            self.advance(1)

    def error(self, code):
        if code != QMediaPlayer.Error.NoError:
            self.stage.setCurrentWidget(self.summary)
            self.message.setText('Could not play this file')
            self.stage_detail.setText(self.player.errorString() or 'Media playback is unavailable.')
            self.open_button.hide()
            self.stage_open.show()

    def publish(self, *_):
        if self.bus:
            self.bus.publish()

    def update_controls(self, *_):
        active = self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        self.configure_tool(self.play, 'media-playback-pause' if active else 'media-playback-start',
                            'Pause' if active else 'Play')
        self.play.setChecked(active)
        if active:
            self.play.setIcon(symbolic_icon('media-playback-pause', self.theme['accent_text']))
        muted = self.audio_output.isMuted()
        self.configure_tool(self.mute, 'audio-volume-muted' if muted else 'audio-volume-high',
                            'Unmute' if muted else 'Mute')
        self.previous.setEnabled(self.can_previous())
        self.next.setEnabled(self.can_next())
        self.play.setEnabled(bool(self.path))
        self.stop.setEnabled(bool(self.path and self.player.playbackState() != QMediaPlayer.PlaybackState.StoppedState))
        self.timeline.setEnabled(self.player.isSeekable())
        self.repeat_button.setEnabled(bool(self.path))
        playable = self.player.error() == QMediaPlayer.Error.NoError
        self.open_button.setVisible(bool(self.path) and playable)
        self.stage.setCurrentWidget(self.video if playable and self.player.hasVideo() else self.summary)
        if self.path and playable:
            self.title.setText(self.current_title())
            self.message.setText(self.current_title())
            self.stage_detail.setText('Playing' if active else 'Paused' if
                                      self.player.playbackState() == QMediaPlayer.PlaybackState.PausedState
                                      else 'Ready to play')
            self.stage_open.hide()
        elif not self.path:
            self.stage_detail.setText('Audio and video from your device')
            self.stage_open.show()
        self.publish()

    def closeEvent(self, event):
        self.player.stop()
        if self.bus:
            self.bus.remove_from_connection()
            self.bus = None
        super().closeEvent(event)


def main():
    args = sys.argv[1:]
    app = QApplication([sys.argv[0]])
    app.setApplicationName('Media')
    app.setOrganizationName('Mellipi')
    app.setDesktopFileName('mellipi-media')
    icon_theme.configure()
    window = Media(args)
    window.show()
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
