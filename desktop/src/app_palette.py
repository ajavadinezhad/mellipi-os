"""Shared palette for Mellipi windows and contrast variants."""

from functools import lru_cache


def blend_color(base, overlay, weight):
    return '#' + ''.join(
        f'{round(int(base[i:i+2], 16) * (1 - weight) + int(overlay[i:i+2],16) * weight):02x}'
        for i in (1, 3, 5)
    )


def colors(preferences):
    appearance = preferences.appearance()
    palette = colors_from_appearance(appearance)
    backgrounds = [palette[key] for key in (
        'background', 'surface', 'raised', 'hover', 'selected_surface',
    )]
    endpoint = '#000000' if appearance['mode'] == 'light' else '#ffffff'
    accent = palette['accent']
    frame = appearance.get('themeFrame', {})
    palette['chrome'] = frame.get('header', blend_color(palette['background'], palette['raised'], .68))
    palette['frame_trim'] = frame.get('trim', palette['border'])
    palette['chrome_edge'] = (adjust_contrast(palette['frame_trim'], [palette['chrome'], palette['background']], 3, endpoint)
                              if appearance['highContrast'] else
                              blend_color(palette['chrome'], palette['frame_trim'], .58) if frame else palette['chrome'])
    palette['chrome_text'] = adjust_contrast(palette['text'], [palette['chrome']], 4.5, endpoint)
    backgrounds.append(palette['chrome'])
    palette['accent_ink'] = adjust_contrast(accent, backgrounds, 4.5, endpoint)
    palette['focus'] = adjust_contrast(palette.get('focus', accent), backgrounds, 3, endpoint)
    palette['focus_text'] = foreground_on(palette['focus'])
    palette['control_border'] = adjust_contrast(palette['border'], backgrounds[:4], 3, endpoint)
    palette['muted'] = adjust_contrast(palette['muted'], backgrounds, 4.5, endpoint)
    palette['faint'] = adjust_contrast(palette['faint'], [palette['surface']], 4.5, endpoint)
    return palette


def colors_from_appearance(appearance):
    light = appearance['mode'] == 'light'
    black = not light and appearance['darkLevel'] == 'black'
    accent = appearance['accent']
    defaults = (
        ('#eef2f6', '#ffffff', '#e1e8ee', '#d7e2e8', '#bac8d3', '#15222d', '#526473', '#647582')
        if light else
        ('#07090c', '#101419', '#1a2027', '#242d37', '#38424d', '#e1e8ed', '#adb7c4', '#8b97a7')
        if black else
        ('#10191f', '#172329', '#203037', '#2b3c43', '#3d5058', '#e1e8ed', '#a2b0bb', '#788b9b')
    )
    keys = ('background', 'surface', 'raised', 'hover', 'border', 'text', 'muted', 'faint')
    palette = dict(zip(keys, defaults))
    for key, opacity in zip(keys[:5], (.055, .012 if black else .06,
                                      .018 if black else .075, .03 if black else .12,
                                      .05 if black else .2)):
        if key == 'background' and black:
            continue
        base = [int(palette[key][i:i+2], 16) for i in (1, 3, 5)]
        tint = [int(accent[i:i+2], 16) for i in (1, 3, 5)]
        palette[key] = '#' + ''.join(f'{round(a * (1 - opacity) + b * opacity):02x}'
                                     for a, b in zip(base, tint))
    palette.update(appearance['themePalette'])
    def mix(base, overlay, opacity):
        return '#' + ''.join(
            f'{round(int(base[i:i+2],16)*(1-opacity)+int(overlay[i:i+2],16)*opacity):02x}'
            for i in (1, 3, 5)
        )
    # Match the shell's divider treatment on both flat and raised surfaces.
    palette['separator'] = palette['border'] if appearance['highContrast'] else mix(
        palette['surface'], palette['border'], .75)
    palette['selected_surface'] = mix(
        palette['surface'], accent, .16)
    return dict(palette, accent=accent, accent_text=foreground_on(accent))



def luminance(color):
    channels = [int(color[i:i+2], 16) / 255 for i in (1, 3, 5)]
    linear = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in channels]
    return sum(v * weight for v, weight in zip(linear, (.2126, .7152, .0722)))


def contrast_ratio(a, b):
    lo, hi = sorted((luminance(a), luminance(b)))
    return (hi + .05) / (lo + .05)


def foreground_on(color):
    return '#000000' if luminance(color) > .179 else '#ffffff'


def adjust_contrast(color, backgrounds, target, endpoint):
    def meets(candidate):
        return all(contrast_ratio(candidate, background) >= target for background in backgrounds)

    if meets(color):
        return color
    # An imported preset may specify a light surface with a dark-mode flag,
    # or vice versa. Derive the fallback from the rendered backgrounds.
    if not meets(endpoint):
        opposite = '#ffffff' if endpoint == '#000000' else '#000000'
        if min(contrast_ratio(opposite, surface) for surface in backgrounds) > min(
                contrast_ratio(endpoint, surface) for surface in backgrounds):
            endpoint = opposite
    channels = [int(color[i:i+2], 16) for i in (1, 3, 5)]
    extreme = int(endpoint[1:3], 16)

    def blend(amount):
        return '#' + ''.join(
            f'{round((channel * (256 - amount) + extreme * amount) / 256):02x}'
            for channel in channels
        )

    low, high = 0, 256
    while high - low > 1:
        amount = (low + high) // 2
        if meets(blend(amount)):
            high = amount
        else:
            low = amount
    return endpoint if high == 256 else blend(high)


def contrast_palette(appearance, palette):
    return dict(_contrast_palette(appearance['mode'], appearance['darkLevel'],
                                  appearance['accent'], tuple(sorted(palette.items()))))


@lru_cache(maxsize=32)
def _contrast_palette(mode, dark_level, accent, entries):
    palette = colors_from_appearance(dict(mode=mode, darkLevel=dark_level, accent=accent,
                                          themePalette=dict(entries), highContrast=False))
    backgrounds = [palette[key] for key in ('background', 'surface', 'raised', 'hover')]
    endpoint = '#000000' if mode == 'light' else '#ffffff'

    for key, target in (('text', 9), ('muted', 7), ('faint', 5.5), ('border', 3)):
        palette[key] = adjust_contrast(palette[key], backgrounds, target, endpoint)
    palette['focus'] = adjust_contrast(accent, backgrounds, 3, endpoint)
    return tuple((key, palette[key]) for key in (
        'background', 'surface', 'raised', 'hover', 'text', 'muted', 'faint', 'border', 'focus',
    ))


# Match the native Settings window at each density.
HEADER_HEIGHTS = {'extra': 30, 'compact': 36, 'comfortable': 42}


# Keep each app recognizable by its glyph; the active theme supplies the ink.
APP_IDENTITIES = {
    'Mellipi Files': 'folder',
    'Mellipi Terminal': 'terminal',
    'Mellipi Browser': 'browser',
    'Private Browser': 'browser',
    'Calendar': 'calendar',
    'Calculator': 'calculator',
    'Text Editor': 'editor',
    'Photos': 'photos',
    'PDF Viewer': 'pdf',
    'Media': 'media',
    'Disks': 'disks',
    'Mellipi Software': 'software',
    'System Monitor': 'usage',
    'Sound Recorder': 'microphone',
}


@lru_cache(maxsize=96)
def identity_appearance(title, surface, color):
    glyph = APP_IDENTITIES.get(title, 'fold')
    mix = lambda weight: '#' + ''.join(
        f'{round((1-weight)*int(surface[i:i+2],16)+weight*int(color[i:i+2],16)):02x}'
        for i in (1, 3, 5))
    badge = mix(.18)
    endpoint = '#000000' if luminance(badge) >= .18 else '#ffffff'
    ink = adjust_contrast(color, [badge], 4.5, endpoint)
    return glyph, ink, badge
