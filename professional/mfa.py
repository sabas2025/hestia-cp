#!/usr/bin/env python3
"""Root-only MFA self-service. Credentials arrive on stdin; no external QR provider.

Pending enrollment seeds use AES-GCM with a separate key. Active TOTP seeds keep
the native format so official package updates cannot lock out every authenticator.
"""
import argparse
import base64
import ctypes
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import re
import secrets
import stat
import struct
import sys
import time
from urllib.parse import quote
from ops import config, lock, private_directory, private_read, require_root, username, utcnow

RECOVERY = r'HPR-[A-F0-9]{8}-[A-F0-9]{8}-[A-F0-9]{8}'

def root_json(path, value):
    from apply import atomic_file
    private_directory(path.parent, 0o700)
    atomic_file(path, (json.dumps(value, separators=(',', ':')) + '\n').encode(), 0o600)

def event(folder, user, action, phase):
    path = folder / 'events.jsonl'
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_uid != 0 or st.st_mode & 0o077 or st.st_nlink != 1:
            raise ValueError('Unsafe MFA audit log')
        line = json.dumps({'user':user,'action':action,'phase':phase,'at':utcnow()},separators=(',',':')).encode()+b'\n'
        os.write(fd,line); os.fsync(fd)
    finally: os.close(fd)

def totp(seed, step):
    raw = hmac.new(base64.b32decode(seed), struct.pack('>Q', step), hashlib.sha1).digest()
    offset = raw[-1] & 15
    return str((struct.unpack('>I', raw[offset:offset+4])[0] & 0x7fffffff) % 1000000).zfill(6)

def password_ok(user, password):
    if not isinstance(password, str) or not 1 <= len(password) <= 128 or '\0' in password:
        return False
    shadow = next((line.split(':')[1] for line in Path('/etc/shadow').read_text().splitlines()
                   if line.split(':', 1)[0] == user), '')
    if not shadow or shadow[0] in '!*': return False
    lib = ctypes.CDLL('libcrypt.so.1')
    lib.crypt.argtypes = [ctypes.c_char_p, ctypes.c_char_p]; lib.crypt.restype = ctypes.c_char_p
    hashed = lib.crypt(password.encode(), shadow.encode())
    return bool(hashed) and hmac.compare_digest(hashed.decode(), shadow)

def qr(seed, user):
    import qrcode
    from qrcode.image.svg import SvgPathImage
    uri = 'otpauth://totp/' + quote('Hestia:' + user, safe='') + '?secret=' + seed + '&issuer=Hestia&digits=6&period=30'
    image = qrcode.make(uri, image_factory=SvgPathImage)
    output = io.BytesIO(); image.save(output)
    return 'data:image/svg+xml;base64,' + base64.b64encode(output.getvalue()).decode()

def set_seed(path, seed):
    """Preserve native owner/group/mode and reject unrecognized configuration shape."""
    from apply import atomic_file
    if path.is_symlink() or any(p.is_symlink() for p in path.parents): raise ValueError('Unsafe account')
    st = path.stat(); text = path.read_text()
    for key, value in [('TWOFA', seed), ('QRCODE', '')]:
        pattern = r"(?m)^" + key + r"='[^'\r\n]*'$"
        if len(re.findall(pattern, text)) != 1: raise ValueError('Account MFA contract changed')
        text = re.sub(pattern, key + "='" + value + "'", text)
    atomic_file(path, text.encode(), st.st_mode & 0o777)
    os.chown(path, st.st_uid, st.st_gid)

def recovery_hash(code): return hashlib.sha256(code.encode()).hexdigest()

def encryption_key(folder, create=False):
    path = folder / 'mfa.key'
    if create and not path.exists():
        private_directory(folder, 0o700)
        # Exclusive creation prevents separate accounts racing to replace the global key.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try: os.write(fd, (secrets.token_hex(32)+'\n').encode()); os.fsync(fd)
        finally: os.close(fd)
    key = bytes.fromhex(private_read(path).strip())
    if len(key) != 32: raise ValueError('Invalid MFA encryption key')
    return key

def protect_seed(seed, user, folder):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    nonce = secrets.token_bytes(12)
    encrypted = AESGCM(encryption_key(folder, create=True)).encrypt(nonce, seed.encode(), ('hestia-mfa:'+user).encode())
    return 'ENC1:' + base64.b64encode(nonce + encrypted).decode()

def reveal_seed(value, user, folder):
    if not value.startswith('ENC1:'): return value
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.exceptions import InvalidTag
    raw = base64.b64decode(value[5:], validate=True)
    if len(raw) < 29: raise ValueError('Invalid encrypted MFA seed')
    try: seed = AESGCM(encryption_key(folder)).decrypt(raw[:12], raw[12:], ('hestia-mfa:'+user).encode()).decode()
    except (InvalidTag, UnicodeError): raise ValueError('Encrypted MFA seed cannot be verified') from None
    if not re.fullmatch(r'[A-Z2-7]{16,128}', seed): raise ValueError('Invalid MFA seed')
    return seed

def verify_factor(state, seed, code, now, recovery=True):
    if re.fullmatch(r'[0-9]{6}', code or ''):
        for step in range(int(now)//30 - 1, int(now)//30 + 2):
            if step > state.get('last_step', -1) and hmac.compare_digest(totp(seed, step), code):
                state['last_step'] = step; return True
    if recovery and re.fullmatch(RECOVERY, code or '') and state.get('seed_hash') == recovery_hash(seed):
        digest = recovery_hash(code)
        matches = [v for v in state.get('recovery_hashes', []) if hmac.compare_digest(digest, v)]
        if matches:
            state['recovery_hashes'].remove(matches[0]); return True
    return False

def codes(state, seed):
    values = ['HPR-' + '-'.join(secrets.token_hex(4).upper() for _ in range(3)) for _ in range(10)]
    state['recovery_hashes'] = [recovery_hash(v) for v in values]
    state['seed_hash'] = recovery_hash(seed)
    return values

def operate(root, user, action, request, verifier=password_ok, now=None, keystore=Path('/etc/hestiacp/professional/secrets')):
    username(user); now = time.time() if now is None else now
    account_path = root / 'data/users' / user / 'user.conf'
    account = config(account_path)
    if account.get('SUSPENDED') != 'no' or account.get('LOGIN_DISABLED') == 'yes': raise ValueError('Account unavailable')
    native = config(root / 'conf/hestia.conf')
    if native.get('DEMO_MODE') == 'yes': raise ValueError('Read-only mode')
    folder = private_directory(root / 'data/professional-mfa', 0o700)
    state_path = folder / (user + '.json')
    with lock(folder / 'locks' / (user + '.lock')):
        account = config(account_path)
        if account.get('SUSPENDED') != 'no' or account.get('LOGIN_DISABLED') == 'yes': raise ValueError('Account unavailable')
        state = json.loads(private_read(state_path)) if state_path.exists() else {}
        if now - state.get('failure_window', 0) > 300:
            state['failures'] = 0; state['failure_window'] = now
        if state.get('failures', 0) >= 10: raise ValueError('Wait before retrying')
        state['failures'] = state.get('failures', 0) + 1
        state['last_attempt'] = {'action': action, 'at': utcnow()}
        root_json(state_path, state)  # Persist attempts even if verification raises/fails.
        seed = account.get('TWOFA', '')
        if seed and state.get('seed_hash') and state['seed_hash'] != recovery_hash(seed):
            # An explicit native administrator reset must invalidate old recovery/replay state.
            state.pop('last_step', None); state.pop('recovery_hashes', None)
            state['seed_hash'] = recovery_hash(seed)
        if action != 'verify' and not verifier(user, request.get('password', '')):
            raise ValueError('Authentication failed')
        if action != 'verify': event(folder,user,action,'requested')
        if action == 'reauth':
            if seed and not verify_factor(state, seed, request.get('code', ''), now):
                raise ValueError('Current factor required')
            result = {'state': 'reauthenticated'}
        elif action == 'prepare':
            if seed: raise ValueError('MFA already enabled')
            binding = request.get('binding', '')
            if not re.fullmatch(r'[a-f0-9]{64}', binding): raise ValueError('Session binding required')
            pending_seed = base64.b32encode(secrets.token_bytes(20)).decode()
            state.pop('last_step', None)
            image = qr(pending_seed, user)  # Fail before staging if renderer missing.
            state['pending'] = {'seed': protect_seed(pending_seed, user, keystore), 'binding': binding, 'expires': now + 600}
            result = {'state': 'pending', 'qr': image, 'manual_key': pending_seed, 'expires_in': 600}
        elif action == 'enable':
            pending = state.get('pending', {})
            if seed or pending.get('expires', 0) < now or not hmac.compare_digest(pending.get('binding', ''), request.get('binding', '')):
                raise ValueError('Enrollment expired or belongs to another session')
            new_seed = reveal_seed(pending.get('seed', ''), user, keystore)
            if not new_seed or not verify_factor(state, new_seed, request.get('code', ''), now, recovery=False): raise ValueError('Invalid or reused code')
            recovery = codes(state, new_seed); state.pop('pending', None)
            # Store recovery hashes before enabling. A crash may leave unused hashes, never an enabled factor without them.
            root_json(state_path, state); set_seed(account_path, new_seed)
            result = {'state': 'enabled', 'recovery_codes': recovery}
        elif action in ('verify', 'disable', 'recovery'):
            if not re.fullmatch(r'[A-Z2-7]{16,128}', seed) or not verify_factor(state, seed, request.get('code', ''), now):
                raise ValueError('Invalid or reused factor')
            if action == 'disable':
                # Consume the factor before modifying native state; a failed write cannot replay recovery.
                root_json(state_path, state); set_seed(account_path, '')
                state.pop('recovery_hashes', None); state.pop('seed_hash', None); state.pop('pending', None)
                result = {'state': 'disabled'}
            elif action == 'recovery':
                result = {'state': 'recovery-renewed', 'recovery_codes': codes(state, seed)}
            else: result = {'state': 'verified'}
        else: raise ValueError('Unknown operation')
        # Keep prepare attempts in the window: repeatedly generating seeds is not a rate-limit bypass.
        if action != 'prepare': state['failures'] = 0
        state['last_event'] = {'action': action, 'at': utcnow()}
        root_json(state_path, state)
        if action != 'verify': event(folder,user,action,'completed')
        return result

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--user', required=True, type=username)
    p.add_argument('--action', required=True, choices=['prepare', 'enable', 'disable', 'recovery', 'verify', 'reauth'])
    p.add_argument('--root', type=Path, default=Path('/usr/local/hestia'))
    a = p.parse_args(); require_root()
    raw = sys.stdin.read(4097)
    if len(raw) > 4096: raise ValueError('Oversized request')
    request = json.loads(raw)
    if not isinstance(request, dict) or set(request) - {'password', 'code', 'binding'}: raise ValueError('Invalid request')
    if any(not isinstance(v, str) for v in request.values()): raise ValueError('Invalid request')
    result = operate(a.root, a.user, a.action, request)
    print('ok' if a.action == 'verify' else json.dumps(result))

if __name__ == '__main__':
    try: main()
    except (ValueError, KeyError, OSError, ImportError):
        print('MFA operation refused. Verify credentials, clock, dependencies and recovery procedure.', file=sys.stderr)
        sys.exit(1)
