"""Shared palette for standalone Mellipi applications."""


def colors(preferences):
    appearance = preferences.appearance()
    light = appearance['mode'] == 'light'
    black = not light and appearance['darkLevel'] == 'black'
    accent = appearance['accent']
    defaults = (
        ('#eef2f6', '#ffffff', '#e1e8ee', '#d7e2e8', '#bac8d3', '#15222d', '#526473')
        if light else
        ('#07090c', '#101419', '#1a2027', '#242d37', '#38424d', '#e1e8ed', '#adb7c4')
        if black else
        ('#10191f', '#172329', '#203037', '#2b3c43', '#3d5058', '#e1e8ed', '#a2b0bb')
    )
    keys = ('background', 'surface', 'raised', 'hover', 'border', 'text', 'muted')
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
    if appearance['highContrast']:
        palette.update(zip(keys, ('#ffffff', '#ffffff', '#e6e6e6', '#d0d0d0', '#000000', '#000000', '#222222')
                            if light else ('#000000', '#000000', '#161616', '#202020', '#ffffff', '#ffffff', '#eeeeee')))
    rgb = [int(accent[i:i+2], 16) / 255 for i in (1, 3, 5)]
    linear = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in rgb]
    luminance = sum(v * weight for v, weight in zip(linear, (.2126, .7152, .0722)))
    def mix(base, overlay, opacity):
        return '#' + ''.join(
            f'{round(int(base[i:i+2],16)*(1-opacity)+int(overlay[i:i+2],16)*opacity):02x}'
            for i in (1, 3, 5)
        )
    palette['separator'] = palette['border'] if appearance['highContrast'] else mix(
        palette['background'], palette['border'], .35)
    palette['selected_surface'] = palette['raised'] if appearance['highContrast'] else mix(
        palette['surface'], accent, .16)
    return dict(palette, accent=accent, accent_text='#000000' if luminance > .179 else '#ffffff')



# Match the native Settings window at each density.
HEADER_HEIGHTS = {'extra': 30, 'compact': 36, 'comfortable': 42}
