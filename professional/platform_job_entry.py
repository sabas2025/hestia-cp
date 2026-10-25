#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0,'/usr/local/hestia/professional')
from ops import require_root
from control_plane import worker
if __name__=='__main__':
    require_root()
    if len(sys.argv)!=3:raise SystemExit(1)
    worker(Path('/usr/local/hestia'),Path('/'),sys.argv[1],sys.argv[2])
