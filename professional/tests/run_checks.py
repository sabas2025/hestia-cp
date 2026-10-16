#!/usr/bin/env python3
"""Run the local test suite, syntax checks and optional visual test."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

ROOT=Path(__file__).resolve().parents[2]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'professional/test-results/verification.json')
    args=parser.parse_args()
    result={'generated_at':datetime.now(timezone.utc).isoformat(),'installer_executed':False,'vps_accessed':False,'checks':[]}
    def run(name,command):
        completed=subprocess.run(command,capture_output=True,text=True,timeout=120)
        result['checks'].append({'name':name,'status':'passed' if completed.returncode==0 else 'failed','exit':completed.returncode,'stdout':completed.stdout[-4000:],'stderr':completed.stderr[-4000:]})
        return completed
    suite=unittest.defaultTestLoader.discover(str(ROOT/'professional/tests'),pattern='test_*.py')
    outcome=unittest.TextTestRunner(verbosity=2).run(suite)
    result['python']={'tests':outcome.testsRun,'failures':len(outcome.failures),'errors':len(outcome.errors),'skipped':len(outcome.skipped)}
    for path in [ROOT/'install'/name for name in ['hst-install.sh','hst-common.sh','hst-install-debian.sh','hst-install-ubuntu.sh']]:run('bash -n '+path.name,['bash','-n',str(path)])
    php=os.environ.get('PHP_BINARY') or shutil.which('php')
    if php:
        for path in (ROOT/'web/professional').glob('*.php'):run('PHP lint '+path.name,[php,'-n','-l',str(path)])
        run('PHP authorization and data-scoping assertions',[php,'-n',str(ROOT/'professional/tests/test_dashboard.php')])
        result['php_runtime']=run('PHP test runtime',[php,'--version']).stdout.splitlines()[0]
    else:result['checks'].append({'name':'PHP tests','status':'unavailable'})
    shellcheck=os.environ.get('SHELLCHECK_BINARY') or shutil.which('shellcheck')
    if shellcheck:
        run('ShellCheck new shared code',['%s'%shellcheck,'--severity=warning','-e','SC1091,SC2034',str(ROOT/'install/hst-common.sh'),str(ROOT/'install/hst-install.sh')])
        run('ShellCheck installer error-level findings',[shellcheck,'--severity=error','-e','SC1091,SC2034',str(ROOT/'install/hst-install-debian.sh'),str(ROOT/'install/hst-install-ubuntu.sh')])
    node=shutil.which('node')
    if node:run('JavaScript syntax',[node,'--check',str(ROOT/'web/professional/dashboard.js')])
    if node and os.environ.get('PLAYWRIGHT_MODULE') and os.environ.get('CHROME_BIN'):
        run('Browser desktop and mobile',[node,str(ROOT/'professional/tests/test_visual.cjs')])
    result['status']='passed' if outcome.wasSuccessful() and all(c['status']=='passed' for c in result['checks']) else 'incomplete-or-failed'
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'status':result['status'],'python':result['python'],'groups':len(result['checks']),'report':str(args.output)},ensure_ascii=False))
    return 0 if result['status']=='passed' else 1

if __name__=='__main__':sys.exit(main())
