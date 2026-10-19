#!/usr/bin/env python3
"""Syntax-check source PHP/Bash; skip dependency directories and emit only a summary."""
import concurrent.futures
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
def main():
    php=os.environ.get('PHP_BINARY','php')
    def check(path):
        kind=None;command=None
        if path.suffix=='.php':kind='php';command=[php,'-n','-l',str(path)]
        elif path.read_bytes()[:80].startswith((b'#!/bin/bash',b'#!/usr/bin/env bash')):kind='bash';command=['bash','-n',str(path)]
        if command:
            result=subprocess.run(command,capture_output=True,text=True,timeout=20)
            return {'file':str(path.relative_to(ROOT)),'kind':kind,'passed':result.returncode==0,
                    'error':result.stderr[-600:] if result.returncode else ''}
    paths=[p for p in ROOT.rglob('*') if p.is_file() and not any(x in ('.git','node_modules','.qa','__pycache__') for x in p.parts)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:results=[r for r in pool.map(check,paths)if r]
    failed=[r for r in results if not r['passed']]
    print(json.dumps({'php':sum(r['kind']=='php'for r in results),'bash':sum(r['kind']=='bash'for r in results),'failures':failed}))
    return int(bool(failed))
if __name__=='__main__':sys.exit(main())
