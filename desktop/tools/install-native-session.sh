#!/usr/bin/env bash
# Register a separate experimental session. Never edits the default or Sway entry.
set -euo pipefail
orbit_project="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
case "${1:-}" in
 --check) exec "$orbit_project/run-native-session.sh" --check ;;
 --preview) orbit_preview=1 ;;
 --help|-h)
  printf '%s\n' 'Usage: install-native-session.sh [--check | --preview]' \
   '--check: read-only runtime and DRM readiness.' \
   '--preview: print the exact two registration files without installing.' \
   'With no option, register Orbit Native (Experimental) alongside existing sessions.'
  exit 0 ;;
 '') orbit_preview=0 ;;
 *) echo 'Unknown option' >&2;exit 2 ;;
esac
if [[ "$orbit_preview" == 0 ]]; then
 "$orbit_project/run-native-session.sh" --check
 if [[ "$EUID" -ne 0 ]]; then
  echo "Run: sudo $orbit_project/tools/install-native-session.sh" >&2;exit 1
 fi
fi
/usr/bin/python3 - "$orbit_project" "$orbit_preview" <<'PY'
import json,os,shlex,sys,tempfile
from pathlib import Path
root=Path(sys.argv[1]);preview=sys.argv[2]=='1'
files={
 '/usr/local/bin/orbit-native-session':('#!/bin/sh\n# Independent experimental native login session.\nexec '+shlex.quote(str(root/'run-native-session.sh'))+' "$@"\n',0o755),
 '/usr/share/wayland-sessions/orbit-native.desktop':('[Desktop Entry]\nName=Abstract (Experimental)\nComment=Abstract native DRM/KMS desktop with workspace animation\nExec=/usr/local/bin/orbit-native-session\nTryExec=/usr/local/bin/orbit-native-session\nType=Application\nDesktopNames=Orbit;\n',0o644)}
if preview:print(json.dumps({path:{'mode':oct(mode),'content':text} for path,(text,mode) in files.items()},indent=2));sys.exit(0)
for name,(text,mode) in files.items():
 path=Path(name);path.parent.mkdir(parents=True,exist_ok=True)
 fd,temporary=tempfile.mkstemp(prefix='.orbit-native-',dir=path.parent)
 try:
  with os.fdopen(fd,'w') as stream:stream.write(text);stream.flush();os.fsync(stream.fileno())
  os.chmod(temporary,mode);os.replace(temporary,path)
 finally:
  if os.path.exists(temporary):os.unlink(temporary)
print('Registered Abstract (Experimental). Existing Orbit/Sway/Mint sessions and login default are unchanged.')
print('Save work before deliberately logging out and choosing the new entry. Hardware login has not been validated.')
PY
