#!/usr/bin/env python3
import sys
sys.path.insert(0,'/usr/local/hestia/professional')
from editor import main
if __name__=='__main__':
    try:main()
    except Exception:
        print('Editor operation refused.',file=sys.stderr);raise SystemExit(1)
