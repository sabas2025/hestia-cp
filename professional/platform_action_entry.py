#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0,'/usr/local/hestia/professional')
from ops import require_root
from control_plane import decode, submit
if __name__=='__main__':
    require_root()
    if len(sys.argv)!=2:raise SystemExit(1)
    try:submit(Path('/usr/local/hestia'),Path('/'),decode(sys.argv[1]))
    except Exception:
        print('Task launch refused.',file=sys.stderr);raise SystemExit(1)
