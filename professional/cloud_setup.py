#!/usr/bin/env python3
"""Register an already authorized, private rclone remote. Never initialize or prune."""
import argparse
import configparser
import getpass
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import warnings
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ops import private_read, private_directory, lock, require_root, safe_environment
from mfa import root_json
from cloud_backup import identifier, settings
from business import regular

PROVIDERS = ('google-drive', 'amazon-s3', 'private-s3', 'ftps', 'ftp', 'sftp')
ROOT = Path('/usr/local/hestia')
CONFIG = Path('/etc/hestiacp/professional/cloud-backup.json')

def run(args):
    result = subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True,
                            env=safe_environment(), timeout=45)
    if result.returncode: raise RuntimeError('Connection or service inspection failed')
    return result.stdout.decode(errors='replace')

def idle(root, runner):
    units = runner(['/usr/bin/systemctl','list-units','--all','--plain','--no-legend',
                    '--state=active,activating,reloading',
                    'hestia-professional-cloud-backup@*.timer','hestia-professional-backup@*.timer',
                    'hestia-professional-cloud-backup@*.service','hestia-professional-backup@*.service'])
    if units.strip(): raise ValueError('Pause backup timers and wait for active backups before registration')
    for path in (root/'data/professional/jobs').glob('*.json'):
        # Job receipts are intentionally root-owned, group-readable metadata.
        if json.loads(regular(path)).get('state') in ('queued','running'):
            raise ValueError('Wait for the active backup job')

def configure(name, provider, remote, folder, transport, password, *, config=CONFIG,
              secret_dir=Path('/etc/hestiacp/professional/secrets'), root=ROOT,
              allow_plain_ftp=False, runner=run, guard=None):
    identifier(name)
    if provider not in PROVIDERS: raise ValueError('Provider excluded or unsupported')
    if not isinstance(password,str) or not 20 <= len(password) <= 256 or any(c in password for c in '\n\r\0'):
        raise ValueError('Restic password must contain 20 to 256 characters on one line')
    raw_transport=private_read(transport)  # Never display credentials or put them in argv.
    if provider=='google-drive':
        parser=configparser.ConfigParser(interpolation=None,strict=True);parser.read_string(raw_transport)
        section=parser[remote] if remote in parser else {}
        token=json.loads(section.get('token','{}'))
        if not section.get('client_id') or not section.get('client_secret') or not isinstance(token,dict) or not token.get('refresh_token'):
            raise ValueError('Authorize Drive with a dedicated OAuth client and refresh token first')
    parent=private_directory(config.parent,0o700)
    with lock(parent/'cloud-setup.lock'):
        guard = guard or (lambda: idle(root,runner))
        guard()
        before = private_read(config) if config.exists() or config.is_symlink() else None
        cfg = json.loads(before) if before is not None else {'schema':2,'targets':[]}
        if not isinstance(cfg,dict) or cfg.get('schema')!=2 or not isinstance(cfg.get('targets'),list):
            raise ValueError('Existing configuration requires review')
        if len(cfg['targets'])>=8 or any(not isinstance(t,dict) or t.get('id')==name for t in cfg['targets']):
            raise ValueError('Target already exists or target limit reached')
        private_directory(secret_dir,0o700)
        password_path=secret_dir/(name+'.password')
        fd=os.open(password_path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        info=os.fstat(fd);committed=False
        try:
            with os.fdopen(fd,'wb') as stream:
                os.fchmod(stream.fileno(),0o600);stream.write((password+'\n').encode());stream.flush();os.fsync(stream.fileno())
            target={'id':name,'provider':provider,'remote':remote,'path':folder,
                    'rclone_config':str(transport),'password_file':str(password_path)}
            if provider=='ftp':target['allow_plain_ftp']=allow_plain_ftp
            cfg['targets'].append(target)
            with tempfile.TemporaryDirectory(prefix='.cloud-setup-',dir=parent) as tmp:
                draft=Path(tmp)/'candidate.json';root_json(draft,cfg);settings(draft)
                runner(['/usr/bin/rclone','lsf',remote+':','--dirs-only','--max-depth','1',
                        '--config',str(transport),'--retries','1','--low-level-retries','1',
                        '--contimeout','10s','--timeout','15s','--max-duration','30s'])
                guard()
                current=private_read(config) if config.exists() or config.is_symlink() else None
                if current!=before:raise ValueError('Configuration changed during registration')
                # Keep a private rollback copy; credentials and existing destinations stay untouched.
                if before is not None:
                    previous=parent/('cloud-backup.before-'+secrets.token_hex(12)+'.json')
                    root_json(previous,json.loads(before))
                os.replace(draft,config);committed=True
            return {'state':'configured','target':name,'provider':provider,'connection_read_tested':True,
                    'repository_initialized':False,'backup_sent':False,'restoration_tested':False,
                    'schedule_enabled':False,'existing_destinations_preserved':True}
        finally:
            if not committed:
                current=password_path.lstat()
                if (current.st_dev,current.st_ino)==(info.st_dev,info.st_ino):password_path.unlink()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--name',required=True);parser.add_argument('--provider',required=True,choices=PROVIDERS)
    parser.add_argument('--remote',required=True);parser.add_argument('--folder',required=True)
    parser.add_argument('--transport',required=True,type=Path)
    parser.add_argument('--allow-plain-ftp',action='store_true')
    args=parser.parse_args();require_root()
    if not sys.stdin.isatty():raise ValueError('Use the interactive root console')
    from apply import verify_deployment
    if verify_deployment(ROOT)['state']!='verified':raise ValueError('Deployment integrity requires review')
    warnings.simplefilter('error',getpass.GetPassWarning);os.umask(0o077)
    password=getpass.getpass('Senha Restic (20–256 caracteres; guarde fora da VPS): ')
    if getpass.getpass('Repita a senha Restic: ')!=password:raise ValueError('Password confirmation differs')
    print(json.dumps(configure(args.name,args.provider,args.remote,args.folder,args.transport,password,
                               allow_plain_ftp=args.allow_plain_ftp),ensure_ascii=False))

if __name__=='__main__':
    try:main()
    except (Exception,KeyboardInterrupt):
        print(json.dumps({'state':'refused-or-failed','message':'Revise integridade, destino, arquivo privado, conexão e tarefas de backup. Credenciais não são exibidas.'}),file=sys.stderr)
        sys.exit(1)
