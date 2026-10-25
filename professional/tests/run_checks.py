#!/usr/bin/env python3
"""Run mandatory release checks. --quick explicitly reports incomplete optional checks."""
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
    parser.add_argument('--quick',action='store_true',help='Allow an incomplete local run; never mark it passed')
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
        for path in [*(ROOT/'web/professional').glob('*.php'), *(ROOT/'web/inc/2fa').glob('*.php')]:run('PHP lint '+str(path.relative_to(ROOT)),[php,'-n','-l',str(path)])
        run('PHP authorization and data-scoping assertions',[php,'-n',str(ROOT/'professional/tests/test_dashboard.php')])
        result['php_runtime']=run('PHP test runtime',[php,'--version']).stdout.splitlines()[0]
    else:result['checks'].append({'name':'PHP tests','status':'unavailable'})
    shellcheck=os.environ.get('SHELLCHECK_BINARY') or shutil.which('shellcheck')
    if shellcheck:
        run('ShellCheck new shared code',['%s'%shellcheck,'--severity=warning','-e','SC1091,SC2034',str(ROOT/'install/hst-common.sh'),str(ROOT/'install/hst-install.sh')])
        run('ShellCheck installer error-level findings',[shellcheck,'--severity=error','-e','SC1091,SC2034',str(ROOT/'install/hst-install-debian.sh'),str(ROOT/'install/hst-install-ubuntu.sh')])
    else: result['checks'].append({'name':'ShellCheck','status':'unavailable'})
    node=shutil.which('node')
    if node:run('JavaScript syntax',[node,'--check',str(ROOT/'web/professional/dashboard.js')])
    if node:run('Operations JavaScript syntax',[node,'--check',str(ROOT/'web/professional/business.js')])
    if node:
        for script in ('editor.js','platform.js'):run('Tools JavaScript syntax '+script,[node,'--check',str(ROOT/'web/professional'/script)])
    if node:run('Node project example syntax',[node,'--check',str(ROOT/'professional/node-server.example.mjs')])
    else: result['checks'].append({'name':'Node/JavaScript','status':'unavailable'})
    for name in ('v-add-user-2fa', 'v-check-user-2fa', 'v-professional-mfa'):run('Bash MFA syntax '+name,['bash','-n',str(ROOT/'bin'/name)])
    run('Python syntax',[sys.executable,'-m','compileall','-q',str(ROOT/'professional')])
    if php:run('Whole-tree source syntax',[sys.executable,str(ROOT/'professional/tests/static_syntax.py')])
    if os.environ.get('NGINX_BINARY') or shutil.which('nginx'):
        run('Nginx public cache template validation',[sys.executable,str(ROOT/'professional/tests/validate_cache.py')])
    else:result['checks'].append({'name':'Nginx public cache template validation','status':'unavailable'})
    if os.environ.get('SSHD_BINARY') or shutil.which('sshd'):
        run('OpenSSH generated policy validation',[sys.executable,str(ROOT/'professional/tests/validate_ssh.py')])
    else:result['checks'].append({'name':'OpenSSH generated policy validation','status':'unavailable'})
    if node and os.environ.get('PLAYWRIGHT_MODULE') and os.environ.get('CHROME_BIN'):
        run('Generate preview from current PHP',[sys.executable,str(ROOT/'professional/tests/build_preview.py')])
        run('Browser desktop and mobile',[node,str(ROOT/'professional/tests/test_visual.cjs')])
        run('Operations browser desktop and mobile',[node,str(ROOT/'professional/tests/test_business_visual.cjs')])
        run('Editor and platform browser desktop and mobile',[node,str(ROOT/'professional/tests/test_tools_visual.cjs')])
    else: result['checks'].append({'name':'Browser desktop and mobile','status':'unavailable'})
    result['mode'] = 'quick' if args.quick else 'release'
    complete = outcome.wasSuccessful() and not outcome.skipped and all(c['status']=='passed' for c in result['checks'])
    result['status']='passed' if complete else 'incomplete-or-failed'
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'status':result['status'],'python':result['python'],'groups':len(result['checks']),'report':str(args.output)},ensure_ascii=False))
    return 0 if complete or (args.quick and outcome.wasSuccessful() and not any(c['status']=='failed' for c in result['checks'])) else 1

if __name__=='__main__':sys.exit(main())
