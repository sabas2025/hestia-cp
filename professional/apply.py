#!/usr/bin/env python3
"""Idempotent, version-aware deployment of this overlay; never install the Hestia stack."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import uuid
from ops import atomic_json, config, private_directory, private_read, require_root

VERSION = "1.10.5"
MARKER = "# HESTIA_PROFESSIONAL_HOOK_V1"
EXPERIMENTAL = {'resources.py', 'antivirus.py', 'cluster.py', 'incremental.py', 'nosql.py', 'enterprise.py',
                'enterprise.example.json', 'resources.example.json', 'topology.example.json',
                'incremental.example.json', 'nosql.example.json'}

def verify_deployment(root):
    """Use the saved root-private manifest, never the installed files as their own reference."""
    record = json.loads(private_read(root / 'professional/deployment.json', 4194304))
    if not isinstance(record.get('files'), list) or not record['files']:
        raise ValueError('Deployment manifest missing')
    mismatch = []; seen = set()
    for item in record['files']:
        path = Path(item['file'])
        if path.is_absolute() or '..' in path.parts or str(path) in seen:
            raise ValueError('Unsafe deployment manifest')
        seen.add(str(path)); target = root / path
        if target.is_symlink() or any(p.is_symlink() for p in target.parents) or not target.is_file() or target.stat().st_uid != 0 or target.stat().st_mode & 0o777 != item.get('mode') or hashlib.sha256(target.read_bytes()).hexdigest() != item['sha256']:
            mismatch.append(str(path))
    if (root / 'web/fm').exists() or (root / 'web/fm').is_symlink():
        mismatch.append('web/fm:unapproved-component')
    return {'state': 'review-required' if mismatch else 'verified', 'mismatched': mismatch,
            'overlay': record['overlay'], 'core_overwritten': False}

def atomic_file(target, content, mode=0o644):
    if target.is_symlink():
        raise ValueError(f"Symlink target rejected: {target.name}")
    target.parent.mkdir(parents=True, exist_ok=True)
    if any(p.is_symlink() for p in [target.parent, *target.parent.parents] if p != p.parent):
        raise ValueError("Symlink parent rejected")
    fd, name = tempfile.mkstemp(prefix=".pro-", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content); stream.flush(); os.fsync(stream.fileno())
        os.chmod(name, mode); os.replace(name, target)
    finally:
        if os.path.exists(name): os.unlink(name)

def patch_runtime(root, source):
    """Only replace the expected download line, retaining the current upstream file."""
    target = root / "bin/v-add-sys-filemanager"
    if not target.is_file():
        raise ValueError("Hestia File Manager command missing")
    old = 'wget "$FM_URL" --quiet -O "$FM_ZIP"'
    new = '''# HESTIA_PROFESSIONAL_LOCKED_FILEMANAGER
source "$HESTIA/professional/hst-common.sh" || exit 1
HST_BUNDLE_ROOT="$HESTIA/professional/bundle"
hst_asset filemanager "$FM_ZIP"'''
    text = target.read_text()
    guard = "# HESTIA_PROFESSIONAL_FILEMANAGER_REVIEW\nprintf '%s\\n' 'File Manager disabled pending dependency remediation; use a reviewed editor integration.' >&2\nexit 1\n"
    if 'HESTIA_PROFESSIONAL_FILEMANAGER_REVIEW' not in text:
        anchor = 'FM_INSTALL_DIR="$HESTIA/web/fm"'
        if text.count(anchor) != 1: raise ValueError('File Manager gate contract changed')
        text = text.replace(anchor, anchor + '\n' + guard)
    if new in text:
        if target.read_text() != text: atomic_file(target, text.encode(), 0o755)
        return False
    if text.count(old) != 1:
        raise ValueError("File Manager download contract changed; review overlay before applying")
    # Original is retained for review; never replay a stale full script on upgrade.
    backup = root / "professional/original-v-add-sys-filemanager"
    if not backup.exists(): atomic_file(backup, target.read_bytes(), 0o600)
    atomic_file(target, text.replace(old, new).encode(), 0o755)
    return True

def patch_dependency_commands(root):
    composer = root / "bin/v-add-user-composer"
    text = composer.read_text()
    if '# HESTIA_PROFESSIONAL_COMPOSER' not in text:
        anchor = 'COMPOSER_BIN="$COMPOSER_DIR/composer"'
        if text.count(anchor) != 1 or 'COMPOSER_SETUP_FILE=$(mktemp)' not in text:
            raise ValueError('Composer command contract changed')
        helper = '''
# HESTIA_PROFESSIONAL_COMPOSER
pro_install_composer() (
    source "$HESTIA/professional/hst-common.sh" || exit 1
    HST_BUNDLE_ROOT="$HESTIA/professional/bundle"
    local temporary
    temporary=$(mktemp) || exit 1
    trap 'rm -f -- "$temporary"' EXIT
    hst_asset composer-phar "$temporary"
    install -o "$user" -g "$user" -m 0755 "$temporary" "$COMPOSER_BIN" || exit 1
)
'''
        text = text.replace(anchor, anchor + '\n' + helper)
        text = text.replace('COMPOSER_HOME="$HOMEDIR/$user/.config/composer" user_exec "$COMPOSER_BIN" --quiet self-update', 'pro_install_composer')
        start = text.index('COMPOSER_SETUP_FILE=$(mktemp)')
        end = text.index('#----------------------------------------------------------#', start)
        text = text[:start] + 'pro_install_composer\n\n' + text[end:]
        backup = root / 'professional/original-v-add-user-composer'
        if not backup.exists(): atomic_file(backup, composer.read_bytes(), 0o600)
        atomic_file(composer, text.encode(), 0o755)
    roundcube = root / "bin/v-add-sys-roundcube"
    text = roundcube.read_text()
    if '# HESTIA_PROFESSIONAL_ROUNDCUBE' not in text:
        start = text.index('download_rc() {')
        end = text.index('\n#----------------------------------------------------------#', start)
        text = text[:start] + '''# HESTIA_PROFESSIONAL_ROUNDCUBE
download_rc() {
    [[ "$rc_v" == 1.7.4 ]] || fail 'Roundcube lock must be reviewed for this version'
    source "$HESTIA/professional/hst-common.sh" || exit 1
    HST_BUNDLE_ROOT="$HESTIA/professional/bundle"
    hst_asset roundcube "$RC_INSTALL_DIR/$RC_FILE"
    tar tzf "$RC_INSTALL_DIR/$RC_FILE" >/dev/null || fail 'Invalid locked Roundcube archive'
}
update_rc_modules() {
    # The complete distribution ships dependencies. Do not resolve new code as root.
    [[ -f "$RC_INSTALL_DIR/vendor/autoload.php" ]] || fail 'Roundcube vendor dependencies missing'
}
''' + text[end:]
        backup = root / 'professional/original-v-add-sys-roundcube'
        if not backup.exists(): atomic_file(backup, roundcube.read_bytes(), 0o600)
        atomic_file(roundcube, text.encode(), 0o755)

def quarantine_file_manager(root):
    """Move the optional UI outside the web root without deleting any account data."""
    target = root / 'web/fm'
    if not target.exists() and not target.is_symlink(): return None
    if any(p.is_symlink() for p in target.parents): raise ValueError('Unsafe File Manager parent')
    folder = private_directory(root / 'professional/quarantine', 0o700)
    saved = folder / ('filemanager-' + uuid.uuid4().hex)
    os.rename(target, saved)
    conf = root / 'conf/hestia.conf'; text = conf.read_text()
    import re
    if re.search(r"(?m)^FILE_MANAGER='[^'\r\n]*'$", text):
        text = re.sub(r"(?m)^FILE_MANAGER='[^'\r\n]*'$", "FILE_MANAGER='false'", text)
    else: text += "\nFILE_MANAGER='false'\n"
    st = conf.stat(); atomic_file(conf, text.encode(), st.st_mode & 0o777); os.chown(conf, st.st_uid, st.st_gid)
    return str(saved.relative_to(root))

def apply_files(root, source, refresh=False, quarantine_filemanager=False):
    if root.is_symlink() or not (root / "web/inc/main.php").is_file():
        raise ValueError("Destination is not an installed Hestia tree")
    live = config(root / "conf/hestia.conf").get("VERSION")
    if live and live != VERSION:
        if refresh:
            # Retain official security update; disable the custom page rather than replay old core.
            atomic_json(root / 'data/professional/deployment-status.json', {'state':'review-required','version':live,'mismatched':['hestia-version']})
            return {"status": "review-required", "version": live, "core_overwritten": False}
        raise ValueError("Review required for this Hestia version")
    if root.resolve() == source.resolve():
        if not refresh:
            raise ValueError('Deployment requires an independently reviewed source tree')
        try:
            result = verify_deployment(root)
        except (ValueError, KeyError, OSError):
            result = {'state': 'review-required', 'mismatched': ['manifest-unavailable'], 'core_overwritten': False}
        atomic_json(root / 'data/professional/deployment-status.json', result)
        return {**result, 'status': result['state']}
    manifest = []
    mfa_contract = json.loads((source / 'professional/mfa-contract.json').read_text())
    # Never overwrite a local MFA hotfix just because the Hestia version string is unchanged.
    for relative, original_hash in mfa_contract.items():
        live_path = root / relative
        expected = source / relative
        if live_path.is_symlink() or any(p.is_symlink() for p in live_path.parents):
            raise ValueError('Unsafe authentication path')
        allowed = original_hash if isinstance(original_hash, list) else [original_hash]
        if live_path.is_file() and live_path.read_bytes() != expected.read_bytes() and hashlib.sha256(live_path.read_bytes()).hexdigest() not in allowed:
            raise ValueError('MFA contract changed; review local authentication modifications')
    fm = root / 'web/fm'
    if fm.exists() or fm.is_symlink():
        if not quarantine_filemanager:
            raise ValueError('Existing File Manager requires review. Use --quarantine-filemanager to preserve it outside web root and disable its UI.')
        quarantine_file_manager(root)
    files = [p for p in (source / "web/professional").glob("*") if p.is_file()]
    files += [source / 'web/inc/2fa' / name for name in ('local-provider.php', 'secret.php', 'check.php')]
    files += [source / 'bin' / name for name in ('v-add-user-2fa', 'v-check-user-2fa', 'v-professional-mfa', 'v-backup-user')]
    files += [source / name for name in ('web/edit/user/index.php', 'web/templates/pages/edit_user.php', 'web/login/index.php', 'web/reset2fa/index.php', 'web/templates/pages/login/login_2.php')]
    files += [source / "web/css/themes/custom/professional.css"]
    files += [source / 'professional/mfa-logrotate.conf']
    files += [p for p in (source / "professional").glob("*") if p.suffix in (".py", ".service", ".timer", ".json") and p.is_file() and p.name != 'deployment.json'
              and p.name not in EXPERIMENTAL and not any(tag in p.name for tag in ('enterprise', 'antivirus', 'cluster', 'incremental'))]
    for file in files:
        destination = root / file.relative_to(source)
        if destination.is_symlink() or any(p.is_symlink() for p in destination.parents): raise ValueError('Unsafe deployment target')
    for file in files:
        destination = root / file.relative_to(source)
        # During a refresh source==root, files already live in place.
        if file.resolve() != destination.resolve():
            atomic_file(destination, file.read_bytes(), 0o755 if file.suffix == ".py" or file.parent.name == 'bin' else 0o644)
        manifest.append({"file": str(destination.relative_to(root)), "sha256": hashlib.sha256(file.read_bytes()).hexdigest(), 'mode': destination.stat().st_mode & 0o777})
    common = source / "install/hst-common.sh"
    asset_lock = source / "install/assets.lock.tsv"
    if common.exists():
        atomic_file(root / "professional/hst-common.sh", common.read_bytes())
        atomic_file(root / "professional/bundle/install/assets.lock.tsv", asset_lock.read_bytes())
    for directory in ("data/professional", "data/professional/jobs", "data/professional/backups"):
        private_directory(root / directory)
    # Read-only user-scoped API profile. No wildcard or privilege escalation.
    profile = "ROLE='user'\nCOMMANDS='v-list-web-domains,v-list-dns-domains,v-list-mail-domains,v-list-databases,v-list-cron-jobs,v-list-user-backups'\n"
    atomic_file(root / "data/api/professional-readonly", profile.encode(), 0o640)
    patch_runtime(root, source)
    patch_dependency_commands(root)
    panel = root / "web/templates/includes/panel.php"
    link = '<a class="pro-home-link" href="/professional/">Central de hospedagem · Visão geral</a>\n'
    text = panel.read_text()
    if link not in text:
        # Add a link without replacing upstream HTML, authorization or scripts.
        atomic_file(panel, (link + text).encode())
    for relative in ('bin/v-add-sys-filemanager', 'bin/v-add-user-composer', 'bin/v-add-sys-roundcube'):
        manifest.append({'file': relative, 'sha256': hashlib.sha256((root / relative).read_bytes()).hexdigest(), 'mode': (root / relative).stat().st_mode & 0o777})
    policy = json.loads((source / 'professional/component-policy.json').read_text())
    atomic_file(root / "professional/deployment.json", json.dumps({"overlay": policy['overlay_version'], "hestia": VERSION, "files": manifest}, indent=2).encode(), 0o600)
    atomic_json(root / 'data/professional/deployment-status.json', {'state': 'verified', 'mismatched': [], 'overlay': policy['overlay_version']})
    return {"status": "applied", "version": VERSION, "files": len(manifest)}

def enable_services(root):
    if root != Path("/usr/local/hestia"):
        raise ValueError("System integration is limited to /usr/local/hestia")
    require_root()
    atomic_file(Path('/etc/logrotate.d/hestia-professional-mfa'), (root / 'professional/mfa-logrotate.conf').read_bytes(), 0o644)
    hook = Path("/etc/hestiacp/hooks/post_install.sh")
    saved = hook.with_name("post_install.before-professional.sh")
    if hook.exists() and MARKER not in hook.read_text():
        if saved.exists():
            raise ValueError("Existing saved hook found; review before chaining")
        atomic_file(saved, hook.read_bytes(), hook.stat().st_mode & 0o777)
    wrapper = f'''#!/bin/bash
{MARKER}
status=0
if [[ -f /etc/hestiacp/hooks/post_install.before-professional.sh ]]; then
    /etc/hestiacp/hooks/post_install.before-professional.sh "$@" || status=$?
fi
/usr/bin/python3 /usr/local/hestia/professional/apply.py --root /usr/local/hestia --source /usr/local/hestia --refresh || status=$?
exit "$status"
'''
    atomic_file(hook, wrapper.encode(), 0o750)
    for name in ("hestia-professional-health.service", "hestia-professional-health.timer", "hestia-professional-backup@.service", "hestia-professional-backup@.timer", "hestia-professional-cloud-backup@.service", "hestia-professional-cloud-backup@.timer"):
        atomic_file(Path("/etc/systemd/system") / name, (root / "professional" / name).read_bytes())
    subprocess.run(["systemctl", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "enable", "--now", "hestia-professional-health.timer"], check=True)
    # Backup timers are deliberately not enabled until a real destination is configured.

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("/usr/local/hestia"))
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--enable-services", action="store_true")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--quarantine-filemanager", action="store_true")
    args = parser.parse_args(); require_root()
    result = apply_files(args.root.absolute(), args.source.resolve(), args.refresh, args.quarantine_filemanager)
    if args.enable_services and result["status"] == "applied": enable_services(args.root.absolute())
    print(json.dumps(result, indent=2))
    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f"Overlay stopped: {error}", file=sys.stderr); sys.exit(1)
