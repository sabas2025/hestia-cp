#!/usr/bin/env python3
"""Record actual package versions and the approved external-asset lock."""
import argparse
import json
from pathlib import Path
from ops import atomic_json, command, config, require_root, utcnow

def collect(root):
    names = ['hestia', 'hestia-php', 'hestia-nginx', 'nginx', 'apache2', 'mariadb-server',
             'mysql-server', 'postgresql', 'rclone', 'restic', 'php8.4-cli', 'php8.4-fpm']
    code, output = command(['dpkg-query', '-W', '-f=${binary:Package}\t${Version}\t${db:Status-Status}\n', *names])
    packages = []
    for line in output.splitlines():
        parts = line.split('\t')
        if len(parts) == 3 and parts[2] == 'installed':
            packages.append({'name': parts[0], 'version': parts[1]})
    lock = root / 'professional/bundle/install/assets.lock.tsv'
    assets = []
    if lock.is_file():
        for line in lock.read_text().splitlines():
            name, digest, url = line.split('\t')
            assets.append({'name': name, 'sha256': digest, 'url': url})
    return {'schema': 1, 'generated_at': utcnow(), 'hestia': config(root / 'conf/hestia.conf').get('VERSION'),
            'packages': packages, 'assets': assets, 'source_commit': 'c14350f40c71b71f36e3945e42607d7d9c4980eb'}

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('/usr/local/hestia'))
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args()
    if args.write: require_root()
    data = collect(args.root)
    if args.write: atomic_json(args.root / 'data/professional/inventory.json', data)
    print(json.dumps(data, ensure_ascii=False, indent=2))
