#!/usr/bin/env python3
"""Administrator project tools: Docker, Compose, non-root Node.js and Hestia proxy templates."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import subprocess
import sys
from urllib.parse import urlsplit
from ops import atomic_json, config, lock, private_read, require_root, safe_environment, utcnow, username
from apply import atomic_file
from assistant import domain

ID = r'[a-z][a-z0-9-]{1,31}'
DOCKER = {
    'containers': (['ps', '--all', '--format', '{{json .}}'], False),
    'images': (['image', 'ls', '--format', '{{json .}}'], False),
    'networks': (['network', 'ls', '--format', '{{json .}}'], False),
    'volumes': (['volume', 'ls', '--format', '{{json .}}'], False),
    'disk': (['system', 'df'], False),
    'container-start': (['start'], True), 'container-stop': (['stop'], True),
    'container-restart': (['restart'], True), 'container-remove': (['rm'], True),
    'container-logs': (['logs', '--tail', '100'], False),
    'container-stats': (['stats', '--no-stream'], False),
    'container-inspect': (['inspect', '--format', '{{json .State}}'], False),
    'image-pull': (['image', 'pull'], True), 'image-remove': (['image', 'rm'], True),
    'network-create': (['network', 'create'], True), 'network-remove': (['network', 'rm'], True),
    'volume-create': (['volume', 'create'], True), 'volume-remove': (['volume', 'rm'], True),
}
COMPOSE = {'status': ['ps', '--all'], 'logs': ['logs', '--tail', '100', '--no-color'],
           'up': ['up', '--detach', '--remove-orphans'], 'down': ['down'],
           'start': ['start'], 'stop': ['stop'], 'restart': ['restart'],
           'pull': ['pull'], 'build': ['build'], 'validate': ['config', '--quiet']}

def run(args):
    # Output is for the trusted administrator's terminal; never expose logs or environments through PHP.
    completed = subprocess.run(args, env=safe_environment(), capture_output=True, text=True, timeout=1800)
    if completed.returncode: raise RuntimeError('Project command failed; review the service from the administrator terminal')
    return completed.stdout

def identifier(value):
    if not re.fullmatch(ID, value or ''): raise ValueError('Invalid project identifier')
    return value

def docker_command(action, target=None):
    if action not in DOCKER: raise ValueError('Unknown Docker action')
    args, changes = DOCKER[action]
    targeted = action.startswith(('container-', 'image-', 'network-', 'volume-'))
    if targeted:
        if not target or target.startswith('-') or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_./:@-]{0,255}', target):
            raise ValueError('Explicit Docker object required')
        if action == 'image-pull' and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_./:-]*@sha256:[a-f0-9]{64}', target):
            raise ValueError('Pin the image by reviewed SHA256 digest before pulling')
        args = args + [target]
    elif target: raise ValueError('This Docker action does not accept a target')
    return ['docker'] + args, changes

def settings(path):
    cfg = json.loads(private_read(path))
    if not isinstance(cfg, dict) or set(cfg) != {'projects'} or not isinstance(cfg['projects'], dict):
        raise ValueError('Use projects configuration')
    for name, project in cfg['projects'].items():
        identifier(name)
        if not isinstance(project, dict) or set(project) - {'type', 'owner', 'domain', 'port', 'compose_file', 'sha256', 'working_directory', 'entrypoint', 'node_binary', 'environment_file', 'url'}:
            raise ValueError('Unknown project field')
        if project.get('type') not in ('compose', 'node', 'proxy', 'editor', 'marketing', 'docker-ui'):
            raise ValueError('Unknown project type')
        username(project.get('owner', ''))
        if project.get('domain'): project['domain'] = domain(project['domain'])
        if project.get('url'):
            parsed = urlsplit(project['url'])
            if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.fragment or parsed.query:
                raise ValueError('Project links require HTTPS without credentials, query strings or fragments')
        if project.get('type') in ('proxy', 'node'):
            if type(project.get('port')) is not int or not 1024 <= project['port'] <= 65535:
                raise ValueError('Use a dedicated unprivileged loopback application port')
        if project['type'] in ('compose', 'marketing'):
            data = private_read(project.get('compose_file', ''), 4194304)
            if hashlib.sha256(data.encode()).hexdigest() != project.get('sha256'):
                raise ValueError('Compose changed after administrator review; update its approved SHA256')
    return cfg

def compose_command(project_id, project, action, runner=run):
    identifier(project_id)
    if project.get('type') not in ('compose', 'marketing') or action not in COMPOSE:
        raise ValueError('Select a registered Compose project and action')
    base = ['docker', 'compose', '--env-file', '/dev/null', '--project-name', 'hestia-' + project_id, '--file', project['compose_file']]
    # Resolve and validate Compose privately before any mutation, including interpolated fields.
    resolved = json.loads(runner(base + ['config', '--format', 'json']))
    if any(v.get('driver_opts') or v.get('external') for v in (resolved.get('volumes') or {}).values()):
        raise ValueError('External or host-backed volume drivers require manual review')
    if any(v.get('driver', 'bridge') != 'bridge' or v.get('external') for v in (resolved.get('networks') or {}).values()):
        raise ValueError('Use private bridge networks for managed Compose')
    for service in resolved.get('services', {}).values():
        if service.get('privileged') or service.get('network_mode') == 'host' or service.get('pid') == 'host' or service.get('devices') or service.get('cap_add'):
            raise ValueError('Privileged/host-sharing services require separate manual review')
        if any(v.get('type') == 'bind' for v in service.get('volumes', [])):
            raise ValueError('Managed Compose uses named volumes; host bind mounts require separate review')
        if any(str(p.get('host_ip')) not in ('127.0.0.1', '::1') for p in service.get('ports', [])):
            raise ValueError('Published container ports must bind to loopback behind the proxy')
        if action in ('up', 'pull') and not re.fullmatch(r'.+@sha256:[a-f0-9]{64}', service.get('image', '')):
            raise ValueError('Deploy reviewed image digests; never use latest tags')
        if any(v.get('type') != 'volume' for v in service.get('volumes', [])):
            raise ValueError('Unknown Compose volume type')
    if not resolved.get('services'): raise ValueError('Compose has no services')
    return base + COMPOSE[action], action not in ('status', 'logs', 'validate')

def node_unit(name, project, lookup=pwd.getpwnam):
    identifier(name); user = username(project['owner']); account = lookup(user)
    if account.pw_uid < 1000: raise ValueError('Node projects require a dedicated unprivileged application account')
    work = project.get('working_directory', ''); entry = project.get('entrypoint', ''); binary = project.get('node_binary', '/usr/bin/node')
    if not re.fullmatch(r'/home/' + re.escape(user) + r'/[A-Za-z0-9_./-]+', work) or '..' in Path(work).parts:
        raise ValueError('Application directory must be within its account home')
    if not re.fullmatch(r'[A-Za-z0-9_./-]+\.m?js', entry) or entry.startswith('/') or '..' in Path(entry).parts:
        raise ValueError('Use a relative JavaScript entrypoint')
    if binary not in ('/usr/bin/node', '/usr/local/bin/node'): raise ValueError('Use an administrator-installed Node LTS binary')
    environment = project.get('environment_file', '')
    if not re.fullmatch(r'/etc/hestiacp/professional/secrets/[A-Za-z0-9_.-]+', environment):
        raise ValueError('Configure a private systemd environment file')
    private_read(environment)
    return f'''# HESTIA_PROFESSIONAL_NODE_V1
[Unit]
Description=Hestia Node.js project {name}
After=network.target

[Service]
Type=simple
User={user}
Group={account.pw_gid}
WorkingDirectory={work}
Environment=NODE_ENV=production
Environment=HOST=127.0.0.1
Environment=PORT={project['port']}
EnvironmentFile={environment}
ExecStart={binary} {work}/{entry}
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths={work}
UMask=0077
MemoryMax=512M
TasksMax=128

[Install]
WantedBy=multi-user.target
'''

def proxy_template(port, tls=False):
    if type(port) is not int or not 1024 <= port <= 65535: raise ValueError('Invalid proxy port')
    return f'''# HESTIA_PROFESSIONAL_PROXY_V1
# This template sends traffic directly to a loopback app; Apache WAF does not inspect it.
server {{
    listen %ip%:{'%proxy_ssl_port% ssl' if tls else '%proxy_port%'};
    server_name %domain_idn% %alias_idn%;
    {'ssl_certificate %ssl_pem%; ssl_certificate_key %ssl_key%;' if tls else ''}
    {'if ($anti_replay = 307) { return 307 https://$host$request_uri; }' if tls else ''}
    {'if ($anti_replay = 425) { return 425; }' if tls else ''}
    include %home%/%user%/conf/web/%domain%/nginx.{'hsts' if tls else 'forcessl'}.conf*;
    access_log /var/log/nginx/domains/%domain%.log combined;
    error_log /var/log/nginx/domains/%domain%.error.log error;
    location ^~ /.well-known/acme-challenge/ {{
        root %home%/%user%/web/%domain%/public_html;
        try_files $uri =404;
    }}
    location ~ /\\.(?!well-known/) {{ deny all; }}
    location / {{
        proxy_pass http://127.0.0.1:{port};
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 60s;
    }}
}}
'''

def publish_catalog(cfg, root):
    # Only identifiers and HTTPS launch URLs are published. No environment, Compose content or tokens.
    value = {'generated_at': utcnow(), 'projects': []}
    for name, p in cfg['projects'].items():
        value['projects'].append({k: p[k] for k in ('type', 'owner', 'url') if k in p} | {'id': name})
    atomic_json(root / 'data/professional/projects.json', value)
    return {'published': len(value['projects'])}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('module', choices=['docker', 'compose', 'node', 'proxy', 'catalog'])
    parser.add_argument('action'); parser.add_argument('--config', type=Path); parser.add_argument('--project')
    parser.add_argument('--target'); parser.add_argument('--apply', action='store_true')
    parser.add_argument('--root', type=Path, default=Path('/usr/local/hestia'))
    args = parser.parse_args(); require_root()
    if args.module == 'docker': command, changes = docker_command(args.action, args.target)
    else:
        if args.config is None: raise ValueError('Private configuration required')
        cfg = settings(args.config)
        if args.module == 'catalog':
            if args.action != 'publish': raise ValueError('Unknown catalog action')
            if args.apply: print(json.dumps(publish_catalog(cfg, args.root))); return 0
            print(json.dumps({'mode': 'plan', 'projects': list(cfg['projects'])})); return 0
        name = identifier(args.project or ''); project = cfg['projects'][name]
        if args.module == 'compose':
            command, changes = compose_command(name, project, args.action)
        elif args.module == 'node':
            if project['type'] != 'node': raise ValueError('Node project required')
            if args.action == 'install':
                body = node_unit(name, project)
                if args.apply:
                    target = Path('/etc/systemd/system') / f'hestia-node-{name}.service'
                    if target.exists() and '# HESTIA_PROFESSIONAL_NODE_V1' not in target.read_text():
                        raise ValueError('Existing service is not managed by this tool')
                    work = Path(project['working_directory'])
                    if not work.is_dir() or not (work / project['entrypoint']).is_file():
                        raise ValueError('Prepare and review application files before installing its service')
                    atomic_file(target, body.encode())
                    run(['systemctl', 'daemon-reload'])
                print(body); return 0
            if args.action not in ('status', 'start', 'stop', 'restart', 'enable'):
                raise ValueError('Unknown Node action')
            command, changes = ['systemctl', args.action, f'hestia-node-{name}.service'], args.action != 'status'
        else:
            if project['type'] not in ('node', 'proxy') or args.action != 'templates': raise ValueError('Use proxy templates for a Node or proxy project')
            # Domain assignment remains an explicit native Hestia operation after reviewing both templates.
            generated = {'professional-' + name + suffix: proxy_template(project['port'], suffix == '.stpl') for suffix in ('.tpl', '.stpl')}
            if args.apply:
                for filename, body in generated.items(): atomic_file(args.root / 'data/templates/web/nginx' / filename, body.encode())
            print(json.dumps({'mode': 'written' if args.apply else 'plan', 'templates': generated,
                              'next': 'Review and assign the template in native Hestia; validate nginx and TLS before reload'})); return 0
    if changes and not args.apply:
        print(json.dumps({'mode': 'plan', 'command': command, 'changes_applied': False})); return 0
    with lock(args.root / 'data/professional-locks/projects.lock'):
        output = run(command)
    print(output, end=''); return 0

if __name__ == '__main__':
    try: sys.exit(main())
    except (ValueError, OSError, KeyError, RuntimeError, subprocess.TimeoutExpired):
        print('Project operation stopped; review configuration, permissions and installed dependencies.', file=sys.stderr); sys.exit(1)
