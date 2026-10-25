#!/usr/bin/env python3
"""Native template hook: provision the matching per-domain Nginx cache zone."""
import sys
from pathlib import Path
sys.path.insert(0,'/usr/local/hestia/professional')
from ops import require_root
from business import account, record, pool_spec, regular, MARKER
from apply import atomic_file

def install(root, fs, owner, name):
    account(root,owner,target=True); record(root,owner,'web',name)
    item = pool_spec(fs,owner,name); old = regular(item['path'])
    if old is not None and not old.startswith((MARKER+'\n').encode()):
        raise ValueError('Unmanaged cache pool')
    atomic_file(Path(item['path']),item['body'].encode(),item['mode'])

if __name__ == '__main__':
    require_root()
    if len(sys.argv) != 3: raise SystemExit(1)
    install(Path('/usr/local/hestia'),Path('/'),sys.argv[1],sys.argv[2])
