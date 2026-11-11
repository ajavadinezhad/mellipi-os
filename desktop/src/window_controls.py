"""Shared 16-pixel window-control glyphs for the Qt and GTK title bars."""

PATHS = {
    'minimize': 'M4 8h8',
    'maximize': 'M4 4h8v8H4z',
    'restore': 'M6 4V3h7v7h-1 M3 6h7v7H3z',
    'close': 'M4 4l8 8M12 4l-8 8',
}


def glyph_svg(name, color):
    path = PATHS[name]
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16">'
        f'<path d="{path}" fill="none" stroke="{color}" stroke-width="1.5" '
        'stroke-linecap="round" stroke-linejoin="round"/></svg>'
    ).encode('ascii')
