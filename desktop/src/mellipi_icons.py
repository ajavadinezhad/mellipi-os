"""Original Mellipi vector icons. One drawing per symbol, no toolkit dependency."""
import re

# 24-unit grid, rounded strokes and clipped corners. Open paths deliberately
# leave breathing room next to the small diagonal cuts.
PATHS = {
    'zoom-in': 'M15 10a5 5 0 1 0-10 0 5 5 0 0 0 10 0zm-1 4 6 6M8 10h4m-2-2v4',
    'zoom-out': 'M15 10a5 5 0 1 0-10 0 5 5 0 0 0 10 0zm-1 4 6 6M8 10h4',
    'zoom-fit-best': 'M8 4H4v4m12-4h4v4M4 16v4h4m8 0h4v-4M8 8h8v8H8z',
    'object-rotate-right': 'M19 4v5h-5m5 0a7 7 0 1 0 0 6M9 10h5v5H9z',
    'image-crop': 'M7 3v14h14M3 7h14v14',
    'resize': 'M4 4h6m4 0h6v6m0 4v6h-6m-4 0H4v-6m0-4V4m5 11 6-6',
    'save-as': 'M4 4h13l3 3v4M4 4v16h8m-4-16v5h8V4m-8 16v-7h4m2 4 4-4 2 2-4 4h-2z',
    'print': 'M7 8V4h10v4M7 17H4V8h14l2 2v7h-3m-10-3h10v6H7zm10-3h.1',
    'list': 'M4 6h.1m3.9 0h12M4 12h.1m3.9 0h12M4 18h.1m3.9 0h12',
    'erase': 'M6 18l-3-3 9-10 7 6-6 7zm1-7 7 6m-1 1h8',
    'information': 'M21 12a9 9 0 1 0-18 0 9 9 0 0 0 18 0zM12 10v6m0-9h.1',
    'calendar-today': 'M4 6h14l2 2v12H4zm0 4h16M8 4v4m8-4v4m-6 6h4v3h-4z',
    'bell-off': 'M5 17h14m-14 0 2-3V9a5 5 0 0 1 1-3m4-2a6 6 0 0 1 6 6v3m-8 7h4M3 3l18 18',
    'selection': 'M9 4H4v5m11-5h5v5M4 15v5h5m6 0h5v-5M9 9h6v6H9z',
    'window': 'M3 5h15l3 3v11H3zm0 5h18M6 7.5h.1',
    'bookmark': 'M6 3h10l2 2v16l-6-4-6 4z',
    'history': 'M4 5v5h5M4 10a8 8 0 1 1 1 7m7-10v5l3 2',
    'undo': 'M9 5l-5 5 5 5m-5-5h10a5 5 0 0 1 0 10h-3',
    'redo': 'M15 5l5 5-5 5m5-5H10a5 5 0 0 0 0 10h3',
    'archive': 'M4 4h13l3 3v13H4zm0 4h16m-10 4h4v4h-4z',
    'save': 'M4 4h13l3 3v13H4zM8 4v5h8V4m-8 16v-7h8v7',
    'replace': 'M4 8h15l-3-3m3 3-3 3m4 5H5l3-3m-3 3 3 3',
    'editor': 'M5 3h10l4 4v14H5zM15 3v5h4M8 12h8m-8 4h5',
    'calculator': 'M5 3h11l3 3v15H5zM8 7h8m-8 5h.1m4 0h.1m4 0h.1m-8 4h.1m4 0h.1m4 0h.1',
    'calendar': 'M4 6h14l2 2v12H4zm0 4h16M8 4v4m8-4v4m-8 6h.1m4 0h.1m4 0h.1m-8 3h.1m4 0h.1',
    'browser': 'M21 12a9 9 0 1 0-18 0 9 9 0 0 0 18 0zM3 12h18M12 3c5 5 5 13 0 18-5-5-5-13 0-18z',
    'fold': 'M3 9l6-6h7l5 5v7l-6 6H8l-5-5V9zm4 7V10l5 4 5-4v6',
    'folder': 'M3 8V5h6l3 3h7l2 2v9H3V8zm0 3h18',
    'terminal': 'M3 5h15l3 3v11H3z M7 9l4 3-4 3m7 0h3',
    'settings': 'M4 7h5m4 0h7M4 12h10m4 0h2M4 17h3m4 0h9M9 5h4v4H9zm5 5h4v4h-4zm-7 5h4v4H7z',
    'software': 'M4 8h14l2 2v10H4zM8 8V6a4 4 0 0 1 8 0v2m-7 6 2 2 4-4',
    'photos': 'M3 5h15l3 3v11H3z M4 17l5-5 4 4 3-3 4 4 M15 9h.1',
    'pdf': 'M6 3h8l4 4v14H6z M14 3v5h4 M9 12h6m-6 4h6',
    'media': 'M3 5h15l3 3v11H3z M10 9l5 3-5 3z',
    'disks': 'M5 5h12l3 3v11H4v-8z M5 14h14m-4 3h2',
    'home': 'M3 12l9-8 9 8m-16-1v9h5v-5h4v5h5v-9',
    'trash': 'M5 7h14m-12 0 1 13h8l1-13M9 7V4h6v3m-4 4v5m2-5v5',
    'camera': 'M3 8h4l2-3h6l2 3h2l2 2v9H3z M15 13a3 3 0 1 0-6 0 3 3 0 0 0 6 0z',
    'bell': 'M4 17l2-3V9a6 6 0 0 1 12 0v5l2 3H4zm6 3h4',
    'wifi': 'M3 8a14 14 0 0 1 18 0M6 12a9 9 0 0 1 12 0m-9 4a4 4 0 0 1 6 0m-3 3h.1',
    'battery': 'M3 7h14l2 2v8H3zm18 3v4M7 10v4m4-4v4',
    'user': 'M15 8a3 3 0 1 0-6 0 3 3 0 0 0 6 0zM5 20v-2a7 7 0 0 1 14 0v2',
    'microphone': 'M9 6a3 3 0 0 1 6 0v5a3 3 0 0 1-6 0zm-3 5a6 6 0 0 0 12 0m-6 6v4m-3 0h6',
    'usage': 'M4 19v-6h4v6zm6 0V5h4v14zm6 0V9h4v10z',
    'volume': 'M3 9h4l5-4v14l-5-4H3zM15 9a4 4 0 0 1 0 6m2-9a8 8 0 0 1 0 12',
    'mute': 'M3 9h4l5-4v14l-5-4H3zM16 10l5 5m0-5-5 5',
    'microphone': 'M9 6a3 3 0 0 1 6 0v5a3 3 0 0 1-6 0zM6 11a6 6 0 0 0 12 0m-6 6v4m-3 0h6',
    'microphone-mute': 'M9 7V6a3 3 0 0 1 6 0v5m-9 0a6 6 0 0 0 10 4m-4 2v4m-3 0h6M4 4l16 16',
    'play': 'M8 5l11 7-11 7z',
    'pause': 'M7 5h3v14H7zm7 0h3v14h-3z',
    'stop': 'M6 6h12v12H6z',
    'previous': 'M5 5v14m13-14L8 12l10 7z',
    'next': 'M19 5v14M6 5l10 7-10 7z',
    'chevron-up': 'M5 15l7-7 7 7', 'chevron-down': 'M5 9l7 7 7-7',
    'chevron-left': 'M15 5l-7 7 7 7', 'chevron-right': 'M9 5l7 7-7 7',
    'pin': 'M8 4h8l-1 5v3l3 3H6l3-3V9zm4 11v6',
    'pinned': 'M8 4h8l-1 5v3l3 3H6l3-3V9zm4 11v6M10 7h4m-4 4h4',
    'layouts': 'M3 4h15l3 3v13H3zM11 4v16m0-8h10',
    'apps': 'M4 4h6v6H4zm10 0h4l2 2v4h-6zM4 14h6v6H4zm10 0h6v6h-6z',
    'refresh': 'M19 6v5h-5m5 0a7 7 0 1 0-1 6',
    'updates': 'M12 3v12m-4-4 4 4 4-4M4 15v5h16v-5',
    'check': 'M5 12l4 4L19 6',
    'more': 'M5 12h.1m6.9 0h.1m6.9 0h.1',
    'close': 'M6 6l12 12m0-12L6 18',
    'lock': 'M5 10h12l2 2v8H5zm3 0V7a4 4 0 0 1 8 0v3m-4 4v3',
    'logout': 'M11 4H5v16h6m-1-8h10m-4-4 4 4-4 4',
    'shutdown': 'M12 3v8m-4-4a7 7 0 1 0 8 0',
    'sleep': 'M19 15a8 8 0 0 1-10-10 8 8 0 1 0 10 10z',
    'switch-user': 'M4 18v-2a5 5 0 0 1 9-3m-2-6a3 3 0 1 0-6 0 3 3 0 0 0 6 0zm3 9h7m-3-3 3 3-3 3',
    'search': 'M15 10a5 5 0 1 0-10 0 5 5 0 0 0 10 0zm-1 4 6 6',
    'edit': 'M5 15 15 5l4 4L9 19H5zm8-8 4 4',
    'plus': 'M12 5v14M5 12h14',
    'copy': 'M8 8h9l3 3v9H8zM5 16H4V4h11v1',
    'paste': 'M8 5H5v15h14V5h-3m-8-2h8v5H8z',
    'cut': 'M7 17a2 2 0 1 0-4 0 2 2 0 0 0 4 0zm0-10a2 2 0 1 0-4 0 2 2 0 0 0 4 0zm0 2 13 10M7 15 20 5',
    'bluetooth': 'M12 3v18l5-5L6 7m6-4 5 5L6 17',
    'keyboard': 'M3 6h15l3 3v9H3zm4 4h.1m4 0h.1m4 0h.1m3 0h.1M7 14h10',
    'display': 'M3 4h15l3 3v10H3zm9 13v4m-4 0h8',
}
APPS = dict(zip(
    ('mellipi-files','mellipi-terminal','mellipi-software','mellipi-photos','mellipi-pdf',
     'mellipi-media','mellipi-disks','mellipi-settings','mellipi-desktop'),
    ('folder','terminal','software','photos','pdf','media','disks','settings','fold')))
APPS.update({f'mellipi-{name}': name for name in ('editor','calculator','calendar','browser')})
APPS.update({'mellipi-monitor': 'usage', 'mellipi-recorder': 'microphone'})
ALIASES = {
    **APPS, 'orbit-settings':'settings','controls':'settings','restart':'refresh',
    'screenshot':'camera','notification':'bell','network':'wifi','network-wireless':'wifi',
    'user-home':'home','user-trash':'trash','drive-harddisk':'disks','drive-removable-media':'disks',
    'system-file-manager':'folder','folder-open':'folder','document-open':'folder',
    'folder-new':'folder','utilities-terminal':'terminal','system-software-install':'software',
    'preferences-system':'settings','preferences-desktop':'fold','image-x-generic':'photos',
    'x-office-document':'pdf','application-pdf':'pdf','video-x-generic':'media','multimedia-player':'media',
    'applications-multimedia':'media','go-previous':'chevron-left','go-next':'chevron-right',
    'go-up':'chevron-up','go-down':'chevron-down','document-edit':'edit','edit-find':'search',
    'open-menu':'more','view-refresh':'refresh','window-close':'close','tab-new':'plus',
    'edit-copy':'copy','edit-paste':'paste','edit-cut':'cut','edit-delete':'trash',
    'audio-volume-high':'volume','audio-volume-muted':'mute','media-playback-start':'play',
    'media-playback-pause':'pause','media-playback-stop':'stop','media-skip-backward':'previous',
    'media-skip-forward':'next','input-keyboard':'keyboard','video-display':'display',
    'edit-undo':'undo','edit-redo':'redo','package-x-generic':'archive',
    'dialog-information':'information','bookmark-new':'bookmark','notifications-disabled':'bell-off',
    'view-restore':'resize','document-save-as':'save-as','document-print':'print',
    'view-list':'list','edit-clear':'erase',
    'document-save':'save','edit-find-replace':'replace',
    'system-log-out':'logout','system-shutdown':'shutdown','system-lock-screen':'lock',
}


def svg(name, ink='#303745', badge=False, *, size=24):
    name = name.removesuffix('-symbolic')
    path = PATHS.get(ALIASES.get(name, name))
    if path is None or type(size) is not int or not 8 <= size <= 128 or not re.fullmatch(r'#[0-9a-fA-F]{6}', ink):
        return None
    # Use vector faces instead of blur or baked bitmaps. Controls keep an
    # opaque accent stroke; only their secondary relief changes by theme.
    if badge:
        channels = tuple(int(ink[i:i+2], 16) for i in (1, 3, 5))
        def tone(base, weight):
            return '#' + ''.join(f'{round(v * (1-weight) + c * weight):02x}'
                                 for v, c in zip(base, channels))
        face_top = tone((63, 76, 94), .24)
        face_mid = tone((35, 45, 63), .17)
        highlight = tone((184, 197, 217), .35)
        ink = tone((255, 255, 255), .28)
        background = (
            '<defs><linearGradient id="face" x1="0%" y1="0%" x2="95%" y2="100%">'
            f'<stop offset="0" stop-color="{face_top}"/><stop offset=".55" stop-color="{face_mid}"/>'
            '<stop offset="1" stop-color="#182438"/></linearGradient></defs>'
            '<path d="M2 1h16l5 5v16l-2 2H1V3z" fill="#0c1420"/>'
            '<path d="M2 0h16l5 5v15l-2 2H1V2z" fill="url(#face)"/>'
            f'<path d="M2 1h15l5 5M2 1v15" fill="none" stroke="{highlight}" stroke-opacity=".44"/>'
            '<path d="M3 21h17l2-2V8" fill="none" stroke="#0b1626" stroke-opacity=".66"/>'
        )
        relief = f'<path d="{path}" transform="translate(0 .8)" stroke="#081221" stroke-opacity=".72"/>'
    else:
        background = ''
        relief = f'<path d="{path}" transform="translate(.3 .65)" stroke="{ink}" stroke-opacity=".20" stroke-width="2.1"/>'
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 24 24">{background}'
            f'<g fill="none" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">'
            f'{relief}<path d="{path}" stroke="{ink}"/></g></svg>').encode()
