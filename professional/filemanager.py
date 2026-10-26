#!/usr/bin/env python3
"""Domain file operations; uploads are bounded, private, single-use capabilities."""
import base64
import ctypes
import errno
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import shutil
import stat
import time
import editor
from mfa import event, root_json
from ops import lock, private_directory, private_read

CHUNK = 262144
MAX_FILE = 67108864
TTL = 900

def enabled(root):
    raw=editor.regular(root/'data/professional-filemanager/policy.json',4096)
    if raw is None:return True
    value=json.loads(raw)
    if not isinstance(value,dict) or set(value)!={'schema','enabled'} or value['schema']!=1 or type(value['enabled']) is not bool:raise ValueError('Invalid file manager policy')
    return value['enabled']

def path(value, directory=False):
    # Preserve the editor's private-dotfile policy; arbitrary binary extensions
    # are permitted only in this account's public document tree.
    p = editor.relative(value, directory=True)
    if not directory and not p.parts: raise ValueError('File name required')
    if any(len(part.encode())>255 or part.startswith('.hestia-') for part in p.parts): raise ValueError('Invalid name')
    return p

def scope(root, actor, owner, domain, value, home, lookup, directory=False):
    editor.authorize(root,actor,owner)
    base,user = editor.workspace(root,owner,domain,home,lookup)
    p = path(value,directory)
    fd = editor.directory_fd(base,p if directory else p.parent)
    info = os.fstat(fd)
    if info.st_uid!=user.pw_uid or info.st_mode & 0o022:
        os.close(fd);raise ValueError('Directory must be controlled by the account')
    return fd,p,user

def version(info):
    return hashlib.sha256(repr((info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns)).encode()).hexdigest()

def checked_file(fd,name,uid):
    handle = os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
    info = os.fstat(handle)
    if not stat.S_ISREG(info.st_mode) or info.st_uid!=uid or info.st_nlink!=1 or info.st_mode & 0o002:
        os.close(handle);raise ValueError('Unsafe file')
    return handle,info

def listing(root,actor,owner,domain,value='',offset=0,home=Path('/home'),lookup=editor.pwd.getpwnam):
    if type(offset) is not int or offset<0 or offset>10000:raise ValueError('Invalid page')
    fd,p,user = scope(root,actor,owner,domain,value,home,lookup,True)
    try:
        entries=[]
        with os.scandir(fd) as scan:
            for scanned,entry in enumerate(scan):
                if scanned>=10000:raise ValueError('Directory too large; use SSH for this folder')
                try:
                    item=path(str(p/entry.name));info=entry.stat(follow_symlinks=False)
                    if info.st_uid!=user.pw_uid or info.st_mode & 0o002:continue
                    kind='directory' if stat.S_ISDIR(info.st_mode) else 'file' if stat.S_ISREG(info.st_mode) and info.st_nlink==1 else None
                    if kind is None:continue
                    try:editor.relative(str(item));editable=kind=='file' and info.st_size<=editor.LIMIT
                    except ValueError:editable=False
                    entries.append({'name':entry.name,'path':str(item),'type':kind,'bytes':info.st_size,
                                    'modified':int(info.st_mtime),'etag':version(info),'editable':editable,
                                    'downloadable':kind=='file' and info.st_size<=MAX_FILE})
                except (OSError,ValueError,UnicodeError):continue
        entries.sort(key=lambda item:(item['type']!='directory',item['name'].casefold(),item['name']))
        return {'path':str(p) if p.parts else '', 'entries':entries[offset:offset+100], 'total':len(entries),
                'offset':offset,'next':offset+100 if offset+100<len(entries) else None,'limit':100,'max_file':MAX_FILE}
    finally:os.close(fd)

def download(root,actor,owner,domain,value,etag,offset,home=Path('/home'),lookup=editor.pwd.getpwnam):
    if type(offset) is not int or offset<0 or not isinstance(etag,str):raise ValueError('Invalid range')
    fd,p,user=scope(root,actor,owner,domain,value,home,lookup)
    try:
        file,info=checked_file(fd,p.name,user.pw_uid)
        try:
            if info.st_size>MAX_FILE or offset>info.st_size or version(info)!=etag:raise ValueError('File changed or exceeds download limit')
            os.lseek(file,offset,os.SEEK_SET);data=os.read(file,CHUNK)
            if version(os.fstat(file))!=etag:raise ValueError('File changed during download')
            return {'data':base64.b64encode(data).decode(),'offset':offset,'total':info.st_size,'etag':etag,'eof':offset+len(data)==info.st_size}
        finally:os.close(file)
    finally:os.close(fd)

def rename_no_replace(srcfd,src,dstfd,dst):
    # Linux atomic no-clobber rename; fail closed if the primitive is absent.
    libc=ctypes.CDLL(None,use_errno=True)
    rename=getattr(libc,'renameat2',None)
    if rename is None:raise ValueError('Atomic rename unavailable')
    rename.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint]
    rename.restype=ctypes.c_int
    if rename(srcfd,os.fsencode(src),dstfd,os.fsencode(dst),1)!=0:
        code=ctypes.get_errno();raise OSError(code,os.strerror(code))

def rename(root,actor,owner,domain,value,new_name,etag,home=Path('/home'),lookup=editor.pwd.getpwnam):
    target=path(new_name)
    if len(target.parts)!=1:raise ValueError('Rename requires one file name')
    folder=private_directory(root/'data/professional-editor',0o700)
    with lock(folder/'locks'/(owner+'-revisions')):
        fd,p,user=scope(root,actor,owner,domain,value,home,lookup)
        try:
            file,info=checked_file(fd,p.name,user.pw_uid)
            try:
                if version(info)!=etag:raise ValueError('File changed; reload')
                rename_no_replace(fd,p.name,fd,target.name);os.fsync(fd)
            finally:os.close(file)
            event(folder,actor,'file-rename','completed')
            return {'state':'renamed','path':str(p.parent/target),'etag':version(os.stat(target.name,dir_fd=fd,follow_symlinks=False))}
        finally:os.close(fd)

def mkdir(root,actor,owner,domain,value,home=Path('/home'),lookup=editor.pwd.getpwnam):
    fd,p,user=scope(root,actor,owner,domain,value,home,lookup)
    try:
        # Create as the account, so a race swapping a directory cannot turn a
        # privileged chmod/chown into access to a different protected directory.
        child=os.fork()
        if child==0:
            try:
                if user.pw_uid!=os.geteuid():
                    os.setgroups([]);os.setgid(user.pw_gid);os.setuid(user.pw_uid)
                os.umask(0o022);os.mkdir(p.name,0o755,dir_fd=fd);os._exit(0)
            except BaseException:os._exit(1)
        _,status=os.waitpid(child,0)
        if status!=0:raise ValueError('Directory creation refused')
        os.fsync(fd);event(private_directory(root/'data/professional-editor',0o700),actor,'file-mkdir','completed')
        return {'state':'created','path':str(p)}
    finally:os.close(fd)

def uploads(root):return private_directory(root/'data/professional-editor/uploads',0o700)

def ticket(folder,ident,actor):
    if not isinstance(ident,str) or not re.fullmatch('[a-f0-9]{32}',ident):raise ValueError('Invalid upload')
    data=json.loads(private_read(folder/(ident+'.json')))
    if data['actor']!=actor or data['expires']<time.time():raise ValueError('Upload unavailable or expired')
    return data

def discard(folder,ident):
    for suffix in ('.bin','.json'):(folder/(ident+suffix)).unlink(missing_ok=True)

def staged_bytes(folder,ident):
    file=os.open(folder/(ident+'.bin'),os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        info=os.fstat(file)
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_nlink!=1 or info.st_mode&0o077 or info.st_size>MAX_FILE:
            raise ValueError('Unsafe upload staging')
        with os.fdopen(file,'rb',closefd=False) as stream:raw=stream.read(MAX_FILE+1)
        if len(raw)>MAX_FILE:raise ValueError('Upload too large')
        return raw
    finally:os.close(file)

def begin(root,actor,owner,domain,value,total,sha256,home=Path('/home'),lookup=editor.pwd.getpwnam):
    if type(total) is not int or not 0<=total<=MAX_FILE or not isinstance(sha256,str) or not re.fullmatch('[a-f0-9]{64}',sha256):raise ValueError('Invalid upload size/hash')
    fd,p,_=scope(root,actor,owner,domain,value,home,lookup)
    try:
        try:os.stat(p.name,dir_fd=fd,follow_symlinks=False)
        except FileNotFoundError:pass
        else:raise ValueError('Destination already exists')
    finally:os.close(fd)
    folder=uploads(root)
    with lock(folder/'queue.lock'):
        active=[]
        for f in folder.glob('*.json'):
            item=json.loads(private_read(f))
            if item['expires']<time.time():discard(folder,f.stem)
            else:active.append(item)
        if len(active)>=8 or sum(item['owner']==owner for item in active)>=2:raise ValueError('Upload queue full')
        if shutil.disk_usage(folder).free<2*total+134217728:raise ValueError('Insufficient disk space')
        ident=secrets.token_hex(16)
        data={'id':ident,'actor':actor,'owner':owner,'domain':domain,'path':str(p),'total':total,'received':0,'sha256':sha256,'expires':time.time()+TTL}
        try:
            handle=os.open(folder/(ident+'.bin'),os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600);os.close(handle)
            root_json(folder/(ident+'.json'),data)
        except BaseException:discard(folder,ident);raise
        return {'upload':ident,'chunk_bytes':CHUNK,'expires_in':TTL}

def part(root,actor,ident,offset,encoded):
    folder=uploads(root)
    with lock(folder/'queue.lock'):
        data=ticket(folder,ident,actor);editor.authorize(root,actor,data['owner'])
        if type(offset) is not int or offset!=data['received'] or not isinstance(encoded,str) or len(encoded)>4*((CHUNK+2)//3):raise ValueError('Invalid upload chunk')
        raw=base64.b64decode(encoded,validate=True)
        if not raw or len(raw)>CHUNK or offset+len(raw)>data['total']:raise ValueError('Invalid upload chunk')
        file=os.open(folder/(ident+'.bin'),os.O_WRONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        try:
            info=os.fstat(file)
            if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_nlink!=1 or info.st_mode&0o077 or info.st_size!=offset:raise ValueError('Unsafe upload staging')
            with os.fdopen(file,'r+b',closefd=False) as stream:
                stream.seek(offset);stream.write(raw);stream.flush();os.fsync(file)
            data['received']+=len(raw);root_json(folder/(ident+'.json'),data)
        finally:os.close(file)
        return {'received':data['received']}

def commit(root,actor,ident,home=Path('/home'),lookup=editor.pwd.getpwnam):
    folder=uploads(root)
    with lock(folder/'queue.lock'):
        data=ticket(folder,ident,actor)
        with lock(folder.parent/'locks'/(data['owner']+'-revisions')):
            if data['received']!=data['total']:raise ValueError('Upload incomplete')
            # Private bounded staging is never a web-accessible temporary file.
            raw=staged_bytes(folder,ident)
            if len(raw)!=data['total'] or hashlib.sha256(raw).hexdigest()!=data['sha256']:raise ValueError('Upload checksum mismatch')
            fd,p,user=scope(root,actor,data['owner'],data['domain'],data['path'],home,lookup)
            temporary='.hestia-upload-'+secrets.token_hex(16)
            try:
                handle=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=fd)
                with os.fdopen(handle,'wb') as stream:
                    stream.write(raw);stream.flush();os.fsync(stream.fileno())
                    os.fchown(stream.fileno(),user.pw_uid,user.pw_gid);os.fchmod(stream.fileno(),0o644)
                # Keep the partial file unreadable by the web service until all
                # bytes are durable. Publish without replacing an existing name.
                rename_no_replace(fd,temporary,fd,p.name);temporary=None;os.fsync(fd)
                discard(folder,ident);event(folder.parent,actor,'file-upload','completed')
                return {'state':'uploaded','path':str(p),'bytes':len(raw),'sha256':data['sha256']}
            finally:
                if temporary:
                    try:os.unlink(temporary,dir_fd=fd)
                    except FileNotFoundError:pass
                os.close(fd)

def cancel(root,actor,ident):
    folder=uploads(root)
    with lock(folder/'queue.lock'):
        ticket(folder,ident,actor);discard(folder,ident)
    return {'state':'cancelled'}
