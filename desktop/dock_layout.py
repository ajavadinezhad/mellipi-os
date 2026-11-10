"""Exact application dock geometry with a stable native layer surface."""

def layout(screen_width,compact,total_apps,fold=False):
    """Keep one 811×66 native surface across output, density and app-count changes.

    Only the bottom-aligned visible body and its input region change.
    """
    if type(screen_width) is not int or screen_width<48:raise ValueError('Invalid dock output width')
    if type(compact) is not bool:raise ValueError('Invalid dock density')
    if type(total_apps) is not int or total_apps<0:raise ValueError('Invalid dock application count')
    if type(fold) is not bool:raise ValueError('Invalid dock layout')
    available=min(screen_width-24,811) if fold else screen_width-24
    gap=min(4 if compact else 7,max(0,available-2))
    slot=min((88 if compact else 100) if fold else (38 if compact else 50),max(1,(available-gap)//2))
    padding=min(10,max(0,(available-2*slot-gap)//2))
    capacity=max(0,min(8 if fold else 12,(available-2*padding+gap)//(slot+gap)-2))
    visible=min(total_apps,capacity);overflow=total_apps-visible
    # The Applications button remains available even with no pinned/running apps.
    body_slots=1+visible+(1 if overflow else 0)
    body=2*padding+body_slots*slot+(body_slots-1)*gap
    return dict(capacity=capacity,slot=slot,gap=gap,padding=padding,surfaceWidth=811,surfaceHeight=66,bodyWidth=body,bodyHeight=52 if compact else 66,visibleApps=visible,overflowCount=overflow)
