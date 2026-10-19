"""Shared operations. GPL-3.0. No shell interpolation and no secret logging."""
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import grp
import json
import os
from pathlib import Path
import re
import subprocess
import stat
import tempfile

def utcnow():
    return datetime.now(timezone.utc).isoformat()

def username(value):
    if not re.fullmatch(r"[a-z][a-z0-9_]{1,29}", value):
        raise ValueError("Invalid username")
    return value

def config(path):
    output = {}
    if path.is_file():
        for line in path.read_text().splitlines():
            match = re.fullmatch(r"([A-Z][A-Z0-9_]*)='([^'\r\n]*)'", line.strip())
            if match:
                output[match[1]] = match[2]
    return output

def command(args, timeout=30):
    try:
        result = subprocess.run(args, text=True, capture_output=True, timeout=timeout,
                                env={**os.environ, "LC_ALL": "C"})
        return result.returncode, result.stdout
    except (OSError, subprocess.TimeoutExpired):
        return 127, ""

def private_directory(path, mode=0o750):
    path = Path(path)
    if path.is_symlink():
        raise ValueError("Symlink directory rejected")
    if any(p.is_symlink() for p in path.parents):
        raise ValueError("Symlink ancestor rejected")
    path.mkdir(parents=True, exist_ok=True, mode=mode)
    if path.stat().st_uid != os.geteuid():
        raise ValueError("Unexpected directory owner")
    path.chmod(mode)
    if os.geteuid() == 0:
        try:
            os.chown(path, 0, grp.getgrnam("hestiaweb").gr_gid)
        except KeyError:
            pass
    return path

def atomic_json(path, value, mode=0o640):
    path = Path(path)
    parent = private_directory(path.parent)
    fd, temporary = tempfile.mkstemp(prefix=".pro-", dir=parent)
    try:
        os.fchmod(fd, mode)
        if os.geteuid() == 0:
            try:
                os.fchown(fd, 0, grp.getgrnam("hestiaweb").gr_gid)
            except KeyError:
                pass
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n"); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)

@contextmanager
def lock(path):
    path = Path(path)
    private_directory(path.parent, 0o700)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.geteuid() or st.st_mode & 0o077 or st.st_nlink != 1:
            raise ValueError('Unsafe lock file')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)

def require_root():
    if os.geteuid() != 0:
        raise PermissionError("This operation requires root")

def private_read(path, limit=1048576):
    """Open secrets without following links; reject unsafe ancestors and special files."""
    path = Path(path)
    if not path.is_absolute() or any(p.is_symlink() for p in path.parents):
        raise ValueError("Unsafe secret path")
    for parent in path.parents:
        st = parent.stat()
        if st.st_uid != 0 or (st.st_mode & 0o022 and not st.st_mode & stat.S_ISVTX):
            raise ValueError("Secret parent is not root controlled")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_uid != 0 or st.st_mode & 0o077 or not 0 < st.st_size <= limit:
            raise ValueError("Secret must be a non-empty root-owned regular file, mode 0600")
        with os.fdopen(fd, 'r', closefd=False) as stream:
            return stream.read(limit + 1)
    finally:
        os.close(fd)

def safe_environment():
    """Do not inherit shell hooks, loader injection, cloud credentials or backend overrides."""
    return {'PATH': '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
            'HOME': '/root', 'LC_ALL': 'C', 'LANG': 'C'}
