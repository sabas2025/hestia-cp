#!/usr/bin/env python3
"""Generate private, digest-pinned stacks for Portainer CE and listmonk; never start services."""
import argparse
import json
from pathlib import Path
import re
import sys
from apply import atomic_file
from ops import private_read, require_root

def image(value):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_./:-]*@sha256:[a-f0-9]{64}', value):
        raise ValueError('Use a reviewed image digest')
    return value

def portainer(reference):
    return {'services': {'portainer': {'image': image(reference), 'restart': 'unless-stopped',
             'ports': ['127.0.0.1:9443:9443'], 'volumes': ['/var/run/docker.sock:/var/run/docker.sock', 'portainer_data:/data'],
             'security_opt': ['no-new-privileges:true'], 'mem_limit': '512m', 'cpus': '1.0'}},
            'volumes': {'portainer_data': {}}}

def marketing(reference, database, credentials):
    if set(credentials) != {'db_password', 'admin_username', 'admin_password'} or any(not isinstance(v, str) or len(v) < 12 or '\n' in v or '\x00' in v for v in credentials.values()):
        raise ValueError('Use private generated credentials of at least 12 characters')
    # Dollar signs are escaped for Compose interpolation, not passed through a shell.
    escape = lambda v: v.replace('$', '$$')
    secret = escape(credentials['db_password'])
    return {'services': {
        'db': {'image': image(database), 'restart': 'unless-stopped',
               'environment': {'POSTGRES_PASSWORD': secret, 'POSTGRES_USER': 'listmonk', 'POSTGRES_DB': 'listmonk'},
               'volumes': ['marketing_db:/var/lib/postgresql/data'], 'mem_limit': '512m', 'cpus': '1.0',
               'healthcheck': {'test': ['CMD-SHELL', 'pg_isready -U listmonk'], 'interval': '10s', 'timeout': '5s', 'retries': 10}},
        'app': {'image': image(reference), 'restart': 'unless-stopped',
                'ports': ['127.0.0.1:9100:9000'], 'depends_on': {'db': {'condition': 'service_healthy'}},
                'environment': {'LISTMONK_app__address': '0.0.0.0:9000', 'LISTMONK_db__host': 'db', 'LISTMONK_db__port': '5432',
                                'LISTMONK_db__user': 'listmonk', 'LISTMONK_db__database': 'listmonk', 'LISTMONK_db__ssl_mode': 'disable',
                                'LISTMONK_db__password': secret, 'LISTMONK_ADMIN_USER': escape(credentials['admin_username']),
                                'LISTMONK_ADMIN_PASSWORD': escape(credentials['admin_password'])},
                'command': ['sh', '-c', './listmonk --install --idempotent --yes --config \'\' && ./listmonk --config \'\''],
                'volumes': ['marketing_uploads:/listmonk/uploads'], 'security_opt': ['no-new-privileges:true'], 'mem_limit': '512m', 'cpus': '1.0'}},
        'volumes': {'marketing_db': {}, 'marketing_uploads': {}}}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stack', choices=['portainer', 'marketing']); parser.add_argument('--image', required=True, type=image)
    parser.add_argument('--database-image', type=image); parser.add_argument('--credentials', type=Path)
    parser.add_argument('--output', required=True, type=Path); parser.add_argument('--apply', action='store_true')
    args = parser.parse_args(); require_root()
    if args.stack == 'marketing':
        if not args.database_image or not args.credentials: raise ValueError('Database image and private credential JSON required')
        value = marketing(args.image, args.database_image, json.loads(private_read(args.credentials)))
    else: value = portainer(args.image)
    # Do not print the generated document: it can contain database credentials.
    if args.apply:
        if args.output.parent != Path('/etc/hestiacp/professional/projects') or not args.output.name.endswith('.compose.json'):
            raise ValueError('Write generated stacks only to /etc/hestiacp/professional/projects/NAME.compose.json')
        atomic_file(args.output, (json.dumps(value, indent=2) + '\n').encode(), 0o600)
    print(json.dumps({'mode': 'written' if args.apply else 'plan', 'stack': args.stack, 'services': list(value['services']),
                      'started': False, 'credentials_printed': False,
                      'socket_privilege': 'root-equivalent; administrator only' if args.stack == 'portainer' else 'no Docker socket'})); return 0

if __name__ == '__main__':
    try: sys.exit(main())
    except (ValueError, OSError): print('Stack generation stopped; check reviewed digests and private inputs.', file=sys.stderr); sys.exit(1)
