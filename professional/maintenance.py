#!/usr/bin/env python3
"""Audit delivery and repair the local file-manager/cache integration as root.

No package upgrades, cloud transfers, WebDAV operations or account/password changes.
"""
import argparse
import configparser
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from ops import require_root, private_directory, lock, safe_environment, username, utcnow
from apply import verify_deployment, atomic_file
from business import account, record, regular, prepare_cache_parent, pool_spec, MARKER
from filemanager import enabled
from mfa import root_json
from assistant import domain

ROOT=Path('/usr/local/hestia')
MINIMUM={'8.2':(8,2,35),'8.3':(8,3,36),'8.4':(8,4,27),'8.5':(8,5,12)}
PHP_BINARY_LIMIT=268435456

def run(args):
    try:
        result=subprocess.run(args,stdin=subprocess.DEVNULL,capture_output=True,timeout=30,env=safe_environment())
        return result.returncode,result.stdout[:1048576].decode(errors='replace')
    except (OSError,subprocess.TimeoutExpired):return 127,''

def php_version(value):
    match=re.search(r'(?<![0-9])(\d+)\.(\d+)\.(\d+)',value)
    if not match:return {'version':'unknown','october_21_fix':'unverified'}
    version=tuple(map(int,match.groups()));branch='.'.join(map(str,version[:2]))
    if re.search(r'(?:dev|alpha|beta|RC)', value, re.IGNORECASE):
        state='prerelease-review-required'
    elif branch in MINIMUM:
        state='included-in-reported-binary' if version>=MINIMUM[branch] else 'upgrade-required'
    else:state='vendor-backport-or-branch-review-required'
    return {'version':'.'.join(map(str,version)),'october_21_fix':state,
            'running_workers_verified':False,'session_upload_progress_verified':False}

def probe_php(path,runtime,runner=run):
    result={'runtime':runtime,'version':'unknown','version_probe_attempted':False,
            'binary_metadata_verified':False,'package_integrity_verified':False,
            'running_workers_verified':False,'session_upload_progress_verified':False}
    try:
        # Inspect metadata without reading an ELF into memory. Size is classified
        # separately from ownership/permissions, preserving configuration limits.
        info=regular(path,(1<<63)-1,metadata_only=True)
        if info is None:raise ValueError('Binary missing')
    except (ValueError,OSError):
        return {**result,'state':'binary-metadata-review-required'}
    result.update(binary_metadata_verified=True,binary_size_bytes=info.st_size)
    if not 0<info.st_size<=PHP_BINARY_LIMIT:
        return {**result,'state':'binary-size-review-required','maximum_binary_bytes':PHP_BINARY_LIMIT}
    if not info.st_mode & 0o111:
        return {**result,'state':'binary-not-executable'}
    result['version_probe_attempted']=True
    code,text=runner([str(path),'-n','-r','echo PHP_VERSION;'])
    if code!=0:return {**result,'state':'binary-command-failed'}
    version=php_version(text)
    return {**result,**version,'state':'version-collected' if version.get('version')!='unknown' else 'binary-version-unverified'}

def backend(root,actor,owner,as_web=False):
    # List domains only. Neither this probe nor its output can contain passwords.
    args=[str(root/'bin/v-professional-editor'),actor,'domains']
    if as_web:args=['/usr/bin/sudo','-n','-u','hestiaweb','--','/usr/bin/sudo','-n',*args]
    try:
        result=subprocess.run(args,input=json.dumps({'owner':owner}),text=True,capture_output=True,
                              timeout=20,env=safe_environment())
        data=json.loads(result.stdout) if result.returncode==0 else {}
        domains=data.get('domains') if isinstance(data,dict) else None
        if result.returncode==0 and (not isinstance(domains,list) or any(not isinstance(d,str) for d in domains)):
            return {'available':False,'exit':0,'state':'invalid-response'}
        domains=domains or []
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
    verified=output.get('integrity',{}).get('state')=='verified'
    if verified:
        output['filemanager']['root_probe']=backend(root,actor,owner)
        output['filemanager']['panel_permissions_probe']=backend(root,actor,owner,as_web=True)
    else:
        output['filemanager']['root_probe']={'available':False,'state':'not-run-unverified-deployment'}
        output['filemanager']['panel_permissions_probe']={'available':False,'state':'not-run-unverified-deployment'}
    binaries=[root/'php/bin/php']
    for branch in ('8.0','8.1','8.2','8.3','8.4','8.5'):
        binaries.append(fs/('usr/bin/php'+branch))
    for path in binaries:
        if verified and path.is_file():
            output['php'].append(probe_php(path,'panel' if path==root/'php/bin/php' else path.name,runner))
    cfg=fs/'etc/hestiacp/professional/cloud-backup.json'
    try:
        from cloud_backup import settings
        targets=settings(cfg)['targets']
        output['cloud']={'configured':True,'targets':[{'id':t['id'],'provider':t['provider']} for t in targets],
                         'delivery_verified_by_this_audit':False}
    except (ValueError,OSError,KeyError,TypeError,configparser.Error):
        exists=cfg.exists() or cfg.is_symlink()
        output['cloud']={'configured':None if exists else False,
                         'state':'review-required' if exists else 'not-configured',
                         'delivery_verified_by_this_audit':False}
    output['package_updates_applied']=False
    output['status']='review-required'  # Runtime versions and availability are not acceptance tests.
    return output

def repair(root=ROOT,fs=Path('/'),enable_filemanager=False,start_nginx=False,runner=run,cache_owner=None,cache_domain=None):
    if cache_owner:username(cache_owner)
    if cache_domain:cache_domain=domain(cache_domain)
    if verify_deployment(root)['state']!='verified':raise ValueError('Deployment integrity requires review')
    result={'state':'running','phase':'preflight','cache_parents':[],'nextcloud_or_webdav_modified':False,
            'twofa_bypassed':False,'packages_upgraded':False,'started_at':utcnow()}
    folder=private_directory(root/'data/professional-maintenance',0o700)
    receipt=folder/'last-repair.json'
    with lock(root/'data/professional-business/locks/change.lock'),lock(folder/'repair.lock'):
        if verify_deployment(root)['state']!='verified':raise ValueError('Deployment integrity requires review')
        root_json(receipt,result)
        migrations=[];applied=[];service_touched=False;was_active=False
        try:
            pools=[]
            for path in sorted((fs/'etc/nginx/conf.d').glob('hestia-pro-cache-*.conf')):
                data=regular(path)
                match=re.match(re.escape(MARKER)+r'\n# ([a-z][a-z0-9_]{1,29})/([A-Za-z0-9.-]+)\n',data.decode() if data else '')
                if not match:raise ValueError('Unrecognized cache configuration')
                owner,name=match.groups()
                if cache_owner and owner!=cache_owner:continue
                if cache_domain and name!=cache_domain:continue
                account(root,owner,target=True);record(root,owner,'web',name)
                spec=pool_spec(fs,owner,name)
                legacy=pool_spec(fs,owner,name,legacy=True)['body'].encode()
                if str(path)!=spec['path'] or data not in (spec['body'].encode(),legacy):raise ValueError('Modified cache configuration')
                if data==legacy:
                    if not cache_domain or not start_nginx:
                        raise ValueError('Legacy cache migration requires an explicit domain and Nginx validation/start flag')
                    info=path.stat()
                    migrations.append({'path':path,'before':data,'body':spec['body'].encode(),
                                       'mode':info.st_mode & 0o777,'gid':info.st_gid,'owner':owner,'domain':name})
                pools.append(owner)
            previous=enabled(root) if enable_filemanager else None
            result['phase']='cache-parents';root_json(receipt,result)
            for owner in sorted(set(pools)):
                prepare_cache_parent(fs,owner);result['cache_parents'].append(owner)
            result['cache_migrated']=[]
            if migrations:
                result['phase']='cache-migration';root_json(receipt,result)
                backup=folder/('cache-before-'+secrets.token_hex(12)+'.json')
                root_json(backup,{'schema':1,'files':[{'path':str(i['path']),'body':i['before'].decode(),
                                                    'mode':i['mode'],'gid':i['gid']} for i in migrations]})
                result['cache_configuration_backup']=str(backup)
                for item in migrations:
                    if regular(item['path'])!=item['before']:raise ValueError('Cache configuration changed during repair')
                    applied.append(item)
                    atomic_file(item['path'],item['body'],0o644);os.chown(item['path'],0,0)
                    result['cache_migrated'].append({'owner':item['owner'],'domain':item['domain']})
            if start_nginx:
                result['phase']='nginx-validation';root_json(receipt,result)
                if runner(['/usr/sbin/nginx','-t'])[0]!=0:raise ValueError('Nginx configuration test failed')
                code,text=runner(['/usr/bin/systemctl','is-active','nginx'])
                was_active=code==0 and text.strip()=='active'
                if not was_active:
                    result['phase']='nginx-start';root_json(receipt,result)
                    service_touched=True
                    if runner(['/usr/bin/systemctl','start','nginx'])[0]!=0:raise RuntimeError('Nginx start failed')
                    result['nginx_started']=True
                elif migrations:
                    result['phase']='nginx-reload';root_json(receipt,result)
                    service_touched=True
                    if runner(['/usr/bin/systemctl','reload','nginx'])[0]!=0:raise RuntimeError('Nginx reload failed')
                    result['nginx_reloaded']=True
                code,text=runner(['/usr/bin/systemctl','is-active','nginx'])
                if code!=0 or text.strip()!='active':raise RuntimeError('Nginx is not active')
                result['nginx_active']=True
            if enable_filemanager:
                result['phase']='filemanager-policy';root_json(receipt,result)
                policy=root/'data/professional-filemanager/policy.json'
                if not previous:
                    root_json(folder/'filemanager-policy.before.json',{'schema':1,'enabled':False})
                    root_json(policy,{'schema':1,'enabled':True})
                result['filemanager_enabled']=enabled(root)
            result.update(state='repaired-local',phase='completed',finished_at=utcnow())
            root_json(receipt,result)
        except BaseException as error:
            result.update(state='failed-or-partial',error=type(error).__name__,reason=str(error)[:500],finished_at=utcnow())
            if applied:
                try:
                    for item in reversed(applied):
                        current=regular(item['path'])
                        if current not in (item['before'],item['body']):raise ValueError('Cache changed outside repair; preserve for review')
                        atomic_file(item['path'],item['before'],item['mode']);os.chown(item['path'],0,item['gid'])
                    if service_touched:
                        if runner(['/usr/sbin/nginx','-t'])[0]!=0:raise RuntimeError('Restored cache requires Nginx review')
                        code,text=runner(['/usr/bin/systemctl','is-active','nginx'])
                        action='reload' if code==0 and text.strip()=='active' else 'start' if was_active else None
                        if action:
                            if runner(['/usr/bin/systemctl',action,'nginx'])[0]!=0:raise RuntimeError('Cache service recovery failed')
                            code,text=runner(['/usr/bin/systemctl','is-active','nginx'])
                            if code!=0 or text.strip()!='active':raise RuntimeError('Cache service recovery unverified')
                    result['cache_rollback']='configuration-restored';result['cache_migrated']=[]
                except BaseException:
                    result['cache_rollback']='recovery-required'
            try:root_json(receipt,result)
            except OSError:pass
            raise
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=('audit','repair-local'))
    p.add_argument('--actor',default='sabasadmin',type=username);p.add_argument('--owner',default='sabas',type=username)
    p.add_argument('--domain',type=domain,help='Explicit domain required for legacy cache migration')
    p.add_argument('--enable-filemanager',action='store_true');p.add_argument('--start-nginx-if-stopped',action='store_true')
    args=p.parse_args();require_root()
    if args.action=='audit' and (args.enable_filemanager or args.start_nginx_if_stopped):raise ValueError('Repair flags require repair-local')
    result=audit(actor=args.actor,owner=args.owner) if args.action=='audit' else repair(
        enable_filemanager=args.enable_filemanager,start_nginx=args.start_nginx_if_stopped,
        cache_owner=args.owner,cache_domain=args.domain)
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':
    try:main()
    except (Exception,KeyboardInterrupt):
        print(json.dumps({'state':'refused-or-failed','message':'Revise integridade, permissões e o recibo de manutenção. Nenhuma atualização de pacotes ou operação de nuvem foi executada.'}),file=sys.stderr)
        sys.exit(1)
