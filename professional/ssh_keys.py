#!/usr/bin/env python3
"""Root-console public-key leases. No private keys, passwords or arbitrary commands."""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
from pathlib import Path
import re
import subprocess
import sys
from ops import lock, require_root, safe_environment
from business import account, regular
from apply import atomic_file

def lease_line(public, expires, networks, now=None):
    now = datetime.now(timezone.utc) if now is None else now
    parts = public.strip().split()
    if '\n' in public.strip() or len(public)>4096 or len(parts)<2 or parts[0] not in ('ssh-ed25519','sk-ssh-ed25519@openssh.com','ecdsa-sha2-nistp256'):
        raise ValueError('One supported public key required')
    base64.b64decode(parts[1],validate=True)
    normalized = ' '.join(parts[:2])
    result = subprocess.run(['/usr/bin/ssh-keygen','-l','-f','/dev/stdin'],input=normalized+'\n',text=True,
                            capture_output=True,timeout=10,env=safe_environment())
    if result.returncode: raise ValueError('Malformed public key')
    end = datetime.fromisoformat(expires)
    if end.tzinfo is None or not 300 <= (end-now).total_seconds() <= 30*86400: raise ValueError('Expiry must be 5 minutes to 30 days ahead, with timezone')
    if len(networks)>16: raise ValueError('Too many source networks')
    sources = [str(ipaddress.ip_network(v,strict=False)) for v in networks]
    ident = hashlib.sha256(normalized.encode()).hexdigest()[:32]
    options = ['restrict','expiry-time="'+end.astimezone(timezone.utc).strftime('%Y%m%d%H%M%SZ')+'"']
    if sources: options.append('from="'+','.join(sources)+'"')
    return ident, ','.join(options)+' '+normalized+' hestia-lease:'+ident+'\n'

def update(old, ident, line=None):
    if not re.fullmatch(r'[a-f0-9]{32}',ident): raise ValueError('Invalid lease id')
    marker = 'hestia-lease:'+ident
    lines = old.splitlines(keepends=True)
    kept = [v for v in lines if v.strip().split()[-1:] != [marker]]
    if line:
        incoming = re.search(r'(ssh-ed25519|sk-ssh-ed25519@openssh.com|ecdsa-sha2-nistp256)\s+(\S+)',line).groups()
        for existing in kept:
            match = re.search(r'(ssh-ed25519|sk-ssh-ed25519@openssh.com|ecdsa-sha2-nistp256)\s+(\S+)',existing)
            if match and match.groups()==incoming: raise ValueError('Key already has another authorization; temporary restrictions would be misleading')
        if kept and not kept[-1].endswith('\n'): kept[-1] += '\n'
        kept.append(line)
    return ''.join(kept)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--owner',required=True); parser.add_argument('--public-key',type=Path)
    parser.add_argument('--expires'); parser.add_argument('--from-network',action='append',default=[])
    parser.add_argument('--remove'); parser.add_argument('--apply',action='store_true')
    args = parser.parse_args(); require_root(); root = Path('/usr/local/hestia')
    account(root,args.owner,target=True)
    if args.remove:
        if args.public_key or args.expires or args.from_network: raise ValueError('Removal cannot add a key')
        ident,line = args.remove,None
    else:
        if not args.public_key or not args.expires: raise ValueError('Public key and expiry required')
        data = regular(args.public_key,4096)
        if data is None: raise ValueError('Public key missing')
        ident,line = lease_line(data.decode(),args.expires,args.from_network)
    target = Path('/etc/ssh/hestia-keys')/args.owner
    with lock(root/'data/professional-business/locks/keys.lock'):
        old = regular(target,65536); body = update((old or b'').decode(),ident,line)
        if args.apply: atomic_file(target,body.encode(),0o600)
    print(json.dumps({'id':ident,'state':'configured' if args.apply else 'planned','ssh_login_tested':False,'path':str(target)}))

if __name__ == '__main__': main()
