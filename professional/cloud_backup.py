#!/usr/bin/env python3
"""Multi-destination encrypted account backups. Plans by default; no browser writes."""
import argparse
import configparser
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from ops import atomic_json, config, lock, private_directory, private_read, require_root, safe_environment, username, utcnow

PROVIDERS = {'google-drive': 'drive', 'amazon-s3': 's3', 'private-s3': 's3',
             'ftps': 'ftp', 'ftp': 'ftp', 'sftp': 'sftp', 'private-webdav': 'webdav'}
ACTIONS = ('plan', 'init', 'run', 'check', 'drill', 'retention')

def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-z][a-z0-9-]{1,31}', value):
        raise ValueError('Invalid target identifier')
    return value

def settings(path):
    cfg = json.loads(private_read(path))
    allowed = {'schema', 'targets', 'rpo_hours', 'rto_minutes', 'keep_daily', 'keep_weekly', 'keep_monthly'}
    if not isinstance(cfg, dict) or set(cfg) - allowed or cfg.get('schema') != 2:
        raise ValueError('Expected cloud backup schema 2')
    for key, default in [('rpo_hours', 24), ('rto_minutes', 120), ('keep_daily', 7), ('keep_weekly', 4), ('keep_monthly', 6)]:
        value = cfg.setdefault(key, default)
        if type(value) is not int or not 1 <= value <= 3650:
            raise ValueError('Invalid retention or recovery objective')
    targets = cfg.get('targets')
    if not isinstance(targets, list) or not 1 <= len(targets) <= 8:
        raise ValueError('Configure between one and eight targets')
    ids, repos = set(), set()
    for target in targets:
        if not isinstance(target, dict) or set(target) - {'id', 'provider', 'remote', 'path', 'password_file', 'rclone_config', 'allow_plain_ftp'}:
            raise ValueError('Unknown target field')
        name = identifier(target.get('id')); provider = target.get('provider')
        if name in ids or provider not in PROVIDERS:
            raise ValueError('Duplicate target or unsupported provider')
        ids.add(name)
        remote = target.get('remote', ''); folder = target.get('path', '')
        if not isinstance(remote, str) or not re.fullmatch(r'[a-zA-Z][a-zA-Z0-9_-]{0,40}', remote):
            raise ValueError('Use a named rclone remote, never an inline backend')
        if not isinstance(folder, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9/_.-]{0,200}', folder) or any(p in ('.', '..') for p in folder.split('/')) or '//' in folder:
            raise ValueError('Use a relative dedicated repository path')
        key = (str(target.get('rclone_config')), remote, folder)
        if key in repos:
            raise ValueError('Each target requires a dedicated repository')
        repos.add(key)
        private_read(target.get('password_file', ''))
        parser = configparser.ConfigParser(interpolation=None, strict=True)
        parser.read_string(private_read(target.get('rclone_config', '')))
        if remote not in parser or parser[remote].get('type') != PROVIDERS[provider]:
            raise ValueError('Provider does not match rclone remote')
        section = parser[remote]
        # Per-target configuration is intentionally isolated; backend options cannot inject commands.
        if parser.defaults() or parser.sections() != [remote]:
            raise ValueError('Use one remote per private rclone configuration')
        forbidden = {'no_check_certificate', 'skip_verify', 'use_insecure_cipher', 'insecure_skip_verify'}
        if any(section.get(k, '').lower() in ('true', 'yes', '1') for k in forbidden):
            raise ValueError('TLS or SSH verification may not be disabled')
        if any(k.endswith('_command') or k in ('ssh', 'command', 'config_pass') for k in section):
            raise ValueError('External credential or transport commands are not accepted')
        if provider == 'ftp' and target.get('allow_plain_ftp') is not True:
            raise ValueError('Plain FTP requires allow_plain_ftp=true; credentials are exposed on the transport')
        if provider == 'ftps' and not any(section.get(k, '').lower() == 'true' for k in ('tls', 'explicit_tls')):
            raise ValueError('FTPS must enable TLS')
        if provider == 'private-webdav' and not section.get('url', '').startswith('https://'):
            raise ValueError('Private WebDAV requires HTTPS')
        if provider in ('amazon-s3', 'private-s3') and section.get('endpoint') and not section.get('endpoint').startswith('https://'):
            raise ValueError('S3 endpoint requires HTTPS')
        if provider == 'amazon-s3' and section.get('provider') != 'AWS':
            raise ValueError('Amazon target requires provider AWS')
        if provider == 'sftp':
            private_read(section.get('key_file', ''))
            known = section.get('known_hosts_file', '')
            private_read(known)
            if not section.get('host') or section.get('disable_hashcheck', '').lower() == 'true':
                raise ValueError('SFTP requires a host and host verification')
        for field in ('service_account_file',):
            if section.get(field): private_read(section[field])
        target['repository'] = f'rclone:{remote}:{folder}'
    return cfg

def checked(args, env=None):
    # Discard provider diagnostics: they may include tokens, URL credentials or account metadata.
    result = subprocess.run(args, env=env or safe_environment(), capture_output=True, text=True, timeout=21600)
    if result.returncode:
        raise RuntimeError(f'External backup command failed ({result.returncode})')
    return result.stdout

def inventory(root, user):
    result = {}
    for kind, field in [('web', 'DOMAIN'), ('db', 'DB')]:
        path = root / 'data/users' / user / f'{kind}.conf'
        result[kind] = re.findall(r"(?:^|\n)" + field + r"='([^'\r\n]+)'", path.read_text()) if path.is_file() else []
    return result

def validate_archive(path, expected):
    """Read headers only, never extract an untrusted archive as root."""
    with tarfile.open(path, 'r:') as archive:
        names = set()
        for member in archive:
            name = PurePosixPath(member.name)
            if name.is_absolute() or '..' in name.parts:
                raise ValueError('Unsafe archive entry')
            if member.isfile() and member.size > 0:
                names.add(str(name))
    missing = []
    for domain in expected['web']:
        if not any(f'web/{domain}/domain_data.tar.{suffix}' in names for suffix in ('gz', 'zst')):
            missing.append('web')
    for database in expected['db']:
        if not any(f'db/{database}/{database}.{engine}.sql.{suffix}' in names for engine in ('mysql', 'pgsql') for suffix in ('gz', 'zst')):
            missing.append('db')
    if missing or not names:
        raise ValueError('Archive missing expected site data or database dumps; review native exclusions and backup logs')
    return {'sites': len(expected['web']), 'databases': len(expected['db']), 'archive_structure': 'verified',
            'sql_import_tested': False, 'application_restored': False}

def make_archive(root, user, runner, staging):
    native = config(root / 'conf/hestia.conf')
    folder = Path(native.get('BACKUP', '/backup'))
    if not folder.is_absolute() or folder.is_symlink() or any(p.is_symlink() for p in folder.parents):
        raise ValueError('Unsafe native backup directory')
    if folder.exists() and (folder.stat().st_uid != 0 or folder.stat().st_mode & 0o022):
        raise ValueError('Native backup directory must be root controlled and not writable by other users')
    if 'local' not in native.get('BACKUP_SYSTEM', '').split(','):
        raise ValueError('Enable native local backup before multicloud copy')
    before = {p: p.stat().st_mtime_ns for p in folder.glob(f'{user}.*.tar')}
    expected = inventory(root, user)
    runner([str(root / 'bin/v-backup-user'), user], env=safe_environment())
    candidates = [p for p in folder.glob(f'{user}.*.tar') if not p.is_symlink() and p.is_file() and p.stat().st_size > 0 and (p not in before or p.stat().st_mtime_ns > before[p])]
    if not candidates: raise RuntimeError('No new native archive')
    original = max(candidates, key=lambda p: p.stat().st_mtime_ns)
    if shutil.disk_usage(staging).free < original.stat().st_size * 1.2:
        raise RuntimeError('Insufficient space for private staging copy')
    archive = Path(staging) / original.name
    # Keep native ownership/modes intact so downloads in Hestia still work.
    # Use an isolated root-private copy, not a hard link to the web-owned native archive.
    fd = os.open(original, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(fd)
        with os.fdopen(fd, 'rb', closefd=False) as source, archive.open('xb') as target:
            archive.chmod(0o600); shutil.copyfileobj(source, target, 1048576)
        after = os.fstat(fd)
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise RuntimeError('Native archive changed during staging')
    finally: os.close(fd)
    evidence = validate_archive(archive, expected)
    digest = hashlib.sha256()
    with archive.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1048576), b''): digest.update(chunk)
    evidence['sha256'] = digest.hexdigest()
    return archive, evidence

def execute(action, user, cfg, root, target_id=None, runner=checked):
    username(user)
    account = root / 'data/users' / user / 'user.conf'
    if not account.is_file() or config(account).get('SUSPENDED') != 'no':
        raise ValueError('Active Hestia account required')
    targets = [t for t in cfg['targets'] if target_id is None or t['id'] == target_id]
    if not targets: raise ValueError('Unknown target')
    if action in ('init', 'retention', 'drill') and not target_id:
        raise ValueError('Select one target for initialization, retention or recovery')
    result = {'schema': 2, 'user': user, 'action': action, 'state': 'running', 'started_at': utcnow(),
              'updated_at': utcnow(), 'targets': [], 'rpo_hours': cfg['rpo_hours'], 'rto_minutes': cfg['rto_minutes']}
    job = root / 'data/professional/jobs' / f'{user}.json'
    staging_root = private_directory(root / 'data/professional-staging', 0o700)
    with lock(root / 'data/professional-locks' / f'backup-{user}.lock'), tempfile.TemporaryDirectory(prefix='source-', dir=staging_root) as staging:
        atomic_json(job, result)
        archive = None
        try:
            if action == 'run':
                archive, result['coverage'] = make_archive(root, user, runner, staging)
            for target in targets:
                item = {'id': target['id'], 'provider': target['provider'], 'state': 'running'}
                result['targets'].append(item)
                result['step'] = action + ':' + target['id']; result['updated_at'] = utcnow(); atomic_json(job, result)
                env = {**safe_environment(), 'RESTIC_REPOSITORY': target['repository'],
                       'RESTIC_PASSWORD_FILE': target['password_file'], 'RCLONE_CONFIG': target['rclone_config']}
                tag = 'hestia-' + user
                started = time.monotonic()
                try:
                    if action == 'init': runner(['restic', 'init'], env=env)
                    elif action == 'run':
                        output = runner(['restic', 'backup', '--json', '--tag', tag, str(archive)], env=env)
                        summaries = [json.loads(line) for line in output.splitlines() if line.strip()]
                        summary = next((x for x in reversed(summaries) if x.get('message_type') == 'summary'), {})
                        snapshot = summary.get('snapshot_id', '')
                        if not re.fullmatch(r'[a-f0-9]{8,64}', snapshot): raise RuntimeError('Backup did not confirm a snapshot')
                        runner(['restic', 'check'], env=env)
                        item['snapshot_id'] = snapshot
                    elif action == 'check': runner(['restic', 'check', '--read-data-subset=5%'], env=env)
                    elif action == 'retention':
                        runner(['restic', 'forget', '--tag', tag, '--group-by', 'host,tags',
                                '--keep-daily', str(cfg['keep_daily']), '--keep-weekly', str(cfg['keep_weekly']),
                                '--keep-monthly', str(cfg['keep_monthly']), '--prune'], env=env)
                    elif action == 'drill':
                        snapshots = json.loads(runner(['restic', 'snapshots', '--tag', tag, '--json'], env=env))
                        if not snapshots: raise RuntimeError('No snapshot for account')
                        snapshot = max(snapshots, key=lambda x: x['time'])['id']
                        if not re.fullmatch(r'[a-f0-9]{64}', snapshot): raise ValueError('Invalid snapshot')
                        with tempfile.TemporaryDirectory(prefix='hestia-cloud-drill-') as td:
                            stats = json.loads(runner(['restic', 'stats', snapshot, '--mode', 'restore-size', '--json'], env=env))
                            size = stats.get('total_size')
                            if type(size) is not int or size <= 0 or shutil.disk_usage(td).free < size * 1.2:
                                raise RuntimeError('Insufficient space or invalid estimate')
                            runner(['restic', 'restore', snapshot, '--target', td, '--verify'], env=env)
                            archives = [p for p in Path(td).rglob(f'{user}.*.tar') if p.is_file() and not p.is_symlink() and not any(q.is_symlink() for q in p.parents)]
                            if len(archives) != 1: raise RuntimeError('Expected one recovered archive')
                            item['coverage'] = validate_archive(archives[0], inventory(root, user))
                            item['snapshot_id'] = snapshot
                            item['drill_scope'] = 'encrypted-restore-and-site-database-archive-structure'
                    item.update(state='succeeded', completed_at=utcnow(), duration_seconds=round(time.monotonic() - started, 2))
                    if action in ('run', 'drill'):
                        atomic_json(root / 'data/professional/backups' / f'{user}-{target["id"]}-{action}.json',
                                    {**item, 'user': user, 'rpo_hours': cfg['rpo_hours']})
                except (RuntimeError, ValueError, OSError, subprocess.TimeoutExpired, StopIteration, KeyError):
                    item.update(state='failed', error='provider-operation-failed', completed_at=utcnow())
                result['updated_at'] = utcnow(); atomic_json(job, result)
            result['state'] = 'succeeded' if all(t['state'] == 'succeeded' for t in result['targets']) else 'failed'
        except Exception:
            result.update(state='failed', step='archive-or-operation-failed'); raise
        finally:
            result.update(completed_at=utcnow(), updated_at=utcnow()); atomic_json(job, result)
            if action in ('run', 'drill') and result['state'] == 'succeeded' and (action == 'drill' or target_id is None):
                atomic_json(root / 'data/professional/backups' / f'{user}-{action}.json', result)
    return result

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=ACTIONS); parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--user', type=username, required=True); parser.add_argument('--target', type=identifier)
    parser.add_argument('--root', type=Path, default=Path('/usr/local/hestia')); parser.add_argument('--apply', action='store_true')
    args = parser.parse_args(); require_root(); cfg = settings(args.config)
    if args.action == 'plan' or not args.apply:
        print(json.dumps({'mode': 'plan', 'user': args.user, 'action': args.action,
                          'scope': 'native-account-sites-and-database-dumps',
                          'targets': [{'id': t['id'], 'provider': t['provider']} for t in cfg['targets']],
                          'rpo_hours': cfg['rpo_hours'], 'rto_minutes': cfg['rto_minutes']}, indent=2)); return 0
    result = execute(args.action, args.user, cfg, args.root, args.target)
    print(json.dumps(result, indent=2)); return 0 if result['state'] == 'succeeded' else 1

if __name__ == '__main__':
    try: sys.exit(main())
    except (ValueError, OSError, RuntimeError, subprocess.TimeoutExpired, configparser.Error):
        print('Cloud backup failed; review private configuration and provider connectivity. No secrets are logged.', file=sys.stderr); sys.exit(1)
