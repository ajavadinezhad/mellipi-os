"""A small local image viewer and markup tool for Mellipi."""
import argparse
import math
import os
from pathlib import Path
import sys
import uuid

os.environ['ORBIT_QT'] = '6'
os.environ['QT_WAYLAND_SHELL_INTEGRATION'] = 'xdg-shell'
os.environ.pop('QT_WAYLAND_DISABLE_WINDOWDECORATION', None)

from PyQt6.QtCore import QIODevice, QPointF, QRect, QRectF, QSaveFile, QSize, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import (
    QColor, QIcon, QImage, QImageReader, QImageWriter, QKeySequence, QPainter,
    QPainterPath, QPen, QPixmap, QShortcut, QTransform,
)
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy,
    QSpinBox, QVBoxLayout, QWidget,
)

from file_chooser import FileChooser
from qt_app import exec_owned_dialog, style_dialog, AppWindow, symbolic_icon, themed_choice, themed_prompt

MAX_IMAGE_PIXELS = 16_000_000
MAX_IMAGE_BYTES = 80 * 1024 * 1024
MAX_HISTORY_BYTES = 64 * 1024 * 1024
MAX_HISTORY_STEPS = 10
VISIBLE_TYPES = {'.' + bytes(fmt).decode('ascii').lower() for fmt in QImageReader.supportedImageFormats()}


def local_file(value):
    """Accept regular local files, including file URLs from desktop launchers."""
    if value.startswith('file:'):
        url = QUrl(value)
        if not url.isValid() or not url.isLocalFile() or url.host() not in ('', 'localhost'):
            raise ValueError('Choose a file on this computer.')
        value = url.toLocalFile()
    path = Path(value).expanduser().absolute()
    if not path.is_file():
        raise ValueError('This file could not be opened.')
    return path


def action(text, icon, callback, parent, shortcut=None, caption=None):
    button = QPushButton(caption or '', parent)
    button.setObjectName('photoAction')
    button.setMinimumHeight(32)
    symbolic_name = icon.removesuffix('-symbolic')
    themed = symbolic_icon(symbolic_name, parent.theme['accent_ink'])
    if themed.isNull():
        if not caption:
            button.setText(text)
    else:
        button.setProperty('mellipiSymbolicIcon', symbolic_name)
        button.setIcon(themed)
        button.setIconSize(QSize(16, 16))
    button.setToolTip(text)
    button.setAccessibleName(text)
    button.clicked.connect(callback)
    if shortcut:
        key = QShortcut(QKeySequence(shortcut), parent)
        key.activated.connect(button.click)
    return button


def status_label(text=''):
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(True)
    widget.setObjectName('muted')
    return widget


class PhotoSurface(QLabel):
    cropChanged = pyqtSignal(bool)
    strokeFinished = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.image_size = QSize()
        self.mode = ''
        self.origin = None
        self.end = None
        self.stroke = None
        self.accent = QColor('#a9d9c3')
        self.pen = QColor('#f26764')

    def picture_rect(self):
        pixmap = self.pixmap()
        if pixmap.isNull():
            return QRectF()
        actual = pixmap.deviceIndependentSize()
        bounds = self.contentsRect()
        return QRectF(bounds.x() + (bounds.width() - actual.width()) / 2,
                      bounds.y() + (bounds.height() - actual.height()) / 2,
                      actual.width(), actual.height())

    def to_pixel(self, pos, clamp=False):
        picture = self.picture_rect()
        if picture.isEmpty() or self.image_size.isEmpty() or (not clamp and not picture.contains(pos)):
            return None
        x = (pos.x() - picture.x()) * self.image_size.width() / picture.width()
        y = (pos.y() - picture.y()) * self.image_size.height() / picture.height()
        return QPointF(max(0., min(x, self.image_size.width())),
                       max(0., min(y, self.image_size.height())))

    def crop_rect(self):
        if self.origin is None or self.end is None:
            return QRect()
        if abs(self.origin.x() - self.end.x()) < 1 or abs(self.origin.y() - self.end.y()) < 1:
            return QRect()
        return QRectF(self.origin, self.end).normalized().toAlignedRect().intersected(
            QRect(0, 0, self.image_size.width(), self.image_size.height()))

    def clear_gesture(self):
        self.origin = None
        self.end = None
        self.stroke = None
        self.cropChanged.emit(False)
        self.update()

    def mousePressEvent(self, event):
        point = self.to_pixel(event.position())
        if not self.mode or point is None or event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        self.clear_gesture()
        self.origin = point
        if self.mode == 'pen':
            self.stroke = QPainterPath(point)
            self.stroke.lineTo(point + QPointF(.01, .01))
        self.update()
        event.accept()

    def mouseMoveEvent(self, event):
        point = self.to_pixel(event.position(), clamp=True)
        if not self.mode or self.origin is None or point is None or not event.buttons() & Qt.MouseButton.LeftButton:
            return super().mouseMoveEvent(event)
        if self.mode == 'pen' and self.stroke is not None:
            if self.stroke.elementCount() < 8192:
                self.stroke.lineTo(point)
        elif self.mode == 'crop':
            self.end = point
            self.cropChanged.emit(not self.crop_rect().isEmpty())
        self.update()
        event.accept()

    def mouseReleaseEvent(self, event):
        point = self.to_pixel(event.position(), clamp=True)
        if not self.mode or self.origin is None or point is None or event.button() != Qt.MouseButton.LeftButton:
            return super().mouseReleaseEvent(event)
        if self.mode == 'pen' and self.stroke is not None:
            stroke = self.stroke
            stroke.lineTo(point)
            self.clear_gesture()
            self.strokeFinished.emit(stroke)
        elif self.mode == 'crop':
            self.end = point
            self.cropChanged.emit(not self.crop_rect().isEmpty())
            self.update()
        event.accept()

    def paintEvent(self, event):
        super().paintEvent(event)
        picture = self.picture_rect()
        if picture.isEmpty() or self.image_size.isEmpty() or (self.stroke is None and self.crop_rect().isEmpty()):
            return
        painter = QPainter(self)
        painter.setClipRect(picture)
        painter.translate(picture.x(), picture.y())
        painter.scale(picture.width() / self.image_size.width(), picture.height() / self.image_size.height())
        if self.stroke is not None:
            draw_ink(painter, self.stroke, self.pen, self.image_size)
        else:
            selection = QRectF(self.crop_rect())
            mask = QPainterPath()
            mask.addRect(QRectF(0, 0, self.image_size.width(), self.image_size.height()))
            mask.addRect(selection)
            painter.fillPath(mask, QColor(0, 0, 0, 115))
            border = QPen(self.accent, 2)
            border.setCosmetic(True)
            painter.setPen(border)
            painter.drawRect(selection)
        painter.end()


def draw_ink(painter, path, color, size):
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    width = max(2, min(18, min(size.width(), size.height()) / 100))
    for ink, weight in ((QColor('#202229'), width + 2), (color, width)):
        painter.setPen(QPen(ink, weight, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                            Qt.PenJoinStyle.RoundJoin))
        painter.drawPath(path)


def save_copy(path, image):
    """Write full-resolution PNG atomically; no partial result if it fails."""
    stream = QSaveFile(str(path))
    stream.setDirectWriteFallback(False)
    if not stream.open(QIODevice.OpenModeFlag.WriteOnly):
        raise OSError(stream.errorString())
    writer = QImageWriter(stream, b'png')
    if not writer.write(image):
        stream.cancelWriting()
        raise OSError(writer.errorString())
    if not stream.commit():
        raise OSError(stream.errorString())


class Canvas(QScrollArea):
    def __init__(self, prompt, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label = PhotoSurface()
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.label.setWordWrap(True)
        self.setWidget(self.label)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        self.image = QImage()
        self.zoom = None
        self.show_message(prompt)

    def show_message(self, message):
        self.image = QImage()
        self.label.setMinimumSize(0, 0)
        self.label.setText(message)

    def set_image(self, image):
        self.image = image
        self.label.image_size = image.size()
        self.update_image()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_image()

    def update_image(self):
        if self.image.isNull():
            return
        if self.zoom is None:
            self.label.setMinimumSize(0, 0)
            viewport = self.viewport().size()
            size = self.image.size().scaled(QSize(max(1, viewport.width() - 4),
                                                  max(1, viewport.height() - 4)), Qt.AspectRatioMode.KeepAspectRatio)
        else:
            size = QSize(max(1, round(self.image.width() * self.zoom)),
                         max(1, round(self.image.height() * self.zoom)))
        ratio = max(1, self.devicePixelRatioF())
        # Keep the scaled raster bounded, including on HiDPI outputs.
        budget = min(ratio, math.sqrt(MAX_IMAGE_PIXELS / (size.width() * size.height())))
        pixels = QSize(max(1, round(size.width() * budget)), max(1, round(size.height() * budget)))
        pixmap = QPixmap.fromImage(self.image.scaled(pixels, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        pixmap.setDevicePixelRatio(budget)
        if self.zoom is not None:
            self.label.setMinimumSize(size)
        self.label.setPixmap(pixmap)

    def set_zoom(self, factor):
        self.zoom = factor
        self.update_image()

    def zoom_by(self, multiplier):
        if self.image.isNull():
            return
        start = self.zoom
        if start is None:
            viewport = self.viewport().size()
            start = min(viewport.width() / self.image.width(), viewport.height() / self.image.height())
        self.set_zoom(min(4, max(.05, start * multiplier)))


def read_photo(path):
    if path.stat().st_size > MAX_IMAGE_BYTES:
        raise ValueError('This image is too large to open.')
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    size = reader.size()
    if not size.isValid() or min(size.width(), size.height()) <= 0:
        raise ValueError('This image is damaged or its format is unsupported.')
    pixels = size.width() * size.height()
    # A codec may decode the full source before scaling its output.
    if pixels > MAX_IMAGE_PIXELS:
        raise ValueError('This image is too large to open.')
    result = reader.read()
    if result.isNull():
        raise ValueError('This image is damaged or its format is unsupported.')
    return result, size


class PhotosWindow(AppWindow):
    extra_style = """
        QPushButton#photoAction { padding: 4px 6px; }
        QPushButton#photoAction:checked {
            background: %(selected_surface)s; border-color: %(control_border)s;
        }
        QPushButton#photoAction:focus { border-color: %(focus)s; }
        QWidget#photoEditBar { background: %(surface)s; border-radius: %(radius)dpx; }
    """

    def __init__(self, value=None):
        super().__init__('Photos')
        self.setWindowIcon(QIcon.fromTheme('mellipi-photos', QIcon.fromTheme('image-x-generic')))
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        self.title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.resize(840, 570)
        self.setMinimumSize(405, 300)
        self.setAcceptDrops(True)
        self.images = []
        self.index = -1
        self.path = None
        self.history = []
        self.future = []
        self.revision = self.saved_revision = None
        self.slideshow = QTimer(self, interval=3500)
        self.slideshow.timeout.connect(self.advance_slideshow)
        toolbar = QHBoxLayout()
        toolbar.setSpacing(4)
        self.open_button = action('Open image', 'document-open-symbolic', self.choose_file, self, QKeySequence.StandardKey.Open)
        toolbar.addWidget(self.open_button)
        self.open_button.hide()
        self.previous = action('Previous image', 'go-previous-symbolic', lambda: self.move(-1), self, Qt.Key.Key_Left)
        self.next = action('Next image', 'go-next-symbolic', lambda: self.move(1), self, Qt.Key.Key_Right)
        toolbar.addWidget(self.previous)
        toolbar.addWidget(self.next)
        self.slideshow_button = action('Play slideshow', 'media-playback-start', self.toggle_slideshow, self, 'F5')
        self.slideshow_button.setCheckable(True)
        toolbar.addWidget(self.slideshow_button)
        toolbar.addWidget(action('Paste image', 'edit-paste', self.paste, self, QKeySequence.StandardKey.Paste))
        toolbar.addStretch()
        self.tools = [
            action('Zoom out', 'zoom-out-symbolic', lambda: self.canvas.zoom_by(.8), self, QKeySequence.StandardKey.ZoomOut),
            action('Zoom in', 'zoom-in-symbolic', lambda: self.canvas.zoom_by(1.25), self, QKeySequence.StandardKey.ZoomIn),
            action('Fit image', 'zoom-fit-best-symbolic', lambda: self.canvas.set_zoom(None), self, 'Ctrl+0'),
            action('Rotate clockwise', 'object-rotate-right-symbolic', self.rotate, self, 'R'),
            action('Copy image', 'edit-copy-symbolic', self.copy, self, QKeySequence.StandardKey.Copy),
        ]
        for button in self.tools:
            toolbar.addWidget(button)
        self.edit_toggle = action('Edit image', 'document-edit', self.toggle_edit, self, 'E')
        self.edit_toggle.setCheckable(True)
        toolbar.addWidget(self.edit_toggle)
        self.content.addLayout(toolbar)
        self.edit_bar = QWidget()
        self.edit_bar.setObjectName('photoEditBar')
        edit_stack = QVBoxLayout(self.edit_bar)
        edit_stack.setContentsMargins(6, 6, 6, 6)
        edit_stack.setSpacing(4)
        edit = QHBoxLayout()
        edit.setSpacing(4)
        edit_stack.addLayout(edit)
        self.crop_btn = action('Select a crop area', 'image-crop', lambda: self.set_mode('crop'), self)
        self.crop_btn.setCheckable(True)
        self.pen_btn = action('Draw on image', 'document-edit', lambda: self.set_mode('pen'), self)
        self.pen_btn.setCheckable(True)
        edit.addWidget(self.crop_btn)
        edit.addWidget(self.pen_btn)
        self.pen_color = QComboBox()
        self.pen_color.setAccessibleName('Pen color')
        for name, color in (('Coral', '#f26764'), ('Amber', '#ffd268'), ('Cyan', '#68dcf0'), ('White', '#ffffff')):
            self.pen_color.addItem(name, color)
        self.pen_color.currentIndexChanged.connect(self.set_pen_color)
        self.pen_color.hide()
        edit.addWidget(self.pen_color)
        edit.addWidget(action('Resize image', 'view-restore', self.resize_dialog, self))
        edit.addStretch()
        edit_actions = QHBoxLayout()
        edit_actions.setSpacing(4)
        edit_actions.addStretch()
        edit_stack.addLayout(edit_actions)
        self.apply_btn = action('Apply crop', 'check', self.crop, self, caption='Apply crop')
        self.apply_btn.hide()
        self.apply_btn.setEnabled(False)
        edit_actions.addWidget(self.apply_btn)
        self.undo_btn = action('Undo last edit', 'edit-undo', self.undo, self, QKeySequence.StandardKey.Undo)
        self.redo_btn = action('Redo last edit', 'edit-redo', self.redo, self, QKeySequence.StandardKey.Redo)
        self.save_btn = action('Save an edited copy', 'document-save-as', self.save_as, self, 'Ctrl+Shift+S', 'Save copy…')
        edit_actions.addWidget(self.undo_btn)
        edit_actions.addWidget(self.redo_btn)
        edit_actions.addWidget(self.save_btn)
        self.edit_bar.hide()
        self.content.addWidget(self.edit_bar)
        self.canvas = Canvas('Open an image or drop one here.')
        self.canvas.setAccessibleName('Image preview')
        self.canvas.label.cropChanged.connect(self.apply_btn.setEnabled)
        self.canvas.label.strokeFinished.connect(self.ink)
        self.themeChanged.connect(self.set_canvas_accent)
        self.set_canvas_accent()
        QShortcut(QKeySequence('Escape'), self).activated.connect(self.escape)
        QShortcut(QKeySequence.StandardKey.Save, self).activated.connect(self.save_as)

        self.start_stage = self.empty_stage('Photos', 'Drop an image here or paste from the clipboard.', 'Open image…', self.choose_file)
        self.content.addWidget(self.start_stage, 1)
        self.canvas.hide()
        self.content.addWidget(self.canvas, 1)
        self.status = status_label()
        self.status.setAccessibleName('Image information')
        self.content.addWidget(self.status)
        self.update_buttons()
        self.themeChanged.connect(self.polish_photo_controls)
        self.polish_photo_controls()
        if value:
            self.open_path(value)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'edit_toggle'):
            self.polish_photo_controls()

    def polish_photo_controls(self):
        scaled = self.theme['text_scale']
        narrow = self.width() < round(420 * scaled)
        size = min(20 if narrow else 24, max(16, round(16 * scaled)))
        for button in self.findChildren(QPushButton, 'photoAction'):
            button.setIconSize(QSize(size, size))


    def choose_file(self):
        value, _ = FileChooser.getOpenFileName(self, 'Open image', '', 'Images (' + ' '.join('*' + s for s in sorted(VISIBLE_TYPES)) + ');;All files (*)')
        if value:
            self.open_path(value)

    def open_path(self, value):
        self.stop_slideshow()
        try:
            path = local_file(value)
            image, _size = read_photo(path)
        except (OSError, ValueError) as error:
            self.status.setText(str(error))
            return False
        images = []
        try:
            # Do not enumerate an unbounded directory or follow special files.
            with os.scandir(path.parent) as entries:
                for number, entry in enumerate(entries):
                    if number >= 4096:
                        break
                    sibling = Path(entry.path)
                    if sibling.suffix.lower() in VISIBLE_TYPES and entry.is_file():
                        images.append(sibling)
        except OSError:
            pass
        if path not in images:
            images.append(path)
        if not self.confirm_leave():
            return False
        self.images = sorted(images, key=lambda item: (item.name.casefold(), item.name))
        self.index = self.images.index(path)
        self.display(path, image)
        return True

    def display(self, path, image):
        self.start_stage.hide()
        self.open_button.show()
        self.canvas.show()
        self.path = path
        self.history.clear()
        self.future.clear()
        self.revision = self.saved_revision = uuid.uuid4().hex
        self.set_mode('')
        self.canvas.zoom = None
        self.canvas.set_image(image)
        self.show_status()
        self.title.setToolTip(str(path) if path else 'Clipboard image')
        self.update_buttons()

    def move(self, delta):
        slot = self.index + delta
        while 0 <= slot < len(self.images):
            path = self.images[slot]
            try:
                image, _size = read_photo(path)
            except (OSError, ValueError):
                slot += delta
                continue
            if not self.confirm_leave():
                return False
            self.index = slot
            self.display(path, image)
            return True
        self.status.setText('No more readable images in this direction.')
        return False

    def toggle_slideshow(self, enabled):
        if not enabled or self.dirty or not 0 <= self.index < len(self.images) - 1:
            self.stop_slideshow()
            return
        if self.edit_toggle.isChecked():
            self.edit_toggle.setChecked(False)
            self.toggle_edit(False)
        self.slideshow.start()
        self.update_slideshow_button()

    def stop_slideshow(self):
        self.slideshow.stop()
        self.update_slideshow_button()

    def advance_slideshow(self):
        if not self.slideshow.isActive():
            return
        if self.dirty or not self.move(1) or self.index == len(self.images) - 1:
            self.stop_slideshow()

    def update_slideshow_button(self):
        playing = self.slideshow.isActive()
        label = 'Stop slideshow' if playing else 'Play slideshow'
        glyph = 'media-playback-stop' if playing else 'media-playback-start'
        icon = symbolic_icon(glyph, self.theme['accent_ink'])
        self.slideshow_button.setProperty('mellipiSymbolicIcon', glyph)
        self.slideshow_button.setIcon(icon)
        self.slideshow_button.setText(label if icon.isNull() else '')
        self.slideshow_button.setToolTip(label)
        self.slideshow_button.setAccessibleName(label)
        self.slideshow_button.setChecked(playing)
        self.slideshow_button.setEnabled(playing or (not self.dirty and 0 <= self.index < len(self.images) - 1))

    def escape(self):
        if self.slideshow.isActive():
            self.stop_slideshow()
        else:
            self.set_mode('')

    def show_status(self):
        name = self.path.name if self.path else 'Clipboard image'
        image = self.canvas.image
        suffix = ' · Unsaved edits' if self.dirty else ''
        if self.index >= 0:
            suffix += f' · {self.index + 1} / {len(self.images)}'
        self.status.setText(f'{image.width()} × {image.height()}{suffix}')
        self.title.setText(name + (' •' if self.dirty else ''))
        self.setWindowTitle(f'{name} — Photos')

    @property
    def dirty(self):
        return self.revision != self.saved_revision

    def toggle_edit(self, enabled):
        if enabled:
            self.stop_slideshow()
        self.edit_bar.setVisible(enabled)
        if not enabled:
            self.set_mode('')

    def set_canvas_accent(self):
        self.canvas.label.accent = QColor(self.theme['accent_ink'])
        self.canvas.label.update()

    def set_pen_color(self, _index):
        self.canvas.label.pen = QColor(self.pen_color.currentData())

    def set_mode(self, mode):
        surface = self.canvas.label
        if surface.mode == mode:
            mode = ''
        surface.mode = mode
        surface.clear_gesture()
        surface.setCursor(Qt.CursorShape.CrossCursor if mode else Qt.CursorShape.ArrowCursor)
        self.crop_btn.setChecked(mode == 'crop')
        self.pen_btn.setChecked(mode == 'pen')
        self.pen_color.setVisible(mode == 'pen')
        self.apply_btn.setVisible(mode == 'crop')
        if mode:
            self.status.setText('Drag across the image, then choose Apply crop.' if mode == 'crop'
                                else 'Draw on the image. Ctrl+Z removes the last stroke.')
        elif not self.canvas.image.isNull():
            self.show_status()

    def commit(self, image):
        self.stop_slideshow()
        if image.isNull():
            self.status.setText('Could not allocate the edited image.')
            return False
        self.future.clear()
        self.remember(self.history)
        self.revision = uuid.uuid4().hex
        self.canvas.set_image(image)
        self.show_status()
        self.update_buttons()
        return True

    def remember(self, stack):
        stack.append((self.canvas.image, self.revision))
        # Undo and redo share one budget; in either direction preserve nearby
        # states first. The displayed image does not count toward the budget.
        other = self.future if stack is self.history else self.history
        while (len(stack) + len(other) > MAX_HISTORY_STEPS or
               sum(image.sizeInBytes() for states in (stack, other) for image, _ in states)
               > MAX_HISTORY_BYTES):
            (other or stack).pop(0)

    def step_history(self, source, destination):
        if not source:
            return
        self.set_mode('')
        image, revision = source.pop()
        self.remember(destination)
        self.revision = revision
        self.canvas.set_image(image)
        self.show_status()
        self.update_buttons()

    def undo(self):
        self.step_history(self.history, self.future)

    def redo(self):
        self.step_history(self.future, self.history)

    def rotate(self):
        if not self.canvas.image.isNull():
            self.set_mode('')
            self.commit(self.canvas.image.transformed(QTransform().rotate(90)))

    def crop(self):
        rect = self.canvas.label.crop_rect()
        if not rect.isEmpty() and rect.size() != self.canvas.image.size():
            cropped = self.canvas.image.copy(rect)
            self.set_mode('')
            self.canvas.zoom = None
            self.commit(cropped)

    def ink(self, path):
        image = self.canvas.image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
        painter = QPainter(image)
        draw_ink(painter, path, self.canvas.label.pen, image.size())
        painter.end()
        self.commit(image)

    def resize_photo(self, width, height):
        if not 1 <= width <= MAX_IMAGE_PIXELS or not 1 <= height <= MAX_IMAGE_PIXELS or width * height > MAX_IMAGE_PIXELS:
            raise ValueError('Choose dimensions that total no more than 16 million pixels.')
        source = self.canvas.image
        if (width, height) == (source.width(), source.height()):
            return False
        self.set_mode('')
        self.canvas.zoom = None
        return self.commit(source.scaled(width, height, Qt.AspectRatioMode.IgnoreAspectRatio,
                                         Qt.TransformationMode.SmoothTransformation))

    def resize_dialog(self):
        source = self.canvas.image
        if source.isNull():
            return
        dialog = style_dialog(QDialog(self), self)
        dialog.setWindowTitle('Resize image')
        form = QFormLayout(dialog)
        width, height = QSpinBox(), QSpinBox()
        for key, field, value in (('Width', width, source.width()), ('Height', height, source.height())):
            field.setRange(1, MAX_IMAGE_PIXELS)
            field.setValue(value)
            field.setSuffix(' px')
            form.addRow(key, field)
        aspect = QCheckBox('Keep aspect ratio', checked=True)
        form.addRow(aspect)

        def sync(value, other, ratio):
            if aspect.isChecked():
                was_blocked = other.blockSignals(True)
                other.setValue(round(value * ratio))
                other.blockSignals(was_blocked)

        width.valueChanged.connect(lambda value: sync(value, height, source.height()/source.width()))
        height.valueChanged.connect(lambda value: sync(value, width, source.width()/source.height()))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        width.setFocus()
        width.selectAll()
        try:
            size = (width.value(), height.value()) if exec_owned_dialog(dialog) == QDialog.DialogCode.Accepted else None
        finally:
            dialog.deleteLater()
        if size is not None:
            try:
                self.resize_photo(*size)
            except ValueError as error:
                themed_prompt(self, 'Could not resize', str(error), 'OK')

    def paste(self):
        self.stop_slideshow()
        mime = QApplication.clipboard().mimeData()
        if not mime or not mime.hasImage():
            self.status.setText('The clipboard has no image.')
            return
        image = QApplication.clipboard().image()
        if image.isNull() or image.width() * image.height() > MAX_IMAGE_PIXELS:
            self.status.setText('The clipboard image is not readable or exceeds 16 million pixels.')
            return
        if self.confirm_leave():
            image.setDevicePixelRatio(1)
            self.images = []
            self.index = -1
            self.display(None, image)
            # A pasted image has no file behind it and must be saved explicitly.
            self.saved_revision = None
            self.show_status()
            self.edit_toggle.setChecked(True)
            self.toggle_edit(True)

    def save_as(self):
        image = self.canvas.image
        if image.isNull():
            return False
        start = self.path.with_name(f'{self.path.stem}-edited.png') if self.path else Path.home() / 'Screenshot-edited.png'
        selected, _ = FileChooser.getSaveFileName(self, 'Save an edited copy', str(start), 'PNG image (*.png)')
        if not selected:
            return False
        path = Path(selected)
        if path.suffix.lower() != '.png':
            path = Path(str(path) + '.png')
            # The dialog may only have confirmed the unextended name.
            if path.exists() and not themed_prompt(self, 'Replace existing copy?', path.name, 'Replace', 'Cancel'):
                return False
        try:
            if self.path is not None and path.resolve() == self.path.resolve():
                raise ValueError('Choose a different file name to keep your original.')
            save_copy(path, image)
        except (OSError, ValueError) as error:
            themed_prompt(self, 'Could not save image', str(error), 'OK')
            return False
        self.saved_revision = self.revision
        self.show_status()
        self.status.setText(f'Saved copy to {path}')
        return True

    def confirm_leave(self):
        if not self.dirty:
            return True
        result = themed_choice(self, 'Unsaved image edits',
                               'Save your edited image before leaving?',
                               'Save copy…', 'Cancel', 'Discard')
        return result == 2 or result == QDialog.DialogCode.Accepted and self.save_as()

    def closeEvent(self, event):
        self.stop_slideshow()
        if self.confirm_leave():
            event.accept()
        else:
            event.ignore()

    def hideEvent(self, event):
        self.stop_slideshow()
        super().hideEvent(event)

    def copy(self):
        if not self.canvas.image.isNull():
            QApplication.clipboard().setImage(self.canvas.image)

    def update_buttons(self):
        self.previous.setEnabled(self.index > 0)
        self.next.setEnabled(0 <= self.index < len(self.images) - 1)
        self.update_slideshow_button()
        for button in [*self.tools, self.edit_toggle, self.save_btn]:
            button.setEnabled(not self.canvas.image.isNull())
        self.undo_btn.setEnabled(bool(self.history))
        self.redo_btn.setEnabled(bool(self.future))

    def dragEnterEvent(self, event):
        urls = event.mimeData().urls()
        if len(urls) == 1 and urls[0].isLocalFile():
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if len(urls) == 1 and self.open_path(urls[0].toString()):
            event.acceptProposedAction()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path', nargs='?')
    args = parser.parse_args()
    app = QApplication([sys.argv[0]])
    app.setApplicationName('Mellipi Photos')
    app.setDesktopFileName('mellipi-photos')
    window = PhotosWindow(args.path)
    window.show()
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
