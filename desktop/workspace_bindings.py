"""Fixed relative-workspace shortcuts, shared by login and live updates."""
BINDINGS={'Ctrl+Mod1+Left':-1,'Ctrl+Mod1+Up':-1,'Ctrl+Mod1+Right':1,'Ctrl+Mod1+Down':1}
def config_lines():
    return [f'bindsym --no-warn --no-repeat {key} nop orbit-workspace-{"next" if step>0 else "previous"}' for key,step in BINDINGS.items()]
