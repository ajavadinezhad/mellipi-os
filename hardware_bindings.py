"""Shared allowlist for compositor media keys and native routing."""
BINDINGS={
    'XF86AudioRaiseVolume':'volume-up','XF86AudioLowerVolume':'volume-down',
    'XF86AudioMute':'volume-mute','XF86AudioMicMute':'microphone-mute',
    'XF86AudioPlay':'media-play-pause','XF86AudioPause':'media-pause',
    'XF86AudioStop':'media-stop','XF86AudioNext':'media-next','XF86AudioPrev':'media-previous',
    'XF86MonBrightnessUp':'brightness-up','XF86MonBrightnessDown':'brightness-down',
}
ACTIONS=frozenset(BINDINGS.values())
def config_lines():
    return [f'bindsym --locked '+('' if action.endswith(('-up','-down')) else '--no-repeat ')+f'{key} nop orbit-hardware-{action}' for key,action in BINDINGS.items()]
