"""Shared palette for Mellipi windows and contrast variants."""

from functools import lru_cache


def colors(preferences):
    appearance = preferences.appearance()
    palette = colors_from_appearance(appearance)
    backgrounds = [palette[key] for key in (
        'background', 'surface', 'raised', 'hover', 'selected_surface',
    )]
    endpoint = '#000000' if appearance['mode'] == 'light' else '#ffffff'
    accent = palette['accent']
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


# App color gives the title glyph an identity; selection keeps the desktop accent.
APP_IDENTITIES = {
    'Mellipi Files': ('folder', '#c37a27'),
    'Mellipi Terminal': ('terminal', '#27866c'),
    'Mellipi Browser': ('browser', '#477add'),
    'Private Browser': ('browser', '#9864cf'),
    'Calendar': ('calendar', '#9864cf'),
    'Calculator': ('calculator', '#5e75cb'),
    'Text Editor': ('editor', '#477add'),
    'Photos': ('photos', '#c1648c'),
    'PDF Viewer': ('pdf', '#c76057'),
    'Media': ('media', '#9864cf'),
    'Disks': ('disks', '#278a94'),
    'Mellipi Software': ('software', '#27866c'),
    'System Monitor': ('usage', '#278a94'),
    'Sound Recorder': ('microphone', '#c76057'),
}


@lru_cache(maxsize=96)
def identity_appearance(title, surface):
    glyph, color = APP_IDENTITIES.get(title, ('fold', '#6e80bb'))
    mix = lambda weight: '#' + ''.join(
        f'{round((1-weight)*int(surface[i:i+2],16)+weight*int(color[i:i+2],16)):02x}'
        for i in (1, 3, 5))
    badge = mix(.18)
    endpoint = '#000000' if luminance(badge) >= .18 else '#ffffff'
    ink = adjust_contrast(color, [badge], 4.5, endpoint)
    return glyph, ink, badge
