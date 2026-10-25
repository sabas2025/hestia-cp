#!/usr/bin/env python3
"""Fixed-location root worker, never accepts commands or credentials on argv."""
import re
import sys
from pathlib import Path
sys.path.insert(0,'/usr/local/hestia/professional')
from ops import require_root
from business import work
if __name__ == '__main__':
    require_root()
    if len(sys.argv) != 3 or any(not re.fullmatch(r'[a-f0-9]{32}',v) for v in sys.argv[1:]):
        raise SystemExit(1)
    work(Path('/usr/local/hestia'),Path('/'),sys.argv[1],sys.argv[2])
