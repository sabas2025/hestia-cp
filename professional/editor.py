#!/usr/bin/env python3
"""Account-scoped UTF-8 editor: descriptor walks, optimistic hashes, MFA and revisions."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import pwd
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
from business import account, record, regular
from mfa import operate as reauthenticate, root_json, event
from ops import lock, private_read, private_directory, require_root, safe_environment, username

LIMIT = 262144
EXTENSIONS = {'.php','.phtml','.js','.mjs','.cjs','.json','.html','.htm','.css','.scss','.txt','.md','.xml','.svg','.yml','.yaml','.sql','.ini','.conf','.toml'}

def authorize(root, actor, owner):
    actor_data = account(root,actor);account(root,owner,target=True)
    if actor!=owner and actor_data.get('ROLE')!='admin': raise ValueError('Foreign workspace')

def relative(value, directory=False):
    if not isinstance(value,str) or len(value)>512 or '\\' in value or any(ord(c)<32 for c in value): raise ValueError('Invalid path')
    p = PurePosixPath(value)
    if p.is_absolute() or '..' in p.parts or any(x.startswith('.') and x!='.htaccess' for x in p.parts): raise ValueError('Invalid path')
    if not directory and (not p.parts or (p.name!='.htaccess' and p.suffix.lower() not in EXTENSIONS)): raise ValueError('Unsupported text file')
    return p

def workspace(root, owner, name, home=Path('/home'), lookup=pwd.getpwnam):
    username(owner);values = record(root,owner,'web',name);name = values['DOMAIN']
    user = lookup(owner)
    if user.pw_uid<1000: raise ValueError('Application account required')
    return home/owner/'web'/name/'public_html',user

def directory_fd(base, path):
    """Never resolve a user-controlled link; keep each parent pinned by an fd."""
    fd = os.open('/',os.O_RDONLY|os.O_DIRECTORY)
    try:
        for index,part in enumerate((*base.parts[1:], *path.parts)):
            new = os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
            os.close(fd);fd = new
            info = os.fstat(fd)
            trusted_sticky_ancestor = index<len(base.parts)-2 and info.st_uid==0 and info.st_mode & stat.S_ISVTX
            if info.st_mode & 0o002 and not trusted_sticky_ancestor: raise ValueError('World-writable workspace')
        return fd
    except BaseException: os.close(fd);raise

def read_at(fd, name, uid):
    try: file = os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
    except FileNotFoundError:return None,None
    try:
        info = os.fstat(file)
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=uid or info.st_nlink!=1 or info.st_size>LIMIT or info.st_mode & 0o002:
            raise ValueError('Unsafe or oversized file')
        with os.fdopen(file,'rb',closefd=False) as stream:data = stream.read(LIMIT+1)
        if len(data)>LIMIT or b'\0' in data:raise ValueError('Not a bounded text file')
        data.decode('utf-8');return data,info
    finally:os.close(file)

def digest(data):return None if data is None else hashlib.sha256(data).hexdigest()

def trim_revisions(root,owner):
    """Bound private source copies to 50 successful recent saves per account."""
    files=sorted((root/'data/professional-editor/revisions').glob('*.json'),key=lambda p:p.stat().st_mtime,reverse=True)
    count=0
    for path in files:
        old=json.loads(private_read(path,2097152))
        if old.get('owner')==owner:
            count+=1
            if count>50:path.unlink()

def browse(root, actor, owner, name, path='', home=Path('/home'), lookup=pwd.getpwnam):
    authorize(root,actor,owner);base,user = workspace(root,owner,name,home,lookup)
    relative_path = relative(path,directory=True);fd = directory_fd(base,relative_path)
    try:
        result = []
        for entry in sorted(os.scandir(fd),key=lambda e:e.name):
            if len(result)>=200:break
            try:
                item = relative(str(relative_path/entry.name),directory=True)
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISLNK(info.st_mode) or info.st_uid!=user.pw_uid:continue
                if entry.is_dir(follow_symlinks=False):kind = 'directory'
                elif entry.is_file(follow_symlinks=False) and info.st_nlink==1 and info.st_size<=LIMIT:
                    relative(str(item));kind = 'file'
                else:continue
                result.append({'name':entry.name,'path':str(item),'type':kind,'bytes':info.st_size})
            except (OSError,ValueError):continue
        return {'owner':owner,'domain':name,'path':path,'entries':result,'limit':200}
    finally:os.close(fd)

def read(root, actor, owner, name, path, home=Path('/home'), lookup=pwd.getpwnam):
    authorize(root,actor,owner);base,user = workspace(root,owner,name,home,lookup);p = relative(path)
    fd = directory_fd(base,p.parent)
    try:data,info = read_at(fd,p.name,user.pw_uid)
    finally:os.close(fd)
    if data is None:raise ValueError('File unavailable')
    return {'owner':owner,'domain':name,'path':str(p),'content':data.decode(),'sha256':digest(data),'bytes':len(data)}

def validate_text(stage, path, data, runner=subprocess.run):
    if len(data)>LIMIT or b'\0' in data:raise ValueError('Not a bounded text file')
    data.decode('utf-8');checks = ['utf-8']
    if path.suffix.lower()=='.json':json.loads(data);checks.append('json')
    if path.suffix.lower() in ('.php','.phtml'):
        binary = shutil.which('php8.4') or shutil.which('php')
        if not binary:raise ValueError('PHP syntax checker unavailable')
        temporary = stage/'syntax.php';temporary.write_bytes(data);temporary.chmod(0o600)
        result = runner([binary,'-n','-l',str(temporary)],env=safe_environment(),stdin=subprocess.DEVNULL,
                        capture_output=True,timeout=15)
        if result.returncode:raise ValueError('PHP syntax check failed')
        checks.append('php-lint')
    return checks

def save(root, actor, owner, name, path, content, expected, home=Path('/home'), lookup=pwd.getpwnam):
    authorize(root,actor,owner)
    if not isinstance(content,str) or not (expected=='absent' or isinstance(expected,str) and re.fullmatch(r'[a-f0-9]{64}',expected)):
        raise ValueError('Content and previous hash required')
    data = content.encode();base,user = workspace(root,owner,name,home,lookup);p = relative(path)
    folder = private_directory(root/'data/professional-editor',0o700)
    if shutil.disk_usage(folder).free<134217728:raise ValueError('Insufficient space for revision and replacement')
    key = hashlib.sha256((owner+'/'+name+'/'+str(p)).encode()).hexdigest()
    with lock(folder/'locks'/(owner+'-revisions')),lock(folder/'locks'/key):
        fd = directory_fd(base,p.parent);temporary = None
        try:
            old,info = read_at(fd,p.name,user.pw_uid)
            if (old is None and expected!='absent') or (old is not None and digest(old)!=expected):raise ValueError('File changed; reload before saving')
            with tempfile.TemporaryDirectory(prefix='lint-',dir=folder) as stage:
                checks = validate_text(Path(stage),p,data)
            ident = secrets.token_hex(16)
            revision = {'id':ident,'owner':owner,'domain':name,'path':str(p),'previous':None if old is None else base64.b64encode(old).decode(),
                        'before':digest(old),'after':digest(data),'mode':info.st_mode & 0o777 if info else 0o644}
            root_json(folder/'revisions'/(ident+'.json'),revision)
            temporary = '.hestia-editor-'+secrets.token_hex(16)
            new = os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=fd)
            with os.fdopen(new,'wb') as stream:
                stream.write(data);stream.flush();os.fsync(stream.fileno())
                os.fchown(stream.fileno(),user.pw_uid,user.pw_gid);os.fchmod(stream.fileno(),revision['mode'])
            current,current_info = read_at(fd,p.name,user.pw_uid)
            if digest(current)!=digest(old) or (info and current_info and current_info.st_ino!=info.st_ino):raise ValueError('Concurrent edit detected')
            os.replace(temporary,p.name,src_dir_fd=fd,dst_dir_fd=fd);temporary = None;os.fsync(fd)
            event(folder,actor,'editor-save','completed')
            trim_revisions(root,owner)
            return {'state':'saved','revision':ident,'sha256':digest(data),'checks':checks,'path':str(p)}
        finally:
            if temporary:
                try:os.unlink(temporary,dir_fd=fd)
                except FileNotFoundError:pass
            os.close(fd)

def restore(root, actor, ident, home=Path('/home'), lookup=pwd.getpwnam):
    if not isinstance(ident,str) or not re.fullmatch(r'[a-f0-9]{32}',ident):raise ValueError('Invalid revision')
    old = json.loads(private_read(root/'data/professional-editor/revisions'/(ident+'.json'),2097152))
    authorize(root,actor,old['owner'])
    if old['previous'] is None:raise ValueError('Created files require explicit removal through account tools')
    content = base64.b64decode(old['previous'],validate=True).decode()
    if digest(content.encode())!=old['before']:raise ValueError('Revision checksum mismatch')
    return save(root,actor,old['owner'],old['domain'],old['path'],content,old['after'],home,lookup)

def history(root, actor, owner):
    authorize(root,actor,owner);result = []
    for path in sorted((root/'data/professional-editor/revisions').glob('*.json'),key=lambda p:p.stat().st_mtime,reverse=True)[:200]:
        data = json.loads(private_read(path,2097152))
        if data.get('owner')==owner:result.append({k:data[k] for k in ('id','domain','path','before','after')})
    return {'revisions':result}

def main():
    parser = argparse.ArgumentParser(description=__doc__);parser.add_argument('--actor',required=True)
    parser.add_argument('--op',choices=('domains','list','read','save','restore','history','files','download','rename','mkdir','upload-begin','upload-part','upload-commit','upload-cancel'),required=True)
    args = parser.parse_args();require_root();root = Path('/usr/local/hestia')
    raw = sys.stdin.read(2097153)
    if len(raw)>2097152:raise ValueError('Oversized request')
    request = json.loads(raw)
    if not isinstance(request,dict) or set(request)-{'owner','domain','path','content','sha256','revision','password','code','offset','etag','name','total','upload','data'}:raise ValueError('Invalid request')
    owner = request.get('owner',args.actor);authorize(root,args.actor,owner)
    import filemanager as fm
    if not fm.enabled(root):raise ValueError('File manager disabled by administrator')
    if args.op in ('save','restore','rename','mkdir','upload-begin','upload-part','upload-commit'):
        if not account(root,args.actor).get('TWOFA'):raise ValueError('Enable A2F first')
        from apply import verify_deployment
        if verify_deployment(root)['state']!='verified':raise ValueError('Deployment review required')
        if args.op not in ('upload-part','upload-commit'):
            reauthenticate(root,args.actor,'reauth',{'password':request.get('password',''),'code':request.get('code','')})
    if args.op=='domains':
        text = regular(root/'data/users'/owner/'web.conf') or b''
        names = re.findall(r"(?:^|\n)DOMAIN='([^'\r\n]+)'",text.decode())
        enabled = []
        for name in names:
            try:record(root,owner,'web',name);enabled.append(name)
            except ValueError:continue
        result = {'domains':enabled}
    elif args.op=='list':result = browse(root,args.actor,owner,request['domain'],request.get('path',''))
    elif args.op=='read':result = read(root,args.actor,owner,request['domain'],request['path'])
    elif args.op=='save':result = save(root,args.actor,owner,request['domain'],request['path'],request['content'],request['sha256'])
    elif args.op=='restore':result = restore(root,args.actor,request['revision'])
    elif args.op=='history':result = history(root,args.actor,owner)
    else:
        common=(root,args.actor,owner,request.get('domain',''),request.get('path',''))
        if args.op=='files':result=fm.listing(*common,offset=request.get('offset',0))
        elif args.op=='download':result=fm.download(*common,etag=request.get('etag'),offset=request.get('offset',0))
        elif args.op=='rename':result=fm.rename(*common,new_name=request.get('name'),etag=request.get('etag'))
        elif args.op=='mkdir':result=fm.mkdir(*common)
        elif args.op=='upload-begin':result=fm.begin(*common,total=request.get('total'),sha256=request.get('sha256'))
        elif args.op=='upload-part':result=fm.part(root,args.actor,request.get('upload'),request.get('offset'),request.get('data'))
        elif args.op=='upload-commit':result=fm.commit(root,args.actor,request.get('upload'))
        else:result=fm.cancel(root,args.actor,request.get('upload'))
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':
    try:main()
    except Exception:
        print('Editor operation refused. Check ownership, path, file hash, syntax and fresh A2F.',file=sys.stderr);sys.exit(1)
