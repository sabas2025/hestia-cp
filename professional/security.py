#!/usr/bin/env python3
"""Reviewed Apache ModSecurity/CRS + existing Hestia Fail2Ban profiles, with rollback."""
import argparse
import base64
import difflib
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid
from ops import atomic_json, config, lock, private_directory, private_read, require_root, safe_environment, utcnow
from apply import atomic_file

PROFILES = {'observacao': ('DetectionOnly', 1, 5, 600), 'basico': ('On', 1, 5, 900),
            'intermediario': ('On', 2, 4, 1800), 'avancado': ('On', 3, 3, 3600)}
WAF = 'etc/apache2/mods-available/security2.conf'
JAIL = 'etc/fail2ban/jail.d/99-hestia-professional.local'
STATE = 'var/lib/hestia-professional/security'
MARKER = '# HESTIA_PROFESSIONAL_SECURITY_V1'

def settings(path):
    cfg = json.loads(private_read(path))
    if not isinstance(cfg, dict) or set(cfg) - {'profile', 'waf', 'fail2ban', 'admin_cidrs', 'request_body_limit'}:
        raise ValueError('Unknown security configuration field')
    if cfg.get('profile') not in PROFILES or type(cfg.get('waf')) is not bool or type(cfg.get('fail2ban')) is not bool:
        raise ValueError('Select a profile and explicit desired states')
    limit = cfg.setdefault('request_body_limit', 134217728)
    if type(limit) is not int or not 1048576 <= limit <= 1073741824:
        raise ValueError('Request body limit must be between 1 MiB and 1 GiB')
    values = cfg.get('admin_cidrs')
    if not isinstance(values, list) or not 1 <= len(values) <= 16:
        raise ValueError('Configure administrator recovery IPs before changing Fail2Ban')
    networks = [ipaddress.ip_network(v, strict=False) for v in values]
    if any(n.prefixlen < (24 if n.version == 4 else 64) for n in networks):
        raise ValueError('Administrator exemptions must be /24 or narrower for IPv4, /64 for IPv6')
    cfg['admin_cidrs'] = [str(n) for n in networks]
    return cfg

def command(args):
    result = subprocess.run(args, capture_output=True, text=True, env=safe_environment(), timeout=60)
    if result.returncode: raise RuntimeError('Service command failed: ' + Path(args[0]).name)
    return result.stdout

def effective_ignores(runner=command):
    result = {}
    for jail in ('ssh-iptables', 'hestia-iptables'):
        output = runner(['fail2ban-client', 'get', jail, 'ignoreip'])
        values = []
        for token in re.findall(r'[A-Za-z0-9_.:/-]+', output):
            try:
                if '.' in token or ':' in token:
                    values.append(str(ipaddress.ip_network(token, strict=False))); continue
            except ValueError: pass
            if '.' in token and re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9.-]*[a-zA-Z0-9]', token): values.append(token)
        result[jail] = values
    return result

def render(cfg, existing=None, managed=()):
    mode, pl, retry, bantime = PROFILES[cfg['profile']]
    files = {}
    if cfg['waf'] or 'waf' in managed:
        if not cfg['waf']: mode = 'Off'
        files[WAF] = f'''{MARKER}
<IfModule security2_module>
    SecDataDir /var/cache/modsecurity
    Include /etc/modsecurity/modsecurity.conf
    SecRuleEngine {mode}
    SecRequestBodyAccess On
    SecRequestBodyLimit {cfg['request_body_limit']}
    SecRequestBodyNoFilesLimit 1048576
    SecResponseBodyAccess Off
    SecAuditEngine RelevantOnly
    SecAuditLogType Serial
    SecAuditLog /var/log/apache2/modsec_audit.log
    SecAuditLogParts AHZ
    Include /etc/modsecurity/crs/crs-setup.conf
    SecAction "id:100001,phase:1,pass,nolog,t:none,setvar:tx.paranoia_level={pl},setvar:tx.blocking_paranoia_level={pl},setvar:tx.executing_paranoia_level={pl}"
    IncludeOptional /etc/modsecurity/crs/REQUEST-900-EXCLUSION-RULES-BEFORE-CRS.conf
    Include /usr/share/modsecurity-crs/rules/*.conf
    IncludeOptional /etc/modsecurity/crs/RESPONSE-999-EXCLUSION-RULES-AFTER-CRS.conf
</IfModule>
'''
    if cfg['fail2ban'] or 'fail2ban' in managed:
        files[JAIL] = MARKER + '\n' + ''.join(f'''
[{jail}]
enabled = {'true' if cfg['fail2ban'] else 'false'}
maxretry = {retry}
findtime = 600
bantime = {bantime}
ignoreip = {' '.join(dict.fromkeys(['127.0.0.1/8', '::1'] + cfg['admin_cidrs'] + (existing or {}).get(jail, [])))}
''' for jail in ('ssh-iptables', 'hestia-iptables'))
    return files

def prerequisites(fs, hestia, cfg, runner=command, desired=None):
    conf = config(hestia / 'conf/hestia.conf')
    if conf.get('VERSION') != '1.10.5': raise ValueError('Review protection for this Hestia version')
    if cfg['waf']:
        if conf.get('WEB_SYSTEM') != 'apache2':
            raise ValueError('Automated WAF profile requires the Hestia Nginx + Apache stack; Nginx-only needs a reviewed connector')
        required = ['etc/apache2/mods-available/security2.conf', 'etc/modsecurity/modsecurity.conf',
                    'etc/modsecurity/crs/crs-setup.conf', 'usr/share/modsecurity-crs/rules/REQUEST-901-INITIALIZATION.conf']
        if not all((fs / p).is_file() for p in required):
            raise ValueError('Install/configure distribution libapache2-mod-security2 and modsecurity-crs first')
        if 'security2_module' not in runner(['apache2ctl', '-M']): raise ValueError('Enable security2 Apache module first')
        current = (fs / WAF).read_text()
        if MARKER not in current and re.search(r'^\s*(?:SecRule|SecAction|Include\s)', current, re.M):
            raise ValueError('Existing customized module policy needs manual review')
        extra = [p for p in (fs / 'etc/modsecurity').glob('*.conf') if p.name != 'modsecurity.conf']
        if extra: raise ValueError('Additional ModSecurity policy found; merge it manually before automatic management')
    if cfg['fail2ban']:
        native = fs / 'etc/fail2ban/jail.local'
        if not native.is_file() or not all(f'[{j}]' in native.read_text() for j in ('ssh-iptables', 'hestia-iptables')):
            raise ValueError('Expected native Hestia jails not found; do not add duplicate SSH jails')
        if (desired or cfg)['fail2ban']:
            for unit in ('ssh-iptables', 'hestia-iptables'): runner(['fail2ban-client', 'status', unit])

def managed_components(fs):
    return {name for name, relative in [('waf', WAF), ('fail2ban', JAIL)]
            if (fs / relative).is_file() and not (fs / relative).is_symlink()
            and MARKER in (fs / relative).read_text()}

def validate_reload(cfg, runner):
    # Validate all touched services before reloading either one.
    if cfg['waf']: runner(['apache2ctl', 'configtest'])
    if cfg['fail2ban']: runner(['fail2ban-client', '-t'])
    if cfg['waf']: runner(['systemctl', 'reload', 'apache2'])
    if cfg['fail2ban']: runner(['fail2ban-client', 'reload'])

def restore_files(fs, previous):
    for name, info in previous.items():
        if name not in (WAF, JAIL): raise ValueError('Rollback path not permitted')
        path = fs / name
        if info is None:
            if path.is_symlink(): raise ValueError('Rollback symlink rejected')
            path.unlink(missing_ok=True)
        else:
            data = base64.b64decode(info['content'], validate=True)
            if hashlib.sha256(data).hexdigest() != info['sha256']: raise ValueError('Rollback checksum mismatch')
            atomic_file(path, data, info['mode'])

def apply_profile(fs, hestia, cfg, runner=command, peer=None):
    managed = managed_components(fs)
    reload_cfg = {**cfg, **{key: cfg[key] or key in managed for key in ('waf', 'fail2ban')}}
    prerequisites(fs, hestia, reload_cfg, runner, desired=cfg)
    if cfg['fail2ban'] and peer and not any(ipaddress.ip_address(peer) in ipaddress.ip_network(v) for v in cfg['admin_cidrs']):
        raise ValueError('Current SSH IP must be included in administrator exemptions')
    state = private_directory(fs / STATE, 0o700)
    with lock(state / 'locks/security.lock'):
        files = render(cfg, effective_ignores(runner) if cfg['fail2ban'] else {}, managed); previous = {}
        for name in files:
            path = fs / name
            if path.is_symlink() or any(p.is_symlink() for p in path.parents): raise ValueError('Managed symlink rejected')
            previous[name] = {'content': base64.b64encode(path.read_bytes()).decode(),
                              'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'mode': path.stat().st_mode & 0o777} if path.exists() else None
        transaction = uuid.uuid4().hex
        public_path = hestia / 'data/professional/security.json'
        previous_public = json.loads(public_path.read_text()) if public_path.is_file() and not public_path.is_symlink() else None
        record = {'schema': 2, 'id': transaction, 'created_at': utcnow(), 'config': reload_cfg, 'desired': cfg, 'previous': previous, 'previous_public': previous_public}
        atomic_json(state / 'transactions' / f'{transaction}.json', record, 0o600)
        try:
            for name, content in files.items(): atomic_file(fs / name, content.encode(), 0o644)
            validate_reload(reload_cfg, runner)
        except Exception as original:
            restore_files(fs, previous)
            try: validate_reload(reload_cfg, runner)
            except Exception:
                raise RuntimeError('Protection failed; original files restored but service recovery requires console review') from original
            raise RuntimeError('Protection failed; original configuration restored and reloaded') from original
        controlled = {key: reload_cfg[key] for key in ('waf', 'fail2ban')}
        public = {'schema': 2, 'configured_at': utcnow(), 'profile': cfg['profile'],
                  'waf': cfg['waf'] if controlled['waf'] else None,
                  'fail2ban': cfg['fail2ban'] if controlled['fail2ban'] else None,
                  'managed': controlled, 'desired_state': {key: cfg[key] for key in controlled},
                  'effective_policy': {'waf': ('off' if not cfg['waf'] else 'detection-only' if cfg['profile'] == 'observacao' else 'on') if controlled['waf'] else 'unmanaged',
                                       'fail2ban': ('on' if cfg['fail2ban'] else 'off') if controlled['fail2ban'] else 'unmanaged'},
                  'runtime_attack_tested': False, 'rollback_id': transaction,
                  'scope': 'apache-backed-sites-and-native-ssh-panel-jails', 'verified_at_apply': True}
        atomic_json(hestia / 'data/professional/security.json', public)
        return public

def rollback(fs, hestia, transaction, runner=command):
    if not re.fullmatch(r'[0-9a-f]{32}', transaction): raise ValueError('Invalid rollback identifier')
    state = fs / STATE
    with lock(state / 'locks/security.lock'):
        record = json.loads(private_read(state / 'transactions' / f'{transaction}.json'))
        # Reject an old rollback over a newer transaction.
        active = hestia / 'data/professional/security.json'
        if not active.is_file() or json.loads(active.read_text()).get('rollback_id') != transaction:
            raise ValueError('Only the active protection transaction can be rolled back')
        restore_files(fs, record['previous']); validate_reload(record['config'], runner)
        result = record.get('previous_public') or {'state': 'rolled-back', 'updated_at': utcnow(), 'profile': 'revisar', 'waf': False, 'fail2ban': False}
        atomic_json(active, result)
        return result

def collect(hestia, runner=command):
    data = {'checked_at': utcnow(), 'fail2ban': 'unknown', 'waf': 'unknown'}
    for name, args in [('fail2ban', ['fail2ban-client', 'ping']), ('waf', ['apache2ctl', '-M'])]:
        try:
            output = runner(args)
            data[name] = 'available' if (name == 'fail2ban' and 'pong' in output.lower()) or 'security2_module' in output else 'unavailable'
        except (OSError, RuntimeError, subprocess.TimeoutExpired): data[name] = 'unavailable'
    snapshot = hestia / 'data/professional/security.json'
    if snapshot.is_file() and not snapshot.is_symlink() and snapshot.stat().st_size <= 1048576:
        try: data['managed'] = json.loads(snapshot.read_text())
        except (ValueError, OSError): data['managed'] = {'state': 'snapshot-unavailable'}
    return data

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['plan', 'apply', 'rollback', 'status'])
    parser.add_argument('--config', type=Path); parser.add_argument('--transaction')
    parser.add_argument('--root', type=Path, default=Path('/usr/local/hestia'))
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args(); require_root(); fs = Path('/')
    if args.action == 'status': print(json.dumps(collect(args.root), indent=2)); return 0
    if args.action == 'rollback':
        if not args.apply: raise ValueError('Rollback requires --apply')
        print(json.dumps(rollback(fs, args.root, args.transaction or ''), indent=2)); return 0
    if args.config is None: raise ValueError('Configuration required')
    cfg = settings(args.config)
    if args.action == 'plan' or not args.apply:
        files = render(cfg, effective_ignores(command) if cfg['fail2ban'] else {}, managed_components(fs)); diffs = {}
        for name, body in files.items():
            path = fs / name
            diffs[name] = ''.join(difflib.unified_diff(path.read_text().splitlines(True) if path.is_file() else [], body.splitlines(True), fromfile=name, tofile='proposed/' + name))
        print(json.dumps({'mode': 'plan', 'profile': cfg['profile'], 'diffs': diffs,
                          'prerequisites': 'Distribution ModSecurity2 + CRS enabled; native Hestia jails active; console recovery available',
                          'scope': 'Apache sites, not panel port 8083, direct backend exposure or volumetric DDoS'}, indent=2)); return 0
    peer = os.environ.get('SSH_CONNECTION', '').split()
    print(json.dumps(apply_profile(fs, args.root, cfg, peer=peer[0] if peer else None), indent=2)); return 0

if __name__ == '__main__':
    try: sys.exit(main())
    except (ValueError, OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        print('Protection stopped: ' + str(error), file=sys.stderr); sys.exit(1)
