#!/usr/bin/env python3
"""Update an existing, verified overlay. Never install the Hestia stack or user data."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import time
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parent))
import apply as overlay
from business import regular
from mfa import root_json
from ops import config, lock, private_directory, private_read, require_root, safe_environment

SYSTEM_FILES = ['etc/logrotate.d/hestia-professional-mfa','etc/hestiacp/hooks/post_install.sh',
                'etc/hestiacp/hooks/post_install.before-professional.sh']
UNITS = ['hestia-professional-health.service','hestia-professional-health.timer',
         'hestia-professional-backup@.service','hestia-professional-backup@.timer',
         'hestia-professional-cloud-backup@.service','hestia-professional-cloud-backup@.timer']
EXTRA = ['professional/deployment.json','data/professional/deployment-status.json','web/templates/pages/edit_web.php','bin/v-add-sys-web-terminal',
         'data/professional/health.json','professional/hst-common.sh','professional/bundle/install/assets.lock.tsv',
         'data/api/professional-readonly','web/templates/includes/panel.php',
         'bin/v-add-sys-filemanager','bin/v-add-user-composer','bin/v-add-sys-roundcube',
         'professional/original-v-add-sys-filemanager','professional/original-v-add-user-composer',
         'professional/original-v-add-sys-roundcube']

def command(args, timeout=90):
    result=subprocess.run(args,stdin=subprocess.DEVNULL,capture_output=True,env=safe_environment(),timeout=timeout)
    if result.returncode:raise RuntimeError('Validation failed: '+Path(args[0]).name)
    return result.stdout.decode(errors='replace')

def targets(root, source, fs):
    result={root/file.relative_to(source) for file in overlay.source_files(source)}
    result.update(root/name for name in EXTRA)
    result.update(root/'data/templates/web/nginx'/file.name for file in (source/'professional/cache-templates').glob('professional-safe.*'))
    result.update(fs/name for name in SYSTEM_FILES)
    result.update(fs/'etc/systemd/system'/name for name in UNITS)
    return sorted(result)

def preflight(root, source, fs=Path('/')):
    if root.is_symlink() or source.is_symlink() or root.resolve()==source.resolve():raise ValueError('Separate source required')
    if config(root/'conf/hestia.conf').get('VERSION')!='1.10.5':raise ValueError('Review this Hestia version first')
    if overlay.verify_deployment(root)['state']!='verified':raise ValueError('Installed layer differs from its saved manifest')
    old=json.loads(private_read(root/'professional/deployment.json',4194304))
    known={root/item['file'] for item in old['files']}
    allowed={root/name for name in EXTRA}|{fs/name for name in SYSTEM_FILES}|{fs/'etc/systemd/system'/name for name in UNITS}
    for path in targets(root,source,fs):
        regular(path,67108864)
        if path.exists() and path not in known|allowed:raise ValueError('Unrecognized existing target: '+path.name)
    for folder in ('data/professional-business/queue','data/professional-platform/jobs'):
        for path in (root/folder).glob('*.json'):
            item=json.loads(private_read(path))
            if item.get('state')=='running' or (item.get('state')=='queued' and item.get('expires',0)>=time.time()):
                raise ValueError('Wait for active administrative tasks')
    # This helper is an updater, never a recovery route for an unfinished fresh install.
    job=fs/'var/lib/hestia-github-deploy/job.json'
    if job.exists() and json.loads(private_read(job)).get('state')!='succeeded':raise ValueError('Inspect previous installation state')
    need=4*sum(path.stat().st_size for path in targets(root,source,fs) if path.exists())+67108864
    if shutil.disk_usage(root).free<need:raise ValueError('Insufficient space for rollback')
    return {'state':'ready','hestia':'1.10.5','from':old['overlay'],
            'to':json.loads((source/'professional/component-policy.json').read_text())['overlay_version'],
            'targets':len(targets(root,source,fs)),'installer_executed':False,'account_data_modified':False}

def snapshot(paths, backup):
    files=[]
    for path in paths:
        raw=regular(path,67108864)
        info=path.stat() if raw is not None else None
        files.append({'path':str(path),'content':None if raw is None else base64.b64encode(raw).decode(),
                      'mode':None if info is None else stat.S_IMODE(info.st_mode),
                      'uid':None if info is None else info.st_uid,'gid':None if info is None else info.st_gid})
    root_json(backup/'files.json',{'files':files});return files

def restore(files):
    for item in reversed(files):
        path=Path(item['path']);regular(path,67108864)
        if item['content'] is None:
            if path.exists():path.unlink()
        else:
            overlay.atomic_file(path,base64.b64decode(item['content'],validate=True),item['mode'])
            os.chown(path,item['uid'],item['gid'])

def syntax(source, root, runner=command):
    # Lint without importing application code or running package installers.
    for path in (source/'professional').glob('*.py'):compile(path.read_bytes(),str(path),'exec')
    php=root/'php/bin/php'
    if not php.is_file():raise ValueError('Native panel PHP unavailable')
    for path in (source/'web/professional').glob('*.php'):runner([str(php),'-n','-l',str(path)])
    for name in ('v-professional-editor','v-professional-platform','v-professional-business','v-professional-mfa'):
        runner(['/bin/bash','-n',str(source/'bin'/name)])

def run_upgrade(root,source,fs=Path('/'),runner=command,integrate=None,check=None):
    folder=private_directory(fs/'var/lib/hestia-professional-upgrade',0o700)
    with lock(folder/'upgrade.lock'),lock(root/'data/professional-business/locks/change.lock'),lock(root/'data/professional-platform/locks/execution.lock'):
        plan=preflight(root,source,fs);syntax(source,root,runner)
        for service in ('hestia','nginx','apache2'):runner(['/usr/bin/systemctl','is-active',service])
        backup=private_directory(folder/uuid.uuid4().hex,0o700)
        files=snapshot(targets(root,source,fs),backup)
        try:timer_enabled=runner(['/usr/bin/systemctl','is-enabled','hestia-professional-health.timer']).strip()=='enabled'
        except RuntimeError:timer_enabled=False
        record={**plan,'state':'applying','backup':str(backup),'started':time.time()};root_json(backup/'status.json',record)
        try:
            overlay.apply_files(root,source)
            (integrate or overlay.enable_services)(root)
            if overlay.verify_deployment(root)['state']!='verified':raise ValueError('Post-update manifest mismatch')
            runner(['/usr/bin/systemctl','is-active','hestia'])
            runner(['nginx','-t']);runner(['apache2ctl','configtest'])
            if check:check(root)
            else:runner(['/usr/bin/python3',str(root/'professional/health.py'),'--write','--installation-check'])
            record.update(state='succeeded',finished=time.time());root_json(backup/'status.json',record)
            return record
        except BaseException:
            record.update(state='recovery-required',finished=time.time())
            try:
                if not timer_enabled:runner(['/usr/bin/systemctl','disable','--now','hestia-professional-health.timer'])
                restore(files);runner(['/usr/bin/systemctl','daemon-reload'])
                if overlay.verify_deployment(root)['state']!='verified':raise ValueError('Rollback manifest mismatch')
                record['state']='failed-restored'
            finally:root_json(backup/'status.json',record)
            raise

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=('plan','apply'))
    parser.add_argument('--source',type=Path,required=True);args=parser.parse_args();require_root()
    root=Path('/usr/local/hestia');source=args.source.absolute()
    # The pinned bootstrap validates every source byte before invoking this entry point.
    result=preflight(root,source) if args.action=='plan' else run_upgrade(root,source)
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':
    try:main()
    except Exception:
        print('Upgrade refused or failed; inspect /var/lib/hestia-professional-upgrade/*/status.json. No fresh installer was executed.',file=sys.stderr)
        sys.exit(1)
