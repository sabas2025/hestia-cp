#!/usr/bin/env python3
"""Reviewed operations: fixed commands, live authorization, MFA, queue and rollback.

This module does not install services or claim production efficacy. Root-owned
plans are single use and expire; private state contains no passwords or OTPs.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import secrets
import signal
import stat
import subprocess
import sys
import time
from ops import config, lock, private_read, private_directory, require_root, safe_environment, username
from mfa import root_json, event, operate as reauthenticate
from apply import atomic_file, verify_deployment
from assistant import domain

MARKER = '# HESTIA_PRO_BUSINESS_V1'
ACTIONS = {'dns-ttl', 'mail-rate', 'cache-profile', 'ssh-policy', 'resources'}
DELEGABLE = {'dns-ttl', 'mail-rate', 'cache-profile'}

def run(args):
    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                               env=safe_environment(), start_new_session=True)
    try:
        output, _ = process.communicate(timeout=90)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL); process.communicate()
        raise RuntimeError('Operation timed out; inspect history') from None
    if process.returncode or len(output) > 1048576:
        raise RuntimeError('Native operation failed; inspect history')
    return output.decode('utf-8', errors='replace')

def regular(path, limit=2097152):
    path = Path(path)
    if path.is_symlink() or any(p.is_symlink() for p in path.parents):
        raise ValueError('Linked configuration rejected')
    if not path.exists(): return None
    st = path.stat()
    if not stat.S_ISREG(st.st_mode) or st.st_uid != 0 or st.st_mode & 0o022 or st.st_nlink != 1 or st.st_size > limit:
        raise ValueError('Configuration must be a bounded root-controlled regular file')
    return path.read_bytes()

def account(root, user, target=False):
    username(user)
    path = root / 'data/users' / user / 'user.conf'
    if regular(path) is None: raise ValueError('Account unavailable')
    data = config(path)
    if data.get('SUSPENDED') != 'no' or (not target and data.get('LOGIN_DISABLED') == 'yes'):
        raise ValueError('Account unavailable')
    regular(root / 'conf/hestia.conf')
    live = config(root / 'conf/hestia.conf')
    if live.get('VERSION') != '1.10.5' or live.get('DEMO_MODE') == 'yes':
        raise ValueError('Version review or read-only mode')
    return data

def authorize(root, actor, action, owner):
    actual = account(root, actor); account(root, owner, target=True)
    if actual.get('ROLE') == 'admin': return
    if actor != owner or action not in DELEGABLE: raise ValueError('Operation not delegated')
    access = json.loads(private_read(root / 'professional/business-access.json'))
    if access.get('schema') != 1 or action not in access.get('grants', {}).get(actor, []):
        raise ValueError('Operation not delegated')

def record(root, owner, kind, name):
    name = domain(name)
    text = regular(root / 'data/users' / owner / (kind + '.conf'))
    for line in (text or b'').decode().splitlines():
        values = dict(re.findall(r"([A-Z_]+)='([^'\r\n]*)'", line))
        if values.get('DOMAIN') == name:
            if values.get('SUSPENDED') == 'yes': raise ValueError('Domain suspended')
            return values
    raise ValueError('Domain not owned by account')

def integer(value, low, high):
    if type(value) is not int or not low <= value <= high: raise ValueError('Number outside allowed range')
    return value

def pool_spec(fs, owner, name):
    username(owner); name = domain(name)
    suffix = hashlib.sha256(name.encode()).hexdigest()[:24]
    return {'path': str(fs / 'etc/nginx/conf.d' / ('hestia-pro-cache-' + suffix + '.conf')),
            'mode': 0o644, 'body': MARKER + '\n# ' + owner + '/' + name + '\n' +
            f'proxy_cache_path /var/cache/nginx/hestia-pro/{owner}/{name} levels=1:2 use_temp_path=off keys_zone=hpro_{name}:1m inactive=10m max_size=64m;\n'}

def build(root, fs, action, owner, params):
    expected = {'dns-ttl': {'domain','value'}, 'mail-rate': {'domain','value'},
                'cache-profile': {'domain','value'}, 'ssh-policy': {'value'},
                'resources': {'uid','memory_mb','tasks','io_weight'}}
    if action not in expected or not isinstance(params, dict) or set(params) != expected[action]:
        raise ValueError('Invalid parameters')
    base = root / 'data/users' / owner
    spec = {'watch': [str(base/'user.conf'), str(root/'conf/hestia.conf')], 'files': [],
            'forward': [], 'reverse': [], 'validate': [], 'reload': [], 'notes': []}
    if action in ('dns-ttl', 'mail-rate', 'cache-profile'):
        name = domain(params['domain']); kind = {'dns-ttl':'dns','mail-rate':'mail','cache-profile':'web'}[action]
        old = record(root, owner, kind, name); spec['watch'].append(str(base/(kind+'.conf')))
        if action == 'dns-ttl':
            new = integer(params['value'], 300, 604800); before = old.get('TTL','')
            if not before.isdigit(): raise ValueError('Native TTL unavailable')
            spec['watch'].append(str(base/'dns'/(name+'.conf')))
            command = 'v-change-dns-domain-ttl'
            spec['notes'].append('TTL reversion updates the DNS serial; propagation requires external validation.')
        elif action == 'mail-rate':
            new = integer(params['value'], 1, 10000); before = old.get('RATE_LIMIT') or 'system'
            if before != 'system' and not before.isdigit(): raise ValueError('Native mail rate unavailable')
            command = 'v-change-mail-domain-rate-limit'
            spec['notes'].append('Per-mailbox overrides remain authoritative; delivery and reputation require real tests.')
        else:
            live = config(root/'conf/hestia.conf'); new = params['value']; before = old.get('PROXY','')
            if live.get('WEB_SYSTEM') != 'apache2' or live.get('PROXY_SYSTEM') != 'nginx':
                raise ValueError('This cache profile requires Nginx in front of Apache')
            if new not in ('professional-safe','default') or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', before):
                raise ValueError('Cache template unavailable')
            extensions = old.get('PROXY_EXT','')
            if not re.fullmatch(r'[A-Za-z0-9,]{0,2048}', extensions): raise ValueError('Invalid extensions')
            for suffix in ('tpl','stpl','sh'):
                template = root/'data/templates/web/nginx'/('professional-safe.'+suffix)
                if regular(template) is None: raise ValueError('Cache template not installed')
                spec['watch'].append(str(template))
            pool = pool_spec(fs, owner, name)
            if new == 'default': pool['body'] = None
            spec['files'].append(pool)
            spec['forward'] = [[str(root/'bin/v-change-web-domain-proxy-tpl'), owner, name, new, extensions, 'no']]
            spec['reverse'] = [[str(root/'bin/v-change-web-domain-proxy-tpl'), owner, name, before, extensions, 'no']]
            spec['validate'] = [['/usr/sbin/nginx','-t']]; spec['reload'] = [['/usr/bin/systemctl','reload','nginx']]
            spec['notes'].append('Public responses only; cookies, authentication, query strings and sensitive routes bypass cache. Verify application behavior and cache hits.')
        if action != 'cache-profile':
            spec['forward'] = [[str(root/'bin'/command), owner, name, str(new)]]
            spec['reverse'] = [[str(root/'bin'/command), owner, name, before]]
    elif action == 'ssh-policy':
        value = params['value']
        if value not in ('keys-only','sftp-only','disabled'): raise ValueError('Invalid SSH policy')
        if owner == config(root/'conf/hestia.conf').get('ROOT_USER','admin'):
            raise ValueError('Recovery administrator is protected')
        sshd = fs/'etc/ssh/sshd_config'; text = regular(sshd)
        if not text or not re.search(rb'(?mi)^\s*Include\s+/etc/ssh/sshd_config.d/\*\.conf\s*$', text):
            raise ValueError('Standard sshd Include required')
        spec['watch'].append(str(sshd))
        body = MARKER + '\nMatch User ' + owner + '\n'
        if value == 'disabled': body += '    DenyUsers ' + owner + '\n'
        else:
            key = fs/'etc/ssh/hestia-keys'/owner; data = regular(key, 65536)
            if not data or not re.search(rb'(?m)(?:^|\s)(?:ssh-ed25519|sk-ssh-ed25519@openssh.com|ecdsa-sha2-nistp256)\s+[A-Za-z0-9+/=]+', data):
                raise ValueError('Root-reviewed public key file required; test access first')
            spec['watch'].append(str(key))
            body += '    AuthenticationMethods publickey\n    PasswordAuthentication no\n    KbdInteractiveAuthentication no\n    PubkeyAuthentication yes\n    AuthorizedKeysFile /etc/ssh/hestia-keys/%u\n'
            if value == 'sftp-only': body += '    ForceCommand internal-sftp\n    DisableForwarding yes\n    PermitTTY no\n'
        body += 'Match all\n'
        spec['files'].append({'path':str(fs/'etc/ssh/sshd_config.d'/('80-hestia-pro-'+owner+'.conf')), 'mode':0o600,'body':body})
        spec['validate'] = [['/usr/sbin/sshd','-t']]; spec['reload'] = [['/usr/bin/systemctl','reload','ssh']]
        spec['notes'].append('SFTP-only does not create a chroot. Maintain a console and test a new SSH connection before closing the current one.')
    else:
        uid = integer(params['uid'],1000,2147483647)
        if pwd.getpwnam(owner).pw_uid != uid: raise ValueError('UID does not match account')
        memory = integer(params['memory_mb'],128,1048576); tasks = integer(params['tasks'],32,65536)
        weight = integer(params['io_weight'],1,10000)
        body = MARKER + f'\n[Slice]\nMemoryAccounting=yes\nMemoryMax={memory}M\nTasksMax={tasks}\nIOAccounting=yes\nIOWeight={weight}\n'
        spec['files'].append({'path':str(fs/f'etc/systemd/system/user-{uid}.slice.d/80-hestia-pro.conf'),'mode':0o644,'body':body})
        spec['reload'] = [['/usr/bin/systemctl','daemon-reload']]
        spec['notes'].append('Only processes inside this user slice are covered. Native CPUQuota/MemoryHigh remain unchanged. Existing PHP, mail, databases and Docker may be outside the slice; daemon-reload does not migrate or restart them.')
    for item in spec['files']:
        previous = regular(item['path'])
        if previous is not None and not previous.startswith((MARKER+'\n').encode()):
            raise ValueError('Unmanaged configuration requires manual review')
    return spec

def snapshot(spec):
    result = {}
    for name in sorted(set(spec['watch'] + [f['path'] for f in spec['files']])):
        data = regular(name)
        result[name] = None if data is None else {'sha256':hashlib.sha256(data).hexdigest(),'mode':Path(name).stat().st_mode & 0o777}
    return result

def folder(root): return root/'data/professional-business'
def plan_path(root, ident):
    if not isinstance(ident,str) or not re.fullmatch(r'[a-f0-9]{32}',ident): raise ValueError('Invalid plan')
    return folder(root)/'plans'/(ident+'.json')
def load(root, ident): return json.loads(private_read(plan_path(root, ident),4194304))
def save(root, plan): root_json(plan_path(root,plan['id']),plan)
def public(plan):
    result = {k:plan[k] for k in ('id','actor','owner','action','params','created','expires','state')}
    result.update(notes=plan['spec']['notes'],files=plan['spec']['files'],commands=plan['spec']['forward'])
    return result

def create(root, fs, actor, action, owner, params, now=None):
    now = time.time() if now is None else now
    authorize(root,actor,action,owner); spec = build(root,fs,action,owner,params)
    plan = {'id':secrets.token_hex(16),'actor':actor,'owner':owner,'action':action,'params':params,
            'created':now,'expires':now+600,'state':'planned','spec':spec,'before':snapshot(spec)}
    save(root,plan); return public(plan)

def effective_ssh(plan, runner):
    if plan['action'] != 'ssh-policy': return
    text = runner(['/usr/sbin/sshd','-T','-C',f"user={plan['owner']},host=localhost,addr=127.0.0.1"])
    values = dict(line.split(' ',1) for line in text.splitlines() if ' ' in line)
    value = plan['params']['value']
    if value == 'disabled':
        if plan['owner'] not in values.get('denyusers','').split(): raise ValueError('Effective SSH denial not confirmed')
    elif values.get('passwordauthentication') != 'no' or values.get('kbdinteractiveauthentication') != 'no' or values.get('pubkeyauthentication') != 'yes' or values.get('authenticationmethods') != 'publickey' or values.get('authorizedkeysfile') != '/etc/ssh/hestia-keys/%u':
        raise ValueError('Earlier SSH policy overrides this configuration')
    elif value == 'sftp-only' and (values.get('forcecommand') != 'internal-sftp' or values.get('disableforwarding') != 'yes' or values.get('permittty') != 'no'):
        raise ValueError('Effective SFTP restriction not confirmed')

def restore(plan, runner):
    for old in plan.get('saved_files',[]):
        path = Path(old['path'])
        regular(path)
        if old['body'] is None:
            if path.exists(): path.unlink()
        else: atomic_file(path,old['body'].encode(),old['mode'])
    if plan.get('native_attempted'):
        for command in plan['spec']['reverse']: runner(command)
    for command in plan['spec']['validate'] + plan['spec']['reload']: runner(command)

def execute(root, fs, actor, ident, rollback=False, runner=run, now=None):
    now = time.time() if now is None else now
    with lock(folder(root)/'locks/change.lock'):
        plan = load(root,ident); authorize(root,actor,plan['action'],plan['owner'])
        if actor != plan['actor']: raise ValueError('Plan belongs to another actor')
        if rollback:
            if plan['state'] != 'applied' or snapshot(plan['spec']) != plan.get('after'):
                raise ValueError('Rollback requires unchanged applied configuration')
            plan['state'] = 'rolling-back'; save(root,plan)
            try:
                restore(plan,runner); plan['state'] = 'rolled-back'
            except Exception:
                plan['state'] = 'recovery-required'; save(root,plan); raise
        else:
            if plan['state'] != 'planned' or plan['expires'] < now: raise ValueError('Plan expired or already used')
            if build(root,fs,plan['action'],plan['owner'],plan['params']) != plan['spec'] or snapshot(plan['spec']) != plan['before']:
                raise ValueError('Configuration changed; create a new plan')
            plan['saved_files'] = []
            for item in plan['spec']['files']:
                data = regular(item['path'])
                plan['saved_files'].append({'path':item['path'],'body':None if data is None else data.decode(),
                                            'mode':item['mode'] if data is None else Path(item['path']).stat().st_mode & 0o777})
            plan['state'] = 'applying'; save(root,plan)
            event(folder(root),actor,plan['action'],'requested')
            try:
                for item in plan['spec']['files']:
                    path = Path(item['path'])
                    if item['body'] is None:
                        if path.exists(): path.unlink()
                    else: atomic_file(path,item['body'].encode(),item['mode'])
                if plan['spec']['forward']:
                    plan['native_attempted'] = True; save(root,plan)
                    for command in plan['spec']['forward']: runner(command)
                for command in plan['spec']['validate']: runner(command)
                effective_ssh(plan,runner)
                for command in plan['spec']['reload']: runner(command)
                plan['state'] = 'applied'; plan['after'] = snapshot(plan['spec'])
            except Exception:
                try: restore(plan,runner); plan['state'] = 'failed-restored'
                except Exception: plan['state'] = 'recovery-required'
                save(root,plan); event(folder(root),actor,plan['action'],plan['state']); raise
        plan['updated'] = now; save(root,plan)
        event(folder(root),actor,plan['action'],plan['state'])
        return public(plan)

def enqueue(root, actor, ident, rollback=False, runner=run, now=None):
    now = time.time() if now is None else now
    with lock(folder(root)/'locks/queue.lock'):
        plan = load(root,ident); authorize(root,actor,plan['action'],plan['owner'])
        if actor != plan['actor'] or plan['state'] != ('applied' if rollback else 'planned') or (not rollback and plan['expires'] < now):
            raise ValueError('Plan unavailable')
        ticket = folder(root)/'queue'/(ident+'.json')
        if ticket.exists() and json.loads(private_read(ticket)).get('state') in ('queued','running'):
            raise ValueError('Operation already queued')
        nonce = secrets.token_hex(16)
        job = {'actor':actor,'id':ident,'rollback':rollback,'nonce':nonce,'expires':now+60,'state':'queued'}
        root_json(ticket,job)
        try:
            runner(['/usr/bin/systemd-run','--quiet','--collect','--no-block',
                    '--unit=hestia-business-'+ident+'-'+nonce[:8], '--property=Type=exec',
                    '--property=User=root','--property=Group=root','--property=UMask=0077',
                    '--property=RuntimeMaxSec=600','--property=KillMode=control-group','--',
                    '/usr/bin/python3','-I',str(root/'professional/change_jobs_entry.py'),ident,nonce])
        except Exception:
            job['state'] = 'queue-failed'; root_json(ticket,job); raise
        result = public(plan); result['state'] = 'queued'; return result

def work(root, fs, ident, nonce, runner=run, integrity=verify_deployment, now=None):
    now = time.time() if now is None else now
    ticket = folder(root)/'queue'/(plan_path(root,ident).name)
    with lock(folder(root)/'locks/queue.lock'):
        job = json.loads(private_read(ticket))
        if job.get('state') != 'queued' or job.get('nonce') != nonce: raise ValueError('Consumed queue ticket')
        job['state'] = 'running'; root_json(ticket,job)
    try:
        if job['expires'] < now or integrity(root).get('state') != 'verified': raise ValueError('Expired or unverified deployment')
        result = execute(root,fs,job['actor'],ident,job['rollback'],runner,now)
        job['state'] = 'completed'; return result
    except Exception:
        job['state'] = 'job-failed'; raise
    finally: root_json(ticket,job)

def history(root, actor):
    account(root,actor); output = []; directory = folder(root)/'plans'
    for path in sorted(directory.glob('*.json'),key=lambda p:p.stat().st_mtime,reverse=True)[:200]:
        plan = load(root,path.stem)
        if plan['actor'] != actor: continue
        result = public(plan); ticket = folder(root)/'queue'/path.name
        if ticket.exists():
            state = json.loads(private_read(ticket)).get('state')
            if state in ('queued','running','queue-failed','job-failed'): result['job_state'] = state
        output.append(result)
    return {'plans':output}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path('/usr/local/hestia'))
    parser.add_argument('--actor',required=True,type=username)
    parser.add_argument('--op',required=True,choices=('plan','apply','rollback','history','diagnose','coverage'))
    args = parser.parse_args(); require_root()
    raw = sys.stdin.read(16385)
    if len(raw)>16384: raise ValueError('Oversized request')
    request = json.loads(raw)
    if not isinstance(request,dict) or set(request)-{'action','owner','params','id','password','code','domain'}:
        raise ValueError('Invalid request')
    if args.op == 'plan': result = create(args.root,Path('/'),args.actor,request['action'],request['owner'],request['params'])
    elif args.op == 'history': result = history(args.root,args.actor)
    elif args.op in ('diagnose','coverage'):
        from assurance import diagnose, coverage
        owner = request.get('owner',args.actor)
        authorize(args.root,args.actor,'dns-ttl' if args.op=='diagnose' else 'resources',owner)
        result = diagnose(args.root,owner,request['domain']) if args.op=='diagnose' else coverage(owner)
    else:
        plan = load(args.root,request['id']); authorize(args.root,args.actor,plan['action'],plan['owner'])
        if plan['actor'] != args.actor or not account(args.root,args.actor).get('TWOFA'):
            raise ValueError('Account must have A2F enabled')
        if verify_deployment(args.root)['state'] != 'verified': raise ValueError('Deployment requires review')
        reauthenticate(args.root,args.actor,'reauth',{'password':request.get('password',''),'code':request.get('code','')})
        result = enqueue(args.root,args.actor,request['id'],args.op=='rollback')
    print(json.dumps(result))

if __name__ == '__main__':
    try: main()
    except (ValueError,KeyError,TypeError,OSError,RuntimeError,subprocess.SubprocessError):
        print('Operation refused; check authorization, factor, plan and private history.',file=sys.stderr); sys.exit(1)
