#!/usr/bin/python3 -I
"""Restricted, root-only bootstrap for the audited Professional 1.2 source.

Console setup stores the password locally. SSH exposes plan/start/status only.
The installer runs in a systemd service with private logs, never in the SSH job.
"""
import argparse
import fcntl
import getpass
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import shutil
import socket
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
import zipfile
from contextlib import contextmanager

SOURCE = 'f974fbf852270d0f0b1d0a451b5dea0c409119b4'
SUMS_SHA256 = 'c056c0a984a7791585897038c58e5b7c497661902597f839d38954fec44864ab'
EXPECTED_FILES = 1697
APT_KEY_URL = 'https://apt.hestiacp.com/pubkey.gpg'
APT_KEY_SHA256 = '0020f1fb33bc0c53062a967b5c87fb51fd42550ab7ada15824cc1e4882b40dea'
APT_KEY_FINGERPRINT = '159F0BD6EC2656F183BFD07BA189E93654F0B0E5'
APT_KEYRING_SHA256 = 'd847beeefee5be7abd8e6372422c6cdf40df040c0dba8d631fd30863e75ad782'
OLD_KEYRING_SHA256 = 'd6513dc00832d51b0a3b4282c55b0497a463a7ac498682f29e04b05b22e2a363'
OLD_APT_ASSET = 'key-hestia\tbdb3e3d077a4dde7de5ed1c28c4311a6a86d8f0583f94d38f0a597ef8f3afbd3\thttps://raw.githubusercontent.com/hestiacp/hestiacp/c14350f40c71b71f36e3945e42607d7d9c4980eb/install/deb/deb_signing.key'
APT_ASSET = 'key-hestia\t'+APT_KEY_SHA256+'\t'+APT_KEY_URL
TARGET_IP = '179.197.72.245'
STATE = Path('/var/lib/hestia-github-deploy')
CONFIG = Path('/etc/hestia-github-deploy')
HELPER = Path('/usr/local/sbin/hestia-github-implantacao')
ROOT = Path('/usr/local/hestia')
KEY = Path('/root/.ssh/github-hestia-diagnostico.pub')
AUTHORIZED = Path('/root/.ssh/authorized_keys')
APT_KEYRING = Path('/usr/share/keyrings/hestia-keyring.gpg')
NATIVE_BACKUPS = Path('/root/hst_install_backups')
NATIVE_LOCK = Path('/run/hestia-professional/install.lock')
ENV = {'PATH':'/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
       'HOME':'/root','LC_ALL':'C','LANG':'C','TERM':'dumb','DEBIAN_FRONTEND':'noninteractive'}

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
    fd = os.open(STATE/'job.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
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
    if result.returncode: raise RuntimeError('Command failed; inspect private VPS log')
    return text

def valid_hostname(value):
    return isinstance(value,str) and len(value)<=253 and '.' in value and not re.fullmatch(r'[0-9.]+',value) and all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?',v) for v in value.split('.'))

def valid_password(value):
    return isinstance(value,str) and 14<=len(value)<=128 and not any(v in value for v in ('\n','\r','\0',':')) and not value.startswith('/tmp/') and all(re.search(r,value) for r in ('[A-Z]','[a-z]','[0-9]'))

def valid_username(value):
    reserved = {'root','sudo','mysql','hestiaweb','hestiamail','aria','aria_log','mysql_upgrade',
                'ib','ib_buffer','ddl','ddl_recovery','performance'}
    return isinstance(value,str) and bool(re.fullmatch(r'[a-z][a-z0-9_]{1,29}',value)) and value not in reserved

def settings():
    cfg = read_json(CONFIG/'config.json')
    if not isinstance(cfg,dict) or set(cfg)!={'hostname','email','username','source'} or cfg['source']!=SOURCE:
        raise ValueError('Invalid deployment configuration')
    if not valid_hostname(cfg['hostname']) or not isinstance(cfg['email'],str) or not re.fullmatch(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,63}',cfg['email']) or not valid_username(cfg['username']):
        raise ValueError('Invalid account settings')
    return cfg

def replace_authorization(old, public):
    fields = public.strip().split()
    if len(fields)<2 or fields[0]!='ssh-ed25519' or not re.fullmatch(r'[A-Za-z0-9+/=]{40,200}',fields[1]):
        raise ValueError('Dedicated Ed25519 public key required')
    key = fields[:2]; output = []
    for line in old.splitlines(keepends=True):
        parts = line.split()
        if any(parts[i:i+2]==key for i in range(max(0,len(parts)-1))): continue
        output.append(line)
    if output and not output[-1].endswith('\n'): output[-1]+='\n'
    output.append('restrict,command="'+str(HELPER)+'" '+' '.join(key)+' github-hestia-diagnostico\n')
    return ''.join(output)

def setup(hostname, email, reader=getpass.getpass, username='admin'):
    cfg = {'hostname':hostname,'email':email,'username':username,'source':SOURCE}
    if not valid_hostname(hostname) or not re.fullmatch(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,63}',email) or not valid_username(username):
        raise ValueError('Invalid hostname or email')
    with locked():
        if (CONFIG/'config.json').exists() or (STATE/'job.json').exists():
            raise ValueError('Setup already exists; preserve it and inspect status')
        public = read_file(KEY,secret=False,limit=4096).decode()
        checked(['/usr/bin/ssh-keygen','-l','-f',str(KEY)])
        old = read_file(AUTHORIZED,secret=False,limit=1048576).decode()
        replacement = replace_authorization(old,public)
        password = reader('Senha do administrador Hestia (14-128 caracteres): ')
        confirm = reader('Repita a senha: ')
        if password!=confirm or not valid_password(password): raise ValueError('Passwords must match, with upper/lowercase and digit; no colon or line break')
        private_dir(CONFIG)
        atomic(CONFIG/'admin-password',password.encode()); del password,confirm
        write_json(CONFIG/'config.json',cfg)
        atomic(CONFIG/('authorized_keys.before-'+str(int(time.time()))),old.encode())
        atomic(AUTHORIZED,replacement.encode())
    return {'state':'configured','source':SOURCE,'hostname':hostname,'username':username,'password_sent_to_github':False,
            'ssh_commands':['diagnostic','plan','start','status']}

def set_user(username, runner=checked):
    if not valid_username(username): raise ValueError('Invalid or reserved panel username')
    with locked():
        if (STATE/'job.json').exists() or ROOT.exists(): raise ValueError('Account changes require an installation that has not started')
        cfg = settings()
        for database in ('passwd','group'):
            try: runner(['/usr/bin/getent',database,username])
            except RuntimeError: continue
            raise ValueError('Selected account or group already exists')
        atomic(CONFIG/('config.before-user-'+secrets.token_hex(8)+'.json'),read_file(CONFIG/'config.json'))
        cfg['username'] = username;write_json(CONFIG/'config.json',cfg)
    return {'state':'configured','username':username,'password_preserved':True,
            'system_users_or_groups_modified':False,'installer_executed':False}

def verify_bundle(folder, sums_hash=SUMS_SHA256, expected=EXPECTED_FILES):
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
    if actual!=names or len(names)!=expected: raise ValueError('Unexpected source files')

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
    private_dir(STATE); target = STATE/'source'
    if target.exists(): verify_bundle(target); return target
    request = urllib.request.Request('https://codeload.github.com/sabas2025/hestia-cp/zip/'+SOURCE)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request,timeout=90) as response:
        if not response.geturl().startswith('https://codeload.github.com/'): raise ValueError('Unexpected source origin')
        data = response.read(52428801)
    with tempfile.TemporaryDirectory(prefix='source-',dir=STATE) as temporary:
        stage = Path(temporary)/'bundle';stage.mkdir(mode=0o700)
        unpack(data,stage);verify_bundle(stage);stage.rename(target)
    return target

def plan(resolver=socket.getaddrinfo, runner=checked, source_loader=bundle, netplan=Path('/etc/netplan')):
    cfg = settings(); source = source_loader(); reasons = []
    try:
        addresses = {item[4][0] for item in resolver(cfg['hostname'],8083,socket.AF_INET,socket.SOCK_STREAM)}
        if addresses!={TARGET_IP}: reasons.append('DNS A must point directly to '+TARGET_IP)
    except OSError: reasons.append('Hostname DNS A is not published')
    try:
        if resolver(cfg['hostname'],8083,socket.AF_INET6,socket.SOCK_STREAM): reasons.append('Review/remove AAAA until VPS IPv6 is validated')
    except OSError: pass
    password = read_file(CONFIG/'admin-password',limit=256).decode()
    if not valid_password(password): raise ValueError('Local password missing or invalid')
    del password
    try: runner(['/usr/bin/getent','passwd',cfg['username']]); reasons.append('Administrator user already exists: '+cfg['username'])
    except RuntimeError: pass
    try: runner(['/usr/bin/getent','group',cfg['username']]); reasons.append('Administrator group already exists: '+cfg['username'])
    except RuntimeError: pass
    try: native = runner(['/bin/bash',str(source/'install/hst-install.sh'),'--preflight'])
    except RuntimeError: native = ''; reasons.append('Native fresh-OS preflight blocked; inspect on VPS')
    if netplan.is_dir() and not any(p.is_file() for p in netplan.iterdir()): reasons.append('Empty Netplan requires networking review')
    return {'state':'blocked' if reasons else 'ready','source':SOURCE,'hostname':cfg['hostname'],'username':cfg['username'],
            'url':'https://'+cfg['hostname']+':8083','reasons':reasons,'preflight':native[-4096:],
            'installer_executed':False,'password_sent_to_github':False,
            'profile':'Nginx+Apache, PHP 8.4, MariaDB, DNS, email, native mail antivirus/antispam, Fail2Ban, resource limits; optional enterprise modules remain pending'}

def status():
    if not (STATE/'job.json').exists(): return {'state':'not-started','source':SOURCE}
    job = read_json(STATE/'job.json')
    # This public record is intentionally small; never return logs or configuration.
    result = {key:job[key] for key in ('state','id','phase','started','updated','source','hostname','username','url','unit') if key in job}
    if job['state']=='queued' and time.time()-job['started']>300: result['state']='queue-expired'
    if job['state']=='running' and time.time()-job['started']>5400: result['state']='interrupted-review'
    return result

def start(runner=checked, planner=plan):
    with locked():
        if (STATE/'job.json').exists(): raise ValueError('An installation is already recorded; inspect status and recover manually')
        result = planner()
        if result['state']!='ready': return result
        ident = secrets.token_hex(16);unit = 'hestia-install-'+ident
        job = {'state':'queued','id':ident,'phase':'waiting-for-worker','started':time.time(),'updated':time.time(),
               'source':SOURCE,'hostname':result['hostname'],'username':settings()['username'],'url':result['url'],'unit':unit}
        write_json(STATE/'job.json',job)
        try:
            runner(['/usr/bin/systemd-run','--quiet','--collect','--unit='+unit,'--property=Type=exec',
                    '--property=User=root','--property=Group=root','--property=UMask=0077',
                    '--property=RuntimeMaxSec=5400','--property=KillMode=control-group',
                    '--property=StandardOutput=null','--property=StandardError=null','--',
                    '/usr/bin/python3','-I',str(HELPER),'worker',ident])
        except Exception:
            job.update(state='launch-failed',updated=time.time());write_json(STATE/'job.json',job);raise
    # Return the accepted ticket, even if the worker already changed its state.
    return job

def installer_args(source, cfg):
    return ['/bin/bash',str(source/'install/hst-install.sh'),'--apply','--interactive','no',
            '--hostname',cfg['hostname'],'--email',cfg['email'],'--username',cfg['username'],
            '--password-file',str(CONFIG/'admin-password'),'--lang','pt-br','--port','8083',
            '--apache','yes','--phpfpm','yes','--multiphp','8.4','--mysql','yes',
            '--named','yes','--exim','yes','--dovecot','yes','--sieve','yes',
            '--clamav','yes','--spamassassin','yes','--fail2ban','yes','--iptables','yes',
            '--resourcelimit','yes','--vsftpd','no','--proftpd','no','--webterminal','no']

def suppress_welcome_email(source):
    path = source/'install/hst-install-ubuntu.sh';body = path.read_text()
    line = 'cat $tmpfile | $send_mail -s "Hestia Control Panel" $email'
    if body.count(line)!=1: raise ValueError('Installer notification contract changed')
    path.write_text(body.replace(line,'# GitHub bootstrap: outbound welcome message disabled; credentials remain local.'))

def correct_apt_asset(source):
    # Only the verified working copy changes; keep the original source intact.
    path = source/'install/assets.lock.tsv';body = path.read_text()
    if body.splitlines().count(OLD_APT_ASSET)!=1 or any(line.startswith('key-hestia\t') and line!=OLD_APT_ASSET for line in body.splitlines()):
        raise ValueError('Installer APT trust contract changed')
    path.write_text(body.replace(OLD_APT_ASSET+'\n',APT_ASSET+'\n'))

@contextmanager
def native_install_lock():
    private_dir(NATIVE_LOCK.parent)
    fd = os.open(controlled(NATIVE_LOCK),os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:
        s = os.fstat(fd)
        if s.st_uid!=0 or not stat.S_ISREG(s.st_mode) or s.st_nlink!=1 or s.st_mode & 0o077:
            raise ValueError('Unsafe native install lock')
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);yield
    finally: os.close(fd)

def replace_keyring(data):
    # Do not use atomic(): /usr/share/keyrings must retain its public directory mode.
    controlled(APT_KEYRING)
    fd,name = tempfile.mkstemp(prefix='.hestia-recovery-',dir=APT_KEYRING.parent)
    try:
        with os.fdopen(fd,'wb') as stream:
            stream.write(data);stream.flush();os.fsync(stream.fileno());os.fchmod(stream.fileno(),0o644)
        os.replace(name,APT_KEYRING)
    finally:
        if os.path.exists(name): os.unlink(name)

def apt_failure_evidence(job, cfg):
    if job.get('state')!='failed' or job.get('phase')!='installing' or any(job.get(k)!=cfg[k] for k in ('source','hostname','username')):
        raise ValueError('Recovery only supports a failed first installation at repository refresh')
    ident = job.get('id','')
    if not re.fullmatch(r'[a-f0-9]{32}',ident) or job.get('unit')!='hestia-install-'+ident:
        raise ValueError('Unexpected installation ticket')
    output = read_file(STATE/'installation.log').decode()
    matches = re.findall(r'^ERROR: Refresh package indexes failed \(status 100\); see (/root/hst_install_backups/(hst_install-[0-9]{8}T[0-9]{6}Z-[0-9]+\.log))$',output,re.M)
    if len(matches)!=1: raise ValueError('Repository failure not identified')
    path = NATIVE_BACKUPS/matches[0][1];raw = read_file(path)
    text = raw.decode()
    events = re.findall(r'^\S+ ((?:START|END) .+)$',text,re.M)
    expected = ['START Refresh package indexes','END Refresh package indexes status=0',
                'START Install bootstrap dependencies','END Install bootstrap dependencies status=0',
                'START Refresh package indexes','END Refresh package indexes status=100']
    if events!=expected or not text.rstrip().endswith(expected[-1]) or 'NO_PUBKEY A189E93654F0B0E5' not in text or 'https://apt.hestiacp.com' not in text:
        raise ValueError('Later, incomplete or different installation requires manual review')
    return path,raw

def recover_apt_key(reader=getpass.getpass, runner=checked, planner=plan, source_loader=bundle):
    with locked(),native_install_lock():
        cfg = settings();job = read_json(STATE/'job.json')
        native_path,native_log = apt_failure_evidence(job,cfg)
        if ROOT.exists() or (CONFIG/'admin-password').exists(): raise ValueError('Existing panel or pending credential requires review')
        # list-units returns success even after --collect has unloaded the service.
        unit = job['unit']+'.service'
        state = runner(['/usr/bin/systemctl','list-units','--all','--no-pager','--no-legend','--plain',unit]).strip()
        rows = [line.split() for line in state.splitlines()]
        if rows and (len(rows)!=1 or len(rows[0])<4 or rows[0][0]!=unit or rows[0][2] not in ('inactive','failed')):
            raise ValueError('Installation service is still active or unknown')
        original = source_loader()
        runner(['/bin/bash',str(original/'install/hst-install.sh'),'--preflight'])
        old = read_file(APT_KEYRING,secret=False)
        if hashlib.sha256(old).hexdigest() not in (OLD_KEYRING_SHA256,APT_KEYRING_SHA256):
            raise ValueError('Unrecognized keyring; preserve it for manual review')
        for name in ('job.json','installation.log','configuration-before.tar.gz','working'):
            if not controlled(STATE/name).exists(): raise ValueError('Missing recovery evidence')
        history = private_dir(STATE/'history')/('apt-key-'+job['id']+'-'+secrets.token_hex(8))
        private_dir(history);atomic(history/'native-installation.log',native_log)
        atomic(history/'keyring-before.gpg',old)
        record = {'state':'preparing','phase':'verify-official-key','previous_job':job['id'],'source':SOURCE,'native_log':str(native_path),
                  'fingerprint':APT_KEY_FINGERPRINT,'installer_executed':False,'created':time.time()}
        write_json(history/'recovery.json',record)
        moved = [];password_created = False;key_changed = False
        try:
            with tempfile.TemporaryDirectory(prefix='trust-',dir=history) as tmp:
                stage = Path(tmp);key = stage/'pubkey';keyring = stage/'keyring.gpg';home = private_dir(stage/'gnupg')
                runner(['/usr/bin/curl','--fail','--silent','--show-error','--proto','=https','--connect-timeout','10','--max-time','60','--output',str(key),APT_KEY_URL],timeout=70)
                if hashlib.sha256(read_file(key,secret=False)).hexdigest()!=APT_KEY_SHA256: raise ValueError('Official repository key checksum changed')
                details = runner(['/usr/bin/gpg','--homedir',str(home),'--batch','--show-keys','--with-colons','--fingerprint',str(key)])
                fingerprints = [line.split(':')[9] for line in details.splitlines() if line.startswith('fpr:')]
                if not fingerprints or fingerprints[0]!=APT_KEY_FINGERPRINT or sum(line.startswith('pub:') for line in details.splitlines())!=1:
                    raise ValueError('Unexpected repository signing key')
                runner(['/usr/bin/gpg','--homedir',str(home),'--batch','--yes','--dearmor','--output',str(keyring),str(key)])
                data = read_file(keyring,secret=False)
                if hashlib.sha256(data).hexdigest()!=APT_KEYRING_SHA256: raise ValueError('Unexpected keyring encoding')
                replace_keyring(data);key_changed = True
            record.update(phase='authenticated-apt-update');write_json(history/'recovery.json',record)
            fd = os.open(history/'apt-update.log',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
            with os.fdopen(fd,'wb') as log: runner(['/usr/bin/apt-get','-o','APT::Update::Error-Mode=any','update'],timeout=300,log=log)
            record.update(phase='local-password');write_json(history/'recovery.json',record)
            password = reader('Senha do administrador Hestia (14-128 caracteres): ')
            confirm = reader('Repita a senha: ')
            if password!=confirm or not valid_password(password): raise ValueError('Invalid or mismatched local password')
            atomic(CONFIG/'admin-password',password.encode());password_created = True;del password,confirm
            record.update(phase='fresh-installation-plan');write_json(history/'recovery.json',record)
            result = planner()
            if result['state']!='ready': raise ValueError('Fresh installation plan is blocked')
            record.update(phase='archive-failed-attempt');write_json(history/'recovery.json',record)
            # Move the ticket last. A partial archive is rolled back on ordinary errors.
            for name in ('working','installation.log','configuration-before.tar.gz','job.json'):
                (STATE/name).rename(history/name);moved.append(name)
            record.update(state='recovered',phase='ready-for-new-plan',updated=time.time());write_json(history/'recovery.json',record)
        except BaseException:
            for name in reversed(moved): (history/name).rename(STATE/name)
            if password_created: controlled(CONFIG/'admin-password').unlink()
            if key_changed: replace_keyring(old)
            record.update(state='failed',updated=time.time());write_json(history/'recovery.json',record);raise
    return {'state':'recovered','username':cfg['username'],'history':str(history),'apt_signature_check':'passed',
            'installer_executed':False,'password_sent_to_github':False,'next':'plan, then start'}

def backup_configuration(archive_path):
    fd = os.open(archive_path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb') as stream,tarfile.open(fileobj=stream,mode='w:gz') as archive:
        for path in ('/etc/ssh','/etc/netplan','/etc/apt','/etc/hostname','/etc/hosts','/etc/resolv.conf'):
            if Path(path).exists() or Path(path).is_symlink(): archive.add(path,arcname=path.lstrip('/'))

def worker(ident, runner=checked, planner=plan, source_loader=bundle):
    if not re.fullmatch(r'[a-f0-9]{32}',ident): raise ValueError('Invalid installation id')
    with locked():
        job = read_json(STATE/'job.json')
        if job['id']!=ident or job['state']!='queued' or time.time()-job['started']>300:
            raise ValueError('Installation ticket expired or consumed')
        cfg = settings()
        def phase(name):
            job.update(state='running',phase=name,updated=time.time());write_json(STATE/'job.json',job)
        try:
            phase('preflight')
            if planner()['state']!='ready': raise ValueError('Preflight changed')
            original = source_loader();working = STATE/'working'
            if working.exists(): raise ValueError('Existing workspace requires manual review')
            shutil.copytree(original,working);suppress_welcome_email(working);correct_apt_asset(working)
            phase('backup-configuration')
            backup_configuration(STATE/'configuration-before.tar.gz')
            phase('installing')
            fd = os.open(STATE/'installation.log',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
            with os.fdopen(fd,'wb') as log:
                runner(installer_args(working,cfg),timeout=5000,log=log)
                phase('validating')
                raw = runner(['/usr/bin/python3',str(ROOT/'professional/apply.py'),'--root',str(ROOT),'--source',str(ROOT),'--refresh'])
                if json.loads(raw).get('status')!='verified': raise ValueError('Installed manifest is not verified')
                runner(['/usr/bin/python3',str(ROOT/'professional/health.py'),'--installation-check'],log=log)
                runner(['/usr/bin/systemctl','is-active','--quiet','hestia'])
                with socket.create_connection(('127.0.0.1',8083),timeout=5): pass
            job.update(state='succeeded',phase='configuration-and-listener-verified',updated=time.time())
        except Exception:
            job.update(state='failed',updated=time.time());raise
        finally:
            password = CONFIG/'admin-password'
            try:
                if password.exists(): controlled(password).unlink()
            except Exception:
                job.update(state='failed',phase='credential-cleanup',updated=time.time())
                write_json(STATE/'job.json',job);raise
            write_json(STATE/'job.json',job)
    return status()

def ssh_action(original):
    mapping = {str(HELPER)+' '+v:v for v in ('plan','start','status')}
    mapping['/usr/local/sbin/hestia-github-diagnostico'] = 'diagnostic'
    if original not in mapping: raise ValueError('SSH command refused')
    return mapping[original]

def main():
    if os.geteuid()!=0: raise ValueError('Run as root')
    os.umask(0o077)
    if 'SSH_ORIGINAL_COMMAND' in os.environ:
        if len(sys.argv)!=1: raise ValueError('Forced SSH command takes no direct arguments')
        action = ssh_action(os.environ.get('SSH_ORIGINAL_COMMAND',''));args = None
    else:
        parser = argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=('setup','set-user','recover-apt-key','plan','start','status','worker'))
        parser.add_argument('id',nargs='?');parser.add_argument('--hostname');parser.add_argument('--email');parser.add_argument('--username');args = parser.parse_args();action = args.action
    if action=='diagnostic':
        os.execve('/usr/local/sbin/hestia-github-diagnostico',['hestia-github-diagnostico'],ENV)
    if action=='setup': result = setup(args.hostname,args.email,username=args.username or 'admin')
    elif action=='set-user': result = set_user(args.username)
    elif action=='recover-apt-key':
        if not sys.stdin.isatty(): raise ValueError('Recovery requires the interactive root console')
        result = recover_apt_key()
    elif action=='plan': result = plan()
    elif action=='start': result = start()
    elif action=='worker': result = worker(args.id or '')
    else: result = status()
    print(json.dumps(result));return 1 if action in ('plan','start') and result.get('state') in ('blocked','failed','launch-failed') else 0

if __name__=='__main__':
    try:sys.exit(main())
    except Exception:
        print(json.dumps({'state':'refused','message':'Confira DNS, configuração local, estado e log privado na VPS. Não há reinstalação automática.'}));sys.exit(1)
