#!/usr/bin/env python3
"""Register a WebDAV backup destination from the VPS console; never install Hestia."""
import argparse
import configparser
import copy
import fcntl
import getpass
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import sys
import tempfile
from urllib.parse import unquote, urlsplit, urlunsplit
import warnings

sys.dont_write_bytecode = True
ROOT = Path('/usr/local/hestia')
CONFIG = Path('/etc/hestiacp/professional/cloud-backup.json')
SECRETS = Path('/etc/hestiacp/professional/secrets')
STATE = Path('/var/lib/hestia-professional-nextcloud')
ENV = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'HOME': '/root', 'LC_ALL': 'C'}
SAFE_REASONS = {'absolute-directory-required', 'unsafe-directory', 'private-directory-required',
                'unsafe-file-path', 'unsafe-file-parent', 'unsafe-file', 'invalid-target-id',
                'invalid-url', 'https-url-without-embedded-credentials-required', 'invalid-port',
                'invalid-url-path', 'invalid-service-user', 'invalid-app-password',
                'invalid-repository-folder', 'invalid-webdav-vendor', 'external-command-failed',
                'backup-timer-or-service-active', 'backup-job-pending-review',
                'installed-backup-module-integrity-failed', 'foreign-python-module',
                'invalid-restic-password', 'verified-validator-required', 'unsafe-lock',
                'existing-configuration-needs-review', 'existing-target-or-target-limit',
                'existing-credentials-never-overwritten', 'invalid-obscured-password',
                'configuration-changed-during-setup', 'configuration-changed-before-commit',
                'root-interactive-console-required', 'restic-password-confirmation-mismatch'}


def directory(path, private=False):
    path = Path(path)
    if not path.is_absolute():
        raise ValueError('absolute-directory-required')
    for parent in [*reversed(path.parents), path]:
        if not parent.exists() and not parent.is_symlink():
            parent.mkdir(mode=0o700)
        info = parent.lstat()
        sticky_ancestor = parent != path and info.st_uid == 0 and info.st_mode & stat.S_ISVTX
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or (info.st_mode & 0o022 and not sticky_ancestor):
            raise ValueError('unsafe-directory')
    if private and path.stat().st_mode & 0o077:
        raise ValueError('private-directory-required')
    return path


def read_file(path, private=True, limit=4194304):
    path = Path(path)
    if not path.is_absolute() or any(p.is_symlink() for p in path.parents):
        raise ValueError('unsafe-file-path')
    for parent in path.parents:
        info = parent.stat()
        if info.st_uid != 0 or info.st_mode & 0o022:
            # Root-controlled sticky /tmp is allowed for isolated tests/staging.
            if not (info.st_uid == 0 and info.st_mode & stat.S_ISVTX):
                raise ValueError('unsafe-file-parent')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        mask = 0o077 if private else 0o022
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1 or info.st_mode & mask or info.st_size > limit:
            raise ValueError('unsafe-file')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            return stream.read(limit + 1)
    finally:
        os.close(fd)


def new_file(path, data):
    directory(path.parent)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    created = os.fstat(fd)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        if path.exists() or path.is_symlink():
            current = path.lstat()
            if (current.st_dev, current.st_ino) == (created.st_dev, created.st_ino):
                path.unlink()
        raise


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-z][a-z0-9-]{1,31}', value):
        raise ValueError('invalid-target-id')
    return value


def destination(url, user, password, folder, vendor):
    if not isinstance(url, str) or any(ord(c) < 33 for c in url):
        raise ValueError('invalid-url')
    parts = urlsplit(url)
    if parts.scheme != 'https' or not parts.hostname or parts.username is not None or parts.password is not None or parts.query or parts.fragment:
        raise ValueError('https-url-without-embedded-credentials-required')
    if parts.port is not None and not 1 <= parts.port <= 65535:
        raise ValueError('invalid-port')
    if any(ord(c) < 32 or ord(c) == 127 for c in unquote(parts.path)):
        raise ValueError('invalid-url-path')
    if not user or len(user) > 256 or any(c in user for c in '\r\n\0:'):
        raise ValueError('invalid-service-user')
    if not password or len(password) > 4096 or any(c in password for c in '\r\n\0'):
        raise ValueError('invalid-app-password')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9/_.-]{0,200}', folder) or any(p in ('', '.', '..') for p in folder.split('/')):
        raise ValueError('invalid-repository-folder')
    if vendor not in ('nextcloud', 'other'):
        raise ValueError('invalid-webdav-vendor')
    return urlunsplit(('https', parts.netloc, (parts.path or '/').rstrip('/') + '/', '', ''))


def run(args, *, data=None, capture=False, timeout=60):
    result = subprocess.run(args, input=data, stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, text=True, timeout=timeout, env=ENV)
    if result.returncode:
        raise RuntimeError('external-command-failed')
    return result.stdout or ''


def idle(root=ROOT, runner=run):
    patterns = ['hestia-professional-cloud-backup@*.timer', 'hestia-professional-backup@*.timer',
                'hestia-professional-cloud-backup@*.service', 'hestia-professional-backup@*.service']
    output = runner(['/usr/bin/systemctl', 'list-units', '--all', '--plain', '--no-legend',
                     '--state=active,activating,reloading', *patterns], capture=True, timeout=20)
    if output.strip():
        raise ValueError('backup-timer-or-service-active')
    for path in (root / 'data/professional/jobs').glob('*.json'):
        job = json.loads(read_file(path, private=False))
        if job.get('state') in ('queued', 'running'):
            raise ValueError('backup-job-pending-review')


def verified_core(root=ROOT):
    record = json.loads(read_file(root / 'professional/deployment.json'))
    for name in ('ops.py', 'cloud_backup.py'):
        relative = 'professional/' + name
        entries = [item for item in record.get('files', []) if item.get('file') == relative]
        data = read_file(root / relative, private=False)
        if len(entries) != 1 or hashlib.sha256(data).hexdigest() != entries[0].get('sha256') or stat.S_IMODE((root / relative).stat().st_mode) != entries[0].get('mode'):
            raise ValueError('installed-backup-module-integrity-failed')
    directory(root / 'professional')
    sys.path.insert(0, str(root / 'professional'))
    for name in ('ops', 'cloud_backup'):
        if name in sys.modules and Path(sys.modules[name].__file__).resolve() != (root / 'professional' / (name + '.py')).resolve():
            raise ValueError('foreign-python-module')
    return importlib.import_module('cloud_backup')


def configure(name, url, user, password, restic_password, folder, vendor,
              *, config=CONFIG, secret_dir=SECRETS, state=STATE, validator=None, runner=run, guard=None):
    """Add one new destination, with a private receipt and rollback of caught failures."""
    identifier(name)
    url = destination(url, user, password, folder, vendor)
    if not 14 <= len(restic_password) <= 4096 or any(c in restic_password for c in '\r\n\0'):
        raise ValueError('invalid-restic-password')
    if validator is None:
        raise ValueError('verified-validator-required')
    directory(state, private=True)
    lock_path = state / 'configure.lock'
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1 or info.st_mode & 0o077:
            raise ValueError('unsafe-lock')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return _configure(name, url, user, password, restic_password, folder, vendor,
                          config, secret_dir, state, validator, runner, guard or idle)
    finally:
        os.close(fd)


def _configure(name, url, user, password, restic_password, folder, vendor,
               config, secret_dir, state, validator, runner, guard):
    guard()
    before = read_file(config) if config.exists() or config.is_symlink() else None
    cfg = json.loads(before) if before is not None else {
        'schema': 2, 'rpo_hours': 24, 'rto_minutes': 120, 'keep_daily': 7,
        'keep_weekly': 4, 'keep_monthly': 6, 'append_only': False, 'targets': []}
    if not isinstance(cfg, dict) or cfg.get('schema') != 2 or not isinstance(cfg.get('targets'), list):
        raise ValueError('existing-configuration-needs-review')
    if len(cfg['targets']) >= 8 or any(not isinstance(t, dict) or t.get('id') == name for t in cfg['targets']):
        raise ValueError('existing-target-or-target-limit')
    transport_path = secret_dir / (name + '.conf')
    password_path = secret_dir / (name + '.password')
    if any(p.exists() or p.is_symlink() for p in (transport_path, password_path)):
        raise ValueError('existing-credentials-never-overwritten')
    directory(config.parent)
    directory(secret_dir, private=True)
    job = directory(state / secrets.token_hex(12), private=True)
    receipt = {'state': 'preparing', 'phase': 'transport', 'target': name, 'repository_initialized': False,
               'backup_sent': False, 'restoration_tested': False}
    new_file(job / 'receipt.json', encoded(receipt))
    if before is not None:
        new_file(job / 'cloud-backup.before.json', before)
    created = []
    temporary = None
    committed = False
    try:
        obscured = runner(['/usr/bin/rclone', 'obscure', '-'], data=password + '\n', capture=True, timeout=30).strip()
        if not re.fullmatch(r'[A-Za-z0-9_-]{20,8192}={0,2}', obscured):
            raise ValueError('invalid-obscured-password')
        parser = configparser.ConfigParser(interpolation=None)
        parser[name] = {'type': 'webdav', 'url': url, 'vendor': vendor, 'user': user, 'pass': obscured}
        output = io.StringIO(); parser.write(output)
        transport = output.getvalue().encode()
        draft_transport = job / 'transport.conf'
        draft_password = job / 'restic.password'
        new_file(draft_transport, transport)
        new_file(draft_password, (restic_password + '\n').encode())
        target = {'id': name, 'provider': 'private-webdav', 'remote': name, 'path': folder,
                  'password_file': str(password_path), 'rclone_config': str(transport_path)}
        cfg['targets'].append(target)
        candidate = copy.deepcopy(cfg)
        candidate['targets'][-1].update(password_file=str(draft_password), rclone_config=str(draft_transport))
        draft = job / 'candidate.json'
        new_file(draft, encoded(candidate))
        receipt['phase'] = 'local-validation'
        validator(draft)
        receipt['phase'] = 'connection-read-test'
        runner(['/usr/bin/rclone', 'lsf', name + ':', '--max-depth', '1', '--dirs-only',
                '--config', str(draft_transport), '--retries', '1', '--low-level-retries', '1',
                '--contimeout', '10s', '--timeout', '15s', '--max-duration', '30s'], timeout=45)
        guard()
        current = read_file(config) if config.exists() or config.is_symlink() else None
        if current != before:
            raise ValueError('configuration-changed-during-setup')
        receipt['phase'] = 'commit'
        for path, data in [(transport_path, transport), (password_path, (restic_password + '\n').encode())]:
            new_file(path, data)
            created.append((path, data))
        final_draft = job / 'final.json'
        new_file(final_draft, encoded(cfg))
        validator(final_draft)
        handle, filename = tempfile.mkstemp(prefix='.nextcloud-', dir=config.parent)
        temporary = Path(filename)
        with os.fdopen(handle, 'wb') as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(encoded(cfg)); stream.flush(); os.fsync(stream.fileno())
        current = read_file(config) if config.exists() or config.is_symlink() else None
        if current != before:
            raise ValueError('configuration-changed-before-commit')
        os.replace(temporary, config)
        committed = True
        receipt.update(state='configured', phase='configuration-saved', connection_read_tested=True,
                       write_permission_tested=False, schedule_enabled=False)
    except BaseException:
        if not committed:
            for path, expected in reversed(created):
                if read_file(path) == expected:
                    path.unlink()
            receipt.update(state='failed', existing_configuration_preserved=True)
        raise
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
        # Private staging files survive interruption for review; never rotate secrets on retry.
        try:
            new_file(job / 'receipt.updated.json', encoded(receipt))
            os.replace(job / 'receipt.updated.json', job / 'receipt.json')
        except OSError:
            if not committed:
                raise
            receipt.update(state='configured-review', receipt_recorded=False)
    return {**receipt, 'review_directory': str(job), 'credential_file': str(password_path)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['configure'])
    parser.add_argument('--webdav', action='store_true', help='Use generic WebDAV rather than Nextcloud')
    args = parser.parse_args()
    if os.geteuid() != 0 or not sys.stdin.isatty():
        raise ValueError('root-interactive-console-required')
    os.umask(0o077)
    warnings.simplefilter('error', getpass.GetPassWarning)
    core = verified_core()
    for binary in ('/usr/bin/rclone', '/usr/bin/systemctl'):
        path = Path(binary)
        directory(path.parent)
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022 or not info.st_mode & 0o111:
            raise ValueError('unsafe-file')
    idle()
    name = identifier(input('Identificador do destino [nextcloud]: ').strip() or 'nextcloud')
    url = input('URL WebDAV HTTPS completa: ').strip()
    user = input('Usuário da nuvem: ').strip()
    password = getpass.getpass('Senha de aplicativo (não será exibida): ')
    folder = input('Pasta dedicada [hestia/servidor/restic]: ').strip() or 'hestia/servidor/restic'
    restic_password = getpass.getpass('Senha Restic; Enter para gerar uma nova: ')
    if restic_password:
        if getpass.getpass('Repita a senha Restic: ') != restic_password:
            raise ValueError('restic-password-confirmation-mismatch')
    else:
        restic_password = secrets.token_urlsafe(48)
    result = configure(name, url, user, password, restic_password, folder,
                       'other' if args.webdav else 'nextcloud', validator=core.settings)
    print(json.dumps(result, ensure_ascii=False))
    print('Guarde uma cópia protegida da senha Restic fora da VPS antes de inicializar o repositório.')


if __name__ == '__main__':
    try:
        main()
    except (Exception, KeyboardInterrupt) as error:
        print(json.dumps({'state': 'refused-or-failed', 'message':
              'Revise permissões, configuração privada, conexão e timers/tarefas de backup. '
              'Cadastros existentes não são substituídos; examine o recibo privado antes de tentar novamente.',
              'reason': str(error) if str(error) in SAFE_REASONS else 'private-review-required'}, ensure_ascii=False))
        sys.exit(1)
