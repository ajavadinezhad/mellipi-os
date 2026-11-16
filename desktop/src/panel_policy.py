"""Layer-shell keyboard focus policy (none=0, exclusive=1, on-demand=2)."""

CENTERED_PANELS=('launcher','overview','space-map','settings','system-settings','session-exit')

SPINE_FOOTER_PANELS=('quick','music','usage','notifications','tray','bluetooth','battery','screenshot','window-placement')

UTILITY_PANELS=frozenset(('quick','music','usage','notifications','tray','bluetooth','battery','screenshot','settings','system-settings','window-placement'))

def keyboard_mode(panel):
    # Popovers retain keyboard navigation and close through the existing
    # transparent outside-click surface. Unknown/closed surfaces cannot grab.
    return 1 if panel in ('fold','launcher','overview','space-map','shelf','ai','capture','switcher','window-capture','session-exit',*UTILITY_PANELS) else 2

PANEL_EDGES=('left','right','top','bottom')
PANEL_THICKNESS=64
TOP_STRIP_HEIGHT=46

def panel_edge(appearance):
    value=appearance.get('panelPosition','left') if isinstance(appearance,dict) else appearance
    return value if value in PANEL_EDGES else 'left'

def panel_thickness(appearance):
    return 52 if appearance.get('density')=='extra' else 64 if appearance.get('compact',True) else 76

def panel_rect(screen,edge,thickness=PANEL_THICKNESS):
    if isinstance(edge,dict):thickness=panel_thickness(edge)+(16 if edge.get('taskbarFloating') else 0)
    edge=panel_edge(edge);x,y=screen['x'],screen['y'];width,height=screen['width'],screen['height']
    if edge in ('left','right'):
        return dict(x=x if edge=='left' else x+width-thickness,y=y,width=thickness,height=height)
    return dict(x=x,y=y if edge=='top' else y+height-thickness,width=width,height=thickness)

def taskbar_surface_rect(screen,appearance,*,fixed_top):
    rect=panel_rect(screen,appearance)
    if fixed_top and panel_edge(appearance) in ('left','right'):
        rect.update(y=rect['y']+TOP_STRIP_HEIGHT,height=max(1,rect['height']-TOP_STRIP_HEIGHT))
    return rect


def panel_available_size(screen,edge):
    vertical=panel_edge(edge) in ('left','right');extra=(panel_thickness(edge)-64+(16 if edge.get('taskbarFloating') else 0)) if isinstance(edge,dict) else 0
    return dict(width=max(1,screen['width']-(92+extra if vertical else 32)),height=max(1,screen['height']-(32 if vertical else 92+extra)))

def overlay_layout(panel,edge):
    """Layer anchors, insets and inner-buffer alignment for one taskbar edge."""
    edge=panel_edge(edge)
    if panel in CENTERED_PANELS:return dict(anchors=0,margins=(0,0,0,0),horizontal='center',vertical='center')
    footer=panel in SPINE_FOOTER_PANELS
    if edge=='left':return dict(anchors=6 if footer else 5,margins=(76,0,0,16) if footer else (76,16,0,0),horizontal='left',vertical='bottom' if footer else 'top')
    if edge=='right':return dict(anchors=10 if footer else 9,margins=(0,0,76,16) if footer else (0,16,76,0),horizontal='right',vertical='bottom' if footer else 'top')
    if edge=='top':return dict(anchors=9 if footer else 5,margins=(0,76,16,0) if footer else (16,76,0,0),horizontal='right' if footer else 'left',vertical='top')
    return dict(anchors=10 if footer else 6,margins=(0,0,16,76) if footer else (16,0,0,76),horizontal='right' if footer else 'left',vertical='bottom')

def panel_mask_origin(buffer_width,buffer_height,body_width,body_height,panel,edge):
    layout=overlay_layout(panel,edge)
    x=(buffer_width-body_width)/2 if layout['horizontal']=='center' else buffer_width-body_width if layout['horizontal']=='right' else 0
    y=(buffer_height-body_height)/2 if layout['vertical']=='center' else buffer_height-body_height if layout['vertical']=='bottom' else 0
    return dict(x=int(x+0.5),y=int(y+0.5))

def panel_body_origin(panel,width,height,screen,edge,body=None,*,content_size=None):
    # For a layer surface, width/height describe its stable buffer; align it
    # using the visible content size so the masked body stays on the output.
    layout=taskbar_overlay_layout(panel,screen,edge,body,content_size or (width,height)) if body else overlay_layout(panel,edge);left,top,right,bottom=layout['margins']
    x=screen['x']+(screen['width']-width)/2 if layout['horizontal']=='center' else screen['x']+screen['width']-width-right if layout['horizontal']=='right' else screen['x']+left
    y=screen['y']+(screen['height']-height)/2 if layout['vertical']=='center' else screen['y']+screen['height']-height-bottom if layout['vertical']=='bottom' else screen['y']+top
    return dict(x=x,y=y)


def taskbar_body_rect(screen,appearance,*,fixed_top=False):
    surface=taskbar_surface_rect(screen,appearance,fixed_top=fixed_top);edge=panel_edge(appearance)
    vertical=edge in ('left','right');margin=8 if appearance.get('taskbarFloating') else 0
    available=surface['height'] if vertical else surface['width']
    length=max(1,available-2*margin)
    thickness=panel_thickness(appearance)
    if vertical:return dict(x=surface['x']+margin,y=surface['y']+(surface['height']-length)//2,width=thickness,height=length)
    return dict(x=surface['x']+(surface['width']-length)//2,y=surface['y']+margin,width=length,height=thickness)


def taskbar_overlay_layout(panel,screen,edge,body,content_size=None):
    result=overlay_layout(panel,edge)
    if panel in CENTERED_PANELS:return result
    edge=panel_edge(edge);footer=panel in SPINE_FOOTER_PANELS
    sx,sy=screen.get('x',0),screen.get('y',0);right=sx+screen['width'];bottom=sy+screen['height']
    if edge=='left':m=(body['x']+body['width']-sx+12,0,0,bottom-body['y']-body['height']+16) if footer else (body['x']+body['width']-sx+12,body['y']-sy+16,0,0)
    elif edge=='right':m=(0,0,right-body['x']+12,bottom-body['y']-body['height']+16) if footer else (0,body['y']-sy+16,right-body['x']+12,0)
    elif edge=='top':m=(0,body['y']+body['height']-sy+12,right-body['x']-body['width']+16,0) if footer else (body['x']-sx+16,body['y']+body['height']-sy+12,0,0)
    else:m=(0,0,right-body['x']-body['width']+16,bottom-body['y']+12) if footer else (body['x']-sx+16,0,0,bottom-body['y']+12)
    if content_size:
        # The popup can be larger than the floating bar. Clamp only along
        # the bar; moving towards the bar would overlap its input surface.
        index = (3 if footer else 1) if edge in ('left','right') else (2 if footer else 0)
        span, size = (screen['height'], content_size[1]) if index in (1,3) else (screen['width'], content_size[0])
        limit = max(0, span - size)
        edge_gap = min(16, limit // 2)
        clamped = max(edge_gap, min(m[index], limit - edge_gap))
        m = (*m[:index], clamped, *m[index+1:])
    return dict(result,margins=tuple(round(value) for value in m))


def workspace_drop_target(targets,x,y):
    return next((row['id'] for row in targets
                 if row['x']<=x<row['x']+row['width'] and row['y']<=y<row['y']+row['height']),None)
