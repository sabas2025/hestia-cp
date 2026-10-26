#!/usr/bin/python3 -I
"""Pinned updater for an already installed Hestia Professional; never reinstall."""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import io
import ipaddress
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import shutil
import stat
import subprocess
import sys
sys.dont_write_bytecode = True
import tempfile
import time
import urllib.request
import zipfile

SOURCE = '2c4fed6001164453ad68ada6fd35ce4459f2bef3'
SUMS_SHA256 = '830ffd0cacf44fd97ed9c83f873d41138c4d41e79605cd41f629f8b69b314fa1'
EXPECTED_FILES = 1745
STATE = Path('/var/lib/hestia-professional-upgrade')
HELPER = Path('/usr/local/sbin/hestia-professional-update')
POLICY = Path('/usr/sbin/policy-rc.d')
TEMPORARY_POLICY = b'#!/bin/sh\n# HESTIA_PROFESSIONAL_DEPENDENCIES_V1\nexit 101\n'
ENV = {'PATH':'/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin', 'HOME':'/root','LC_ALL':'C','LANG':'C'}

def controlled(path):
    path = Path(path)
    if path.is_symlink() or any(p.is_symlink() for p in path.parents): raise ValueError('Linked path refused')
    for p in (path,*path.parents):
        if p.exists():
            s = p.stat()
            if s.st_uid != 0 or (s.st_mode & 0o022 and not s.st_mode & stat.S_ISVTX):
                raise ValueError('Path must be root controlled')
    return path

def private_dir(path):
    path = controlled(path); path.mkdir(parents=True,exist_ok=True,mode=0o700)
    path.chmod(0o700); return path

def read_file(path, secret=True, limit=1048576):
    path = controlled(path)
    fd = os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        s = os.fstat(fd)
        if not stat.S_ISREG(s.st_mode) or s.st_nlink != 1 or s.st_size > limit or (secret and s.st_mode & 0o077):
            raise ValueError('Invalid file ownership, size or permissions')
        with os.fdopen(fd,'rb',closefd=False) as stream: data = stream.read(limit+1)
        if len(data)>limit: raise ValueError('Oversized file')
        return data
    finally: os.close(fd)

def atomic(path, data):
    path = controlled(path); private_dir(path.parent)
    fd, name = tempfile.mkstemp(prefix='.deploy-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as stream:
            os.fchmod(stream.fileno(),0o600); stream.write(data); stream.flush(); os.fsync(stream.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name): os.unlink(name)

def write_json(path, data): atomic(path,(json.dumps(data,separators=(',',':'))+'\n').encode())
def read_json(path): return json.loads(read_file(path))

@contextmanager
def locked():
    private_dir(STATE)
    fd = os.open(STATE/'controller.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:
        s = os.fstat(fd)
        if s.st_uid != 0 or not stat.S_ISREG(s.st_mode) or s.st_nlink != 1 or s.st_mode & 0o077: raise ValueError('Unsafe lock')
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB); yield
    finally: os.close(fd)

def checked(args, timeout=60, log=None):
    if log is not None:
        result = subprocess.run(args,stdin=subprocess.DEVNULL,stdout=log,stderr=log,env=ENV,timeout=timeout)
        text = ''
    else:
        result = subprocess.run(args,stdin=subprocess.DEVNULL,capture_output=True,env=ENV,timeout=timeout)
        if len(result.stdout)>1048576: raise ValueError('Oversized command output')
        text = result.stdout.decode(errors='replace')
    if result.returncode:
        if log is None:atomic(STATE/'command-error.log',(result.stdout+result.stderr)[-1048576:])
        raise RuntimeError('Command failed; inspect private VPS log')
    return text

def verify_bundle(folder, sums_hash=None, expected=None):
    sums_hash=SUMS_SHA256 if sums_hash is None else sums_hash
    expected=EXPECTED_FILES if expected is None else expected
    sums = read_file(folder/'SHA256SUMS',secret=False,limit=1048576)
    if hashlib.sha256(sums).hexdigest()!=sums_hash: raise ValueError('Unapproved checksum manifest')
    names = {'SHA256SUMS'}
    for line in sums.decode().splitlines():
        digest, name = line.split('  ',1); path = PurePosixPath(name)
        if not re.fullmatch(r'[a-f0-9]{64}',digest) or path.is_absolute() or '..' in path.parts or '\\' in name or name in names:
            raise ValueError('Unsafe or duplicate checksum path')
        names.add(name)
        data = read_file(folder/name,secret=False,limit=67108864)
        if hashlib.sha256(data).hexdigest()!=digest: raise ValueError('Source checksum mismatch')
    actual = {str(p.relative_to(folder)) for p in folder.rglob('*') if p.is_file()}
    if actual!=names or len(names)!=expected:
        raise ValueError('Unexpected source files: '+json.dumps({
            'expected':expected,'manifest':len(names),'actual':len(actual),
            'missing':sorted(names-actual)[:10],'extra':sorted(actual-names)[:10]}))

def unpack(data, target):
    if len(data)>52428800: raise ValueError('Oversized ZIP')
    names = set(); total = 0; prefix = None
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        members = archive.infolist()
        if len(members)>10000: raise ValueError('Too many ZIP entries')
        for item in members:
            path = PurePosixPath(item.filename); mode = item.external_attr>>16
            if path.is_absolute() or '..' in path.parts or '\\' in item.filename or not path.parts or item.filename in names:
                raise ValueError('Unsafe ZIP path')
            names.add(item.filename)
            if prefix is None: prefix = path.parts[0]
            if path.parts[0]!=prefix: raise ValueError('Multiple ZIP roots')
            if stat.S_IFMT(mode) not in (0,stat.S_IFREG,stat.S_IFDIR): raise ValueError('ZIP links or special files refused')
            relative = Path(*path.parts[1:])
            if str(relative)=='.':
                if not item.is_dir(): raise ValueError('Invalid ZIP root')
                continue
            destination = target/relative
            if item.is_dir(): destination.mkdir(parents=True,exist_ok=True); continue
            total += item.file_size
            if total>268435456: raise ValueError('Expanded source too large')
            destination.parent.mkdir(parents=True,exist_ok=True)
            with archive.open(item) as incoming, destination.open('xb') as outgoing: shutil.copyfileobj(incoming,outgoing)
            destination.chmod(0o755 if mode & 0o111 else 0o644)

def bundle():
    if not re.fullmatch(r'[a-f0-9]{40}',SOURCE) or not re.fullmatch(r'[a-f0-9]{64}',SUMS_SHA256):
        raise ValueError('Release has no approved source pin')
    parent=private_dir(STATE/'sources');target=parent/SOURCE
    if target.exists():
        controlled(target)
        if not target.is_dir():raise ValueError('Source cache is not a directory')
        try:verify_bundle(target);return target
        except (ValueError,OSError) as error:
            # Preserve an invalid cache in full; never ignore extra files or weaken hashes.
            if (STATE/'job.json').exists():
                old=read_json(STATE/'job.json')
                if old.get('state') in ('queued','running'):
                    raise ValueError('Invalid source cache while an update task is pending; inspect before recovery') from error
            saved=private_dir(STATE/'quarantine')/(SOURCE+'-'+secrets.token_hex(8))
            target.rename(saved)
            write_json(STATE/'source-cache-recovery.json',{'source':SOURCE,'preserved':str(saved),
                       'reason':str(error)[:2000],'at':time.time()})
    request=urllib.request.Request('https://codeload.github.com/sabas2025/hestia-cp/zip/'+SOURCE)
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request,timeout=90) as response:
        if not response.geturl().startswith('https://codeload.github.com/'):raise ValueError('Unexpected origin')
        data=response.read(52428801)
    with tempfile.TemporaryDirectory(prefix='source-',dir=parent) as temp:
        stage=Path(temp)/'bundle';stage.mkdir(mode=0o700)
        unpack(data,stage);verify_bundle(stage);stage.rename(target)
    return target

def cidr(value):
    if not value:
        fields=os.environ.get('SSH_CONNECTION','').split()
        if len(fields)!=4:raise ValueError('Supply --admin-cidr from the recovery console')
        address=ipaddress.ip_address(fields[0]);value=str(address)+('/32' if address.version==4 else '/128')
    network=ipaddress.ip_network(value,strict=False)
    if network.prefixlen<(24 if network.version==4 else 64):raise ValueError('Administrator exemption too broad')
    return str(network)

def components(value):
    names=value.split(',') if value else []
    if len(set(names))!=len(names) or set(names)-{'backup','waf','docker','node'}:raise ValueError('Unknown component')
    return names

# The pinned core's CLI hides preflight exceptions. This read-only wrapper reports
# the actual blocker, without running apply(), disabling integrity or printing file contents.
PLAN_CODE = r'''
import json,sys
from pathlib import Path
sys.dont_write_bytecode=True
source=Path(sys.argv[2]);sys.path.insert(0,str(source/'professional'))
import upgrade
original=upgrade.regular
def checked_file(path,*args):
    try:return original(path,*args)
    except (ValueError,OSError) as error:
        raise ValueError('Target blocked: '+str(path)+'; '+str(error)) from error
upgrade.regular=checked_file
root=Path('/usr/local/hestia')
try:result=upgrade.preflight(root,source)
except Exception as error:
    result={'state':'blocked','phase':'installed-preflight','error':type(error).__name__,'reason':str(error)[:2000]}
    try:
        integrity=upgrade.overlay.verify_deployment(root)
        if integrity.get('state')!='verified':result['integrity']=integrity
    except Exception:pass
print(json.dumps(result,ensure_ascii=False))
'''

def inspect_plan(source,runner=checked):
    result=json.loads(runner(['/usr/bin/python3','-I','-B','-c',PLAN_CODE,'plan',str(source)]))
    if not isinstance(result,dict) or result.get('state') not in ('ready','blocked'):
        raise ValueError('Invalid preflight response')
    return result

def status():
    if not (STATE/'job.json').exists():return {'state':'not-started','source':SOURCE}
    job=read_json(STATE/'job.json')
    result={key:job[key] for key in ('state','phase','unit','source','started','updated','overlay_updated','results') if key in job}
    if result.get('state') in ('queued','running') and time.time()-job.get('started',0)>5400:
        result['state']='interrupted-review'
    return result

def start(selected,recovery,runner=checked,loader=bundle):
    names=components(selected);recovery=cidr(recovery) if 'waf' in names else None
    source=loader()
    plan=inspect_plan(source,runner)
    if plan.get('state')!='ready':raise ValueError('Installed tree blocked: '+plan.get('reason','inspect plan'))
    with locked():
        if (STATE/'job.json').exists():
            old=read_json(STATE/'job.json')
            if old.get('state') in ('queued','running') and time.time()-old.get('started',0)<5400:
                raise ValueError('Previous update task has not finished')
            try:runner(['/usr/bin/systemctl','is-active',old['unit']])
            except RuntimeError:pass
            else:raise ValueError('Previous update task is still active')
        ident=secrets.token_hex(16);nonce=secrets.token_hex(16)
        unit='hestia-professional-upgrade-'+ident
        job={'state':'queued','phase':'overlay','source':SOURCE,'unit':unit,'id':ident,'nonce':nonce,
             'components':names,'admin_cidr':recovery,'started':time.time(),'updated':time.time(),'overlay_updated':False}
        write_json(STATE/'job.json',job)
        try:
            runner(['/usr/bin/systemd-run','--quiet','--collect','--no-block','--unit='+unit,
                    '--property=Type=exec','--property=User=root','--property=Group=root','--property=UMask=0077',
                    '--property=RuntimeMaxSec=5400','--property=KillMode=control-group',
                    '--property=ExecStopPost=/usr/bin/python3 -I -B '+str(HELPER)+' _cleanup --nonce '+nonce,
                    '--property=StandardOutput=null','--property=StandardError=null','--',
                    '/usr/bin/python3','-I','-B',str(HELPER),'_worker','--nonce',nonce])
        except Exception:job['state']='launch-failed';write_json(STATE/'job.json',job);raise
        return {'state':'queued','unit':unit,'source':SOURCE,'installer_executed':False}

def worker(nonce,runner=checked,loader=bundle):
    with locked():
        job=read_json(STATE/'job.json')
        if job.get('nonce')!=nonce or job.get('state')!='queued' or job.get('source')!=SOURCE:raise ValueError('Invalid or consumed task')
        job.update(state='running',updated=time.time());write_json(STATE/'job.json',job)
    try:
        source=loader();job['results']={}
        result=runner(['/usr/bin/python3','-I','-B',str(source/'professional/upgrade.py'),'apply','--source',str(source)],timeout=600)
        upgrade=json.loads(result)
        if upgrade.get('state')!='succeeded':raise ValueError('Overlay did not finish successfully')
        job.update(overlay_updated=True,phase='prerequisites',updated=time.time())
        job['results']['overlay']=upgrade;write_json(STATE/'job.json',job)
        if job['components']:
            args=['/usr/bin/python3','-I','-B',str(source/'professional/dependencies.py'),'--components',','.join(job['components'])]
            if job['admin_cidr']:args+=['--admin-cidr',job['admin_cidr']]
            result=json.loads(runner(args,timeout=4500))
            if result.get('state')!='succeeded':raise ValueError('Prerequisites did not finish')
            job['results']['prerequisites']=result
        runner(['/usr/bin/python3', '/usr/local/hestia/professional/health.py','--write','--installation-check'])
        job.update(state='succeeded',phase='local-verification',updated=time.time())
    except BaseException:
        job.update(state='failed',updated=time.time());raise
    finally:write_json(STATE/'job.json',job)
    return status()

def cleanup(nonce):
    """systemd calls this after stopping the task, including a killed package installer."""
    with locked():
        job=read_json(STATE/'job.json')
        if not isinstance(nonce,str) or job.get('nonce')!=nonce:raise ValueError('Foreign cleanup task')
        if POLICY.exists() and read_file(POLICY,secret=False,limit=4096)==TEMPORARY_POLICY:
            POLICY.unlink()
        if job.get('state') in ('queued','running'):
            job.update(state='interrupted-review',updated=time.time())
            write_json(STATE/'job.json',job)
    return status()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('plan','apply','status','_worker','_cleanup'))
    parser.add_argument('--components',default='backup,waf,docker,node')
    parser.add_argument('--admin-cidr');parser.add_argument('--nonce');args=parser.parse_args()
    if os.geteuid()!=0:raise ValueError('Root console required')
    if args.action=='status':result=status()
    elif args.action=='plan':
        source=bundle();result=inspect_plan(source)
        if result['state']=='ready':
            names=components(args.components);result['components']=names
            if 'waf' in names:result['admin_cidr']=cidr(args.admin_cidr)
    elif args.action=='apply':result=start(args.components,args.admin_cidr)
    elif args.action=='_worker':result=worker(args.nonce)
    else:result=cleanup(args.nonce)
    print(json.dumps(result,ensure_ascii=False))
    return 1 if result.get('state')=='blocked' else 0

if __name__=='__main__':
    try:sys.exit(main())
    except Exception as error:
        print(json.dumps({'state':'refused-or-failed','error':type(error).__name__,'reason':str(error)[:2000],
                          'message':'Confira os registros privados em /var/lib/hestia-professional-upgrade. Não execute o instalador novamente.'},ensure_ascii=False))
        sys.exit(1)

