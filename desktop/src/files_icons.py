"""Phosphor glyphs for Files, painted with the active theme."""
from functools import lru_cache
from pathlib import Path

from PyQt6.QtGui import QColor, QIcon, QPixmap
from project_paths import PROJECT_ROOT

ASSETS = PROJECT_ROOT / 'icons/phosphor'
ACTIONS = dict(zip(
    ('go-previous', 'go-next', 'go-up', 'document-edit', 'edit-find', 'open-menu',
     'more', 'folder-new', 'edit-copy', 'edit-cut', 'edit-paste', 'user-trash',
     'view-reveal', 'document-open', 'package-x-generic', 'folder-download', 'bookmark'),
    ('arrow-left', 'arrow-right', 'arrow-up', 'pencil-simple', 'magnifying-glass',
     'dots-three', 'dots-three', 'folder-plus', 'copy', 'scissors', 'clipboard',
     'trash', 'eye', 'folder-open', 'archive', 'tray-arrow-down', 'folder-plus')))
PLACES = {
    'user-home': ('house', '#81a9ff'), 'user-desktop': ('desktop', '#a395ff'),
    'folder-documents': ('file-text', '#79b7ff'), 'folder-download': ('download-simple', '#71c9a4'),
    'folder-pictures': ('images', '#f5a7bf'), 'drive-harddisk': ('hard-drives', '#9baac3'),
    'drive-removable-media': ('hard-drives', '#9baac3'), 'user-trash': ('trash', '#eeb48d'),
    'folder': ('folder', '#edb35f'), 'bookmark': ('folder', '#a395ff'),
}
GROUPS = (
    ('file-image', 'png jpg jpeg gif svg webp heic avif bmp tiff ico'),
    ('file-audio', 'mp3 wav flac ogg m4a opus aac'),
    ('file-video', 'mp4 mkv webm mov avi mpeg'),
    ('file-zip', 'zip tar gz xz bz2 zst 7z rar deb'),
    ('file-code', 'py js ts html css sh rs c cpp json yaml yml toml'),
    ('file-pdf', 'pdf'),
    ('file-text', 'txt md log odt doc docx rtf csv'),
)
FILE_TYPES = {suffix: glyph for glyph, suffixes in GROUPS for suffix in suffixes.split()}


@lru_cache(maxsize=64)
def asset(style, name):
    try:
        return (ASSETS / style / (name + '.svg')).read_text()
    except OSError:
        return ''


@lru_cache(maxsize=192)
def icon(style, name, ink, tint='', selected='', *, semantic_tint=True):
    original = asset(style, name)
    result = QIcon()
    if not original:
        return result
    for mode, fg, fill in ((QIcon.Mode.Normal, ink, tint), (QIcon.Mode.Selected, selected, selected)):
        if not fg:
            continue
        # Mix the semantic color into the outline too; a tiny shaded area
        # alone is hard to distinguish at file-list size.
        if tint and semantic_tint and mode == QIcon.Mode.Normal:
            base, accent = QColor(fg), QColor(tint)
            fg = QColor(*(round(.55 * a + .45 * b) for a,b in zip(
                base.getRgb()[:3], accent.getRgb()[:3]))).name()
        svg = original.replace('currentColor', fg)
        if fill:
            svg = svg.replace('opacity="0.2"', f'fill="{fill}" opacity="{0.72 if semantic_tint else 0.34}"')
        for size in (16, 20, 24, 32, 48):
            scaled = svg.replace('<svg ', f'<svg width="{size}" height="{size}" ', 1)
            pixmap = QPixmap()
            if pixmap.loadFromData(scaled.encode(), 'SVG'):
                result.addPixmap(pixmap, mode)
    return result


def place_icon(name, palette):
    """Keep each location's glyph while letting the current theme supply its inks."""
    glyph, _ = PLACES[name]
    return icon('duotone', glyph, palette['accent_ink'], palette['accent'], semantic_tint=False)


def file_icon(filename, folder, ink, accent, selected):
    glyph = 'folder' if folder else FILE_TYPES.get(Path(filename).suffix[1:].casefold(), 'file')
    result = icon('duotone', glyph, ink, accent, selected, semantic_tint=False)
    return result if not result.isNull() else icon('duotone', 'file', ink, accent, selected, semantic_tint=False)
