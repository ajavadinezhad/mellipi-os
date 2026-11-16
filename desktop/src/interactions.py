"""Small deterministic interaction models, independent of the renderer."""
def tooltip_position(screen,x,y,width=260,height=34,placement='auto',anchor_top=None,anchor_bottom=None):
    """Keep the complete bubble on its output, flipping away from the edge."""
    sx,sy,sw,sh=screen
    gap=8
    left=max(sx,min(x-width//2,sx+sw-width))
    below=(y if anchor_bottom is None else anchor_bottom)+gap
    above=(y if anchor_top is None else anchor_top)-gap-height
    choices=(above,below) if placement=='above' else (below,above)
    top=next((candidate for candidate in choices if sy<=candidate and candidate+height<=sy+sh),
             max(sy,min(choices[0],sy+sh-height)))
    return round(left),round(top)


def switch_order(windows,recent):
    by_id={w['id']:w for w in windows}
    ids=[i for i in recent if i in by_id]
    ids += [w['id'] for w in reversed(windows) if w['id'] not in ids]
    active=next((w['id'] for w in windows if w.get('active')),None)
    if active in ids:ids.remove(active);ids.insert(0,active)
    return [by_id[i] for i in ids]
