"""Use an application's registered new-window action when it has one."""
import os
import sys


def main(path):
    try:
        from gi.repository import Gio
        app = Gio.DesktopAppInfo.new_from_filename(path)
        if app is not None:
            for action in app.list_actions():
                if action.casefold().replace('-', '').replace('_', '') == 'newwindow':
                    app.launch_action(action, None)
                    return
    except (ImportError, ValueError):
        pass
    os.execvp('gio', ['gio', 'launch', path])


if __name__ == '__main__':
    main(sys.argv[1])
