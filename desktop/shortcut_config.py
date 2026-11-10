"""Pure shortcut catalog, validation and Sway configuration generation."""
import re

LABELS={
    'launcher':'Open Abstract','quick':'Quick settings','screenshot':'Screenshot','terminal':'Terminal',
    'volume-up':'Volume up','volume-down':'Volume down','volume-mute':'Output mute',
    'microphone-mute':'Microphone mute','media-play-pause':'Play / pause','media-next':'Next track','media-previous':'Previous track',
    'brightness-up':'Brightness up','brightness-down':'Brightness down',
    'snap-left':'Snap window left','snap-right':'Snap window right','maximize':'Maximize window','restore':'Restore window size','next-layout':'Next keyboard layout',
}
DEFAULTS=dict.fromkeys(LABELS,'')
DEFAULTS.update(launcher='Ctrl+Mod1+space',quick='Ctrl+Mod1+s',screenshot='Print',terminal='Mod4+Return',
    **{'volume-up':'Mod4+F12','volume-down':'Mod4+F11','volume-mute':'Mod4+F10',
    'snap-left':'Mod4+Left','snap-right':'Mod4+Right','maximize':'Mod4+Up','restore':'Mod4+Down','next-layout':'Shift+Mod4+space'})
ACTIONS=frozenset(LABELS)
RESERVED={'Mod4+q','Mod4+f','Mod4+space','Ctrl+Mod1+q','Mod1+Tab','Mod1+Shift+Tab'}|{f'Mod4+{n}' for n in range(1,5)}|{f'Shift+Mod4+{n}' for n in range(1,5)}

from workspace_bindings import BINDINGS as WORKSPACE_BINDINGS
RESERVED.update(WORKSPACE_BINDINGS)

def chord(value):
    if not isinstance(value,str) or len(value)>64:raise ValueError('Invalid shortcut')
    if not value.strip():return ''
    parts=[p.strip() for p in value.strip().split('+')];key=parts[-1]
    aliases={'ctrl':'Ctrl','control':'Ctrl','alt':'Mod1','mod1':'Mod1','shift':'Shift','super':'Mod4','win':'Mod4','mod4':'Mod4'}
    modifiers=[aliases.get(p.lower(),p) for p in parts[:-1]]
    names={v.lower():v for v in ('Left','Right','Up','Down','Home','End','Page_Up','Page_Down','space','Return','Tab','Escape','Print')}
    key=names.get(key.lower(),key)
    if re.fullmatch(r'f\d+',key,re.I):key='F'+key[1:]
    if len(set(modifiers))!=len(modifiers) or any(p not in ('Ctrl','Mod1','Shift','Mod4') for p in modifiers):raise ValueError('Use Ctrl, Alt, Shift or Super modifiers')
    if not re.fullmatch(r'(?:[A-Za-z0-9]|F(?:[1-9]|[12][0-9]|3[0-5])|Left|Right|Up|Down|Home|End|Page_Up|Page_Down|space|Return|Tab|Escape|Print)',key):raise ValueError('Unsupported shortcut key')
    if len(key)==1:key=key.lower()
    if not modifiers and key!='Print':raise ValueError('Choose a shortcut with a modifier')
    return '+'.join([p for p in ('Ctrl','Mod1','Shift','Mod4') if p in modifiers]+[key])

def validate(bindings):
    if not isinstance(bindings,dict) or set(bindings)!=ACTIONS:raise ValueError('Invalid shortcut actions')
    result={action:chord(value) for action,value in bindings.items()};seen={}
    for action,value in result.items():
        if value in RESERVED:raise ValueError('This shortcut is reserved by the desktop')
        if value and value in seen:raise ValueError('This shortcut is already assigned to '+LABELS[seen[value]])
        if value:seen[value]=action
        if value=='Print' and action!='screenshot':raise ValueError('Print is reserved for screenshots')
    return result

def binding_line(action,value):
    repeat='' if action in ('volume-up','volume-down','brightness-up','brightness-down') else '--no-repeat '
    return f'bindsym --no-warn {repeat}{value} nop orbit-action-{action}'

def config_lines(bindings=None):
    values=validate(DEFAULTS if bindings is None else bindings)
    # Remove old built-in defaults too, so a changed binding really moves.
    unbind=[f'unbindsym {value}' for value in dict.fromkeys(v for v in DEFAULTS.values() if v and v not in values.values())]
    return unbind+[binding_line(action,value) for action,value in values.items() if value]

