"""Small deterministic interaction models, independent of the renderer."""
def tooltip_position(screen,x,y,width=260,height=34,placement='auto',anchor_top=None,anchor_bottom=None):
    sx,sy,sw,sh=screen
    left=max(sx+8,min(x-width//2,sx+sw-width-8))
    if placement=='above':
        top=(y if anchor_top is None else anchor_top)-height-8
    elif placement=='below':
        top=(y if anchor_bottom is None else anchor_bottom)+8
        if top+height>sy+sh-72:top=(y if anchor_top is None else anchor_top)-height-8
    else:
        top=y-height-8 if y>sy+sh-110 else y+8
    bottom_margin=8 if placement in ('above','below') else 72
    return int(left),int(max(sy+36,min(top,sy+sh-height-bottom_margin)))

def switch_order(windows,recent):
    by_id={w['id']:w for w in windows}
    ids=[i for i in recent if i in by_id]
    ids += [w['id'] for w in reversed(windows) if w['id'] not in ids]
    active=next((w['id'] for w in windows if w.get('active')),None)
    if active in ids:ids.remove(active);ids.insert(0,active)
    return [by_id[i] for i in ids]
