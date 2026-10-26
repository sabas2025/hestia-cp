#!/usr/bin/env python3
"""Audit delivery and repair the local file-manager/cache integration as root.

No package upgrades, cloud transfers, WebDAV operations or account/password changes.
"""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from ops import require_root, private_directory, lock, safe_environment, username
from apply import verify_deployment
from business import account, record, regular, prepare_cache_parent, pool_spec, MARKER
from filemanager import enabled
from mfa import root_json

ROOT=Path('/usr/local/hestia')
MINIMUM={'8.2':(8,2,35),'8.3':(8,3,36),'8.4':(8,4,27),'8.5':(8,5,12)}

def run(args):
    try:
        result=subprocess.run(args,stdin=subprocess.DEVNULL,capture_output=True,timeout=30,env=safe_environment())
        return result.returncode,result.stdout[:1048576].decode(errors='replace')
    except (OSError,subprocess.TimeoutExpired):return 127,''

def php_version(value):
    match=re.search(r'(?<![0-9])(\d+)\.(\d+)\.(\d+)',value)
    if not match:return {'version':'unknown','october_21_fix':'unverified'}
    version=tuple(map(int,match.groups()));branch='.'.join(map(str,version[:2]))
    if branch in MINIMUM:
        state='included-in-reported-binary' if version>=MINIMUM[branch] else 'upgrade-required'
    else:state='vendor-backport-or-branch-review-required'
    return {'version':'.'.join(map(str,version)),'october_21_fix':state,
            'running_workers_verified':False,'session_upload_progress_verified':False}

def backend(root,actor,owner,as_web=False):
    # List domains only. Neither this probe nor its output can contain passwords.
    args=[str(root/'bin/v-professional-editor'),actor,'domains']
    if as_web:args=['/usr/bin/sudo','-n','-u','hestiaweb','--','/usr/bin/sudo','-n',*args]
    try:
        result=subprocess.run(args,input=json.dumps({'owner':owner}),text=True,capture_output=True,
                              timeout=20,env=safe_environment())
        domains=json.loads(result.stdout).get('domains',[]) if result.returncode==0 else []
        return {'exit':result.returncode,'domain_count':len(domains),'available':result.returncode==0}
    except (OSError,ValueError,subprocess.TimeoutExpired):return {'available':False,'exit':127}

def audit(root=ROOT,fs=Path('/'),actor='sabasadmin',owner='sabas',runner=run):
    username(actor);username(owner)
    output={'schema':1,'vps_modified':False,'excluded_operations':['nextcloud','webdav'],
            'filemanager':{},'php':[]}
    for name,fn in (
        ('integrity',lambda:verify_deployment(root)),
        ('filemanager_enabled',lambda:enabled(root)),
        ('administrator_twofa',lambda:bool(account(root,actor).get('TWOFA'))),
    ):
        try:output[name]=fn()
        except (ValueError,OSError,KeyError):output[name]={'state':'review-required'}
    for service in ('nginx','hestia-web-terminal','fail2ban'):
        code,text=runner(['/usr/bin/systemctl','is-active',service])
        output[service]={'active':code==0 and text.strip()=='active'}
    output['filemanager']['root_probe']=backend(root,actor,owner)
    output['filemanager']['panel_permissions_probe']=backend(root,actor,owner,as_web=True)
    binaries=[root/'php/bin/php']
    for branch in ('8.0','8.1','8.2','8.3','8.4','8.5'):
        path=shutil.which('php'+branch)
        if path:binaries.append(Path(path))
    for path in binaries:
        if path.is_file():
            code,text=runner([str(path),'-n','-r','echo PHP_VERSION;'])
            row=php_version(text if code==0 else '')
            row['runtime']='panel' if path==root/'php/bin/php' else path.name
            output['php'].append(row)
    cfg=fs/'etc/hestiacp/professional/cloud-backup.json'
    try:
        from cloud_backup import settings
        targets=settings(cfg)['targets']
        output['cloud']={'configured':True,'targets':[{'id':t['id'],'provider':t['provider']} for t in targets],
                         'delivery_verified_by_this_audit':False}
    except (ValueError,OSError,KeyError):output['cloud']={'configured':False,'delivery_verified_by_this_audit':False}
    output['package_updates_applied']=False
    output['status']='review-required'  # Runtime versions and availability are not acceptance tests.
    return output

def repair(root=ROOT,fs=Path('/'),enable_filemanager=False,start_nginx=False,runner=run):
    if verify_deployment(root)['state']!='verified':raise ValueError('Deployment integrity requires review')
    result={'state':'repaired-local','cache_parents':[],'nextcloud_or_webdav_modified':False,
            'twofa_bypassed':False,'packages_upgraded':False}
    folder=private_directory(root/'data/professional-maintenance',0o700)
    with lock(folder/'repair.lock'):
        for path in sorted((fs/'etc/nginx/conf.d').glob('hestia-pro-cache-*.conf')):
            data=regular(path)
            match=re.match(re.escape(MARKER)+r'\n# ([a-z][a-z0-9_]{1,29})/([A-Za-z0-9.-]+)\n',data.decode() if data else '')
            if not match:raise ValueError('Unrecognized cache configuration')
            owner,name=match.groups();account(root,owner,target=True);record(root,owner,'web',name)
            spec=pool_spec(fs,owner,name)
            if str(path)!=spec['path'] or data!=spec['body'].encode():raise ValueError('Modified cache configuration')
            prepare_cache_parent(fs,owner);result['cache_parents'].append(owner)
        if enable_filemanager:
            previous=enabled(root)  # Refuse malformed policy instead of overwriting it.
            policy=root/'data/professional-filemanager/policy.json'
            if not previous:
                root_json(folder/'filemanager-policy.before.json',{'schema':1,'enabled':False})
                root_json(policy,{'schema':1,'enabled':True})
            result['filemanager_enabled']=enabled(root)
        if start_nginx:
            if runner(['/usr/sbin/nginx','-t'])[0]!=0:raise ValueError('Nginx configuration test failed')
            code,text=runner(['/usr/bin/systemctl','is-active','nginx'])
            if code!=0 or text.strip()!='active':
                if runner(['/usr/bin/systemctl','start','nginx'])[0]!=0:raise RuntimeError('Nginx start failed')
            code,text=runner(['/usr/bin/systemctl','is-active','nginx'])
            if code!=0 or text.strip()!='active':raise RuntimeError('Nginx is not active')
            result['nginx_active']=True
        root_json(folder/'last-repair.json',result)
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=('audit','repair-local'))
    p.add_argument('--actor',default='sabasadmin',type=username);p.add_argument('--owner',default='sabas',type=username)
    p.add_argument('--enable-filemanager',action='store_true');p.add_argument('--start-nginx-if-stopped',action='store_true')
    args=p.parse_args();require_root()
    if args.action=='audit' and (args.enable_filemanager or args.start_nginx_if_stopped):raise ValueError('Repair flags require repair-local')
    result=audit(actor=args.actor,owner=args.owner) if args.action=='audit' else repair(
        enable_filemanager=args.enable_filemanager,start_nginx=args.start_nginx_if_stopped)
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':
    try:main()
    except (Exception,KeyboardInterrupt):
        print(json.dumps({'state':'refused-or-failed','message':'Revise integridade, permissões e o recibo de manutenção. Nenhuma atualização de pacotes ou operação de nuvem foi executada.'}),file=sys.stderr)
        sys.exit(1)
