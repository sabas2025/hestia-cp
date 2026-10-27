#!/usr/bin/env python3
"""Patch only fingerprinted terminal releases; keep unknown builds for review."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from ops import require_root, private_directory, lock, safe_environment, private_read

ROOT=Path('/usr/local/hestia')
FILES={
    'server.js':('terminal-runtime.js','d077844995dcb225596d8780d957df6c51c6f8dd39668cafead79715d0964ada',0o755),
    'web-terminal-session-auth.php':('terminal-auth.php','aae48e898bbe957b8ad30eff715317eb939f4d77933e7e8f709ecafbee01e6c2',0o755),
}

def targets(root):
    paths=[root/'web-terminal'/name for name in FILES]
    return paths if any(p.exists() or p.is_symlink() for p in paths) else []

def inspect(root,source):
    from business import regular
    paths=targets(root)
    if not paths:return []
    output=[]
    for path in paths:
        asset,old_hash,mode=FILES[path.name]
        previous=regular(path,1048576);approved=regular(source/'professional'/asset,1048576)
        if previous is None or approved is None:raise ValueError('Terminal package is incomplete; review the installed package')
        digest=hashlib.sha256(previous).hexdigest();new_hash=hashlib.sha256(approved).hexdigest()
        if digest not in (old_hash,new_hash):raise ValueError('Unknown terminal build; preserve and review before patching')
        output.append({'path':path,'body':approved,'previous':previous,'previous_mode':path.stat().st_mode & 0o777,
                       'mode':mode,'changed':previous!=approved or path.stat().st_mode & 0o777!=mode})
    return output

def protect(root,source):
    from apply import atomic_file
    from mfa import root_json
    changes=inspect(root,source)
    if not changes:return {'state':'not-installed','changed':False,'files':[]}
    changed=any(c['changed'] for c in changes)
    if changed:
        folder=private_directory(root/'data/professional-terminal',0o700)
        with lock(folder/'patch.lock'):
            changes=inspect(root,source)
            for item in changes:
                backup=folder/('before-'+hashlib.sha256(item['previous']).hexdigest())
                if not backup.exists():atomic_file(backup,item['previous'],0o600)
            try:
                for item in changes:atomic_file(item['path'],item['body'],item['mode'])
            except BaseException:
                for item in changes:atomic_file(item['path'],item['previous'],item['previous_mode'])
                raise
            root_json(folder/'status.json',{'state':'files-patched','running_process_verified':False,'restart_required':True})
    return {'state':'files-patched','changed':changed,'running_process_verified':False,
            'files':[{'file':str(c['path'].relative_to(root)), 'sha256':hashlib.sha256(c['body']).hexdigest(), 'mode':c['mode']} for c in changes]}

def run(args):
    result=subprocess.run(args,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                          timeout=30,env=safe_environment())
    return result.returncode

def activate(root=ROOT,restart=False,runner=run):
    from apply import verify_deployment, atomic_file
    from mfa import root_json
    require_root()
    if verify_deployment(root)['state']!='verified':raise ValueError('Deployment integrity requires review')
    manifest=root/'professional/deployment.json';before=private_read(manifest)
    originals=inspect(root,root)
    try:
        result=protect(root,root)
        if result['state']=='not-installed':raise ValueError('Install the reviewed terminal package first')
        data=json.loads(before);names={item['file'] for item in result['files']}
        data['files']=[item for item in data['files'] if item['file'] not in names]+result['files']
        root_json(manifest,data)
        if verify_deployment(root)['state']!='verified':raise ValueError('Terminal patch integrity failed')
        if restart and runner(['/usr/bin/systemctl','is-active','--quiet','hestia-web-terminal'])==0:
            if runner(['/usr/bin/systemctl','restart','hestia-web-terminal'])!=0:raise RuntimeError('Terminal restart failed')
            if runner(['/usr/bin/systemctl','is-active','--quiet','hestia-web-terminal'])!=0:raise RuntimeError('Terminal is not active')
            result['running_process_verified']=True
        return {k:v for k,v in result.items() if k!='files'}
    except BaseException:
        for item in originals:atomic_file(item['path'],item['previous'],item['previous_mode'])
        atomic_file(manifest,before.encode(),0o600)
        raise

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=('apply',))
    p.add_argument('--restart-if-active',action='store_true');args=p.parse_args()
    print(json.dumps(activate(restart=args.restart_if_active)))

if __name__=='__main__':
    try:main()
    except (Exception,KeyboardInterrupt):
        print('Terminal hardening refused; review package fingerprints, integrity and service state.',file=sys.stderr);sys.exit(1)
