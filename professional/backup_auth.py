#!/usr/bin/env python3
"""Remove active MFA provisioning secrets only from the private native backup copy."""
import os
from pathlib import Path
import re
import stat
import sys
from apply import atomic_file
from ops import config, require_root

def sanitize(path):
    if not path.is_absolute() or path.name != 'user.conf' or path.parent.name != 'hestia':
        raise ValueError('Only the native staging copy is accepted')
    if path.is_symlink() or any(p.is_symlink() for p in path.parents): raise ValueError('Symlinks refused')
    parent = path.parent.parent.stat(); st = path.stat()
    if parent.st_uid != 0 or parent.st_mode & 0o077 or not stat.S_ISDIR(parent.st_mode):
        raise ValueError('Private root-owned staging directory required')
    if st.st_uid != 0 or not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_size > 2097152:
        raise ValueError('Unsafe backup configuration')
    values = config(path)
    had_factor = bool(values.get('TWOFA'))
    text = path.read_text()
    updates = [('TWOFA',''),('QRCODE','')]
    if had_factor: updates.append(('LOGIN_DISABLED','yes'))
    for key, value in updates:
        pattern = r"(?m)^" + key + r"='[^'\r\n]*'$"
        count = len(re.findall(pattern,text))
        if count > 1: raise ValueError('Ambiguous backup configuration')
        if count: text = re.sub(pattern,key+"='"+value+"'",text)
        else: text += '\n'+key+"='"+value+"'\n"
    if had_factor: text += "\nPRO_MFA_REENROLL='yes'\n"
    atomic_file(path,text.encode(),st.st_mode & 0o777);os.chown(path,st.st_uid,st.st_gid)
    return had_factor

if __name__ == '__main__':
    try:
        require_root()
        if len(sys.argv)!=2: raise ValueError('One staging path required')
        sanitize(Path(sys.argv[1]))
    except (ValueError,OSError):
        print('MFA backup sanitization refused; no archive should be published.',file=sys.stderr)
        sys.exit(1)
