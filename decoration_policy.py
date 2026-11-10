"""On-demand decoration selection; no separate titlebar windows or polling."""
def client_draws_x11(motif=None,extents=None):
    return bool(extents and len(extents)>=4) or bool(motif and len(motif)>=3 and int(motif[0])&2 and int(motif[2])==0)

def apply_auto_decorations(request=None,command=None):
    if request is None or command is None:
        import sway_events
        request=request or sway_events.request;command=command or sway_events.command
    connection=None;commands=[]
    try:
        def visit(node):
            nonlocal connection
            if node.get('app_id') or node.get('window'):
                mode='normal'
                if node.get('shell')=='xdg_shell':mode='csd'
                elif node.get('window'):
                    try:
                        from xwayland_controls import load_xlib
                        load_xlib()
                        from Xlib import display,X
                        if connection is None:connection=display.Display()
                        window=connection.create_resource_object('window',node['window'])
                        def hint(name):
                            result=window.get_full_property(connection.intern_atom(name),X.AnyPropertyType)
                            return list(result.value) if result else None
                        if client_draws_x11(hint('_MOTIF_WM_HINTS'),hint('_GTK_FRAME_EXTENTS')):mode='pixel'
                    except Exception:pass
                ident=node.get('id')
                if type(ident) is int and node.get('border')!=mode:commands.append(f'[con_id={ident}] border {mode}'+(' 1' if mode=='pixel' else ''))
            for child in node.get('nodes',[])+node.get('floating_nodes',[]):visit(child)
        visit(request(4))
        results=[]
        for text in commands:
            try:results.append(command(text))
            except ValueError:
                # Some legacy native clients cannot draw a titlebar. Keep the
                # compositor-owned fallback for those, never a detached overlay.
                if 'border csd' not in text:raise
        return results
    finally:
        if connection:connection.close()
