#!/usr/bin/env python3
"""CI-only immutable ZIP download check; never contact or change the VPS."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

if __name__=='__main__':
    if os.geteuid()!=0:raise SystemExit('Run as root in the isolated CI runner')
    root=Path(__file__).resolve().parents[2]
    spec=importlib.util.spec_from_file_location('pinned_update',root/'ops/vps-atualizar.py')
    updater=importlib.util.module_from_spec(spec);spec.loader.exec_module(updater)
    with tempfile.TemporaryDirectory(prefix='hestia-archive-') as temporary:
        updater.STATE=Path(temporary)/'state';source=updater.bundle()
        updater.verify_bundle(source)
        # Check reuse after real imports in the exact no-bytecode mode of the updater.
        code='import sys;sys.path.insert(0,sys.argv[1]);import upgrade,dependencies'
        subprocess.run([sys.executable,'-I','-B','-c',code,str(source/'professional')],check=True)
        assert updater.bundle()==source
        updater.verify_bundle(source)
        print(json.dumps({'state':'verified','source':updater.SOURCE,'files':updater.EXPECTED_FILES,
                          'manifest_sha256':updater.SUMS_SHA256,'reuse_after_import_verified':True,
                          'installer_executed':False,'vps_accessed':False}))
