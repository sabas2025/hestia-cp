#!/usr/bin/env python3
"""Consistent Hestia tar + encrypted Restic copy, checks and isolated restore drills."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from ops import atomic_json, config, lock, private_read, require_root, username, utcnow

def settings(path):
    stat = path.stat()
    if path.is_symlink() or stat.st_uid != 0 or stat.st_mode & 0o077:
        raise ValueError("Backup configuration must be a root-owned regular file with mode 0600")
    result = json.loads(private_read(path))
    allowed = {"repository", "password_file", "keep_daily", "rpo_hours", "rto_minutes"}
    if set(result) - allowed:
        raise ValueError("Unknown backup configuration key")
    repository = result.get("repository", "")
    if not isinstance(repository, str) or not repository.startswith(("/", "sftp:", "s3:", "rclone:")) or any(c in repository for c in "\r\n"):
        raise ValueError("Use an absolute path or sftp:, s3:, rclone: repository")
    if re.search(r"https?://[^/@\s]+:[^/@\s]+@", repository):
        raise ValueError("Do not embed passwords in repository URLs")
    if repository.startswith('s3:http://'):
        raise ValueError('S3 requires TLS; use the reviewed multicloud configuration')
    if repository.startswith('/') and any(part in ('public', 'public_html') for part in Path(repository).parts):
        raise ValueError('Backup repository must be outside web-public directories')
    password = Path(result.get("password_file", ""))
    if not password.is_absolute() or password.is_symlink() or not password.is_file():
        raise ValueError("Password must be an absolute non-symlink regular file")
    st = password.stat()
    if st.st_uid != 0 or st.st_mode & 0o077 or st.st_size == 0:
        raise ValueError("Password file must be non-empty, root-owned and mode 0600")
    private_read(password)
    for key, default in (("keep_daily", 7), ("rpo_hours", 24), ("rto_minutes", 120)):
        value = result.get(key, default)
        if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 3650:
            raise ValueError("Invalid numeric backup setting")
        result[key] = value
    return result

def checked(args, env=None):
    # Capture output in a root-private log; never print commands with repository credentials.
    result = subprocess.run(args, env=env, capture_output=True, text=True, timeout=21600)
    if result.returncode:
        raise RuntimeError(f"{Path(args[0]).name} failed with status {result.returncode}; review service journal")
    return result.stdout

def execute(action, user, cfg, root, runner=checked):
    user = username(user)
    if not (root / "data/users" / user / "user.conf").is_file():
        raise ValueError("Hestia user does not exist")
    conf = config(root / "conf/hestia.conf")
    backup_dir = Path(conf.get("BACKUP", "/backup"))
    if not backup_dir.is_absolute():
        raise ValueError("Backup folder must be absolute")
    progress = {"schema": 1, "user": user, "action": action, "state": "running", "step": "starting", "started_at": utcnow(), "updated_at": utcnow()}
    path = root / "data/professional/jobs" / f"{user}.json"
    env = {**os.environ, "RESTIC_REPOSITORY": cfg["repository"], "RESTIC_PASSWORD_FILE": cfg["password_file"]}
    env.pop("RESTIC_PASSWORD", None)
    def step(name):
        progress.update(step=name, updated_at=utcnow()); atomic_json(path, progress)
    with lock(root / "data/professional-locks" / f"backup-{user}.lock"):
        started = time.monotonic()
        try:
            step("starting")
            if action == "init":
                step("initialize-encrypted-repository")
                runner(["restic", "init"], env=env)
            elif action == "run":
                step("consistent-hestia-backup")
                before = {p: p.stat().st_mtime_ns for p in backup_dir.glob(f"{user}.*.tar")}
                runner([str(root / "bin/v-backup-user"), user], env=None)
                candidates = [p for p in backup_dir.glob(f"{user}.*.tar") if not p.is_symlink() and p.stat().st_size > 0 and (p not in before or p.stat().st_mtime_ns > before[p])]
                if not candidates:
                    raise RuntimeError("No newly completed Hestia archive was found")
                archive = max(candidates, key=lambda p: p.stat().st_mtime_ns)
                step("encrypted-remote-copy")
                runner(["restic", "backup", "--tag", "hestia-" + user, str(archive)], env=env)
                step("verify-repository")
                runner(["restic", "check"], env=env)
            elif action == "check":
                step("verify-repository-data")
                runner(["restic", "check", "--read-data-subset=5%"], env=env)
            elif action == "retention":
                step("apply-user-retention")
                runner(["restic", "forget", "--tag", "hestia-" + user, "--keep-daily", str(cfg["keep_daily"]), "--group-by", "host,tags", "--prune"], env=env)
            elif action == "drill":
                step("isolated-restore-drill")
                with tempfile.TemporaryDirectory(prefix="hestia-restore-drill-") as temporary:
                    stats = json.loads(runner(["restic", "stats", "latest", "--tag", "hestia-" + user, "--mode", "restore-size", "--json"], env=env))
                    size = stats.get('total_size')
                    if not isinstance(size, int) or size < 0 or shutil.disk_usage(temporary).free < size * 1.2:
                        raise RuntimeError('Restore drill needs a valid size estimate and at least 20% free space margin')
                    runner(["restic", "restore", "latest", "--tag", "hestia-" + user, "--target", temporary, "--verify"], env=env)
                    restored = [p for p in Path(temporary).rglob(f"{user}.*.tar") if p.is_file() and not p.is_symlink()]
                    if not restored:
                        raise RuntimeError("Restore drill did not produce an archive")
                    for archive in restored:
                        runner(["tar", "-tf", str(archive)], env=None)
                # This validates Restic recovery and archive readability, not a live application restore.
                progress["drill_scope"] = "restic-restore-and-tar-readability"
            progress.update(state="succeeded", step="completed", completed_at=utcnow(), updated_at=utcnow(), rpo_hours=cfg["rpo_hours"], rto_minutes=cfg["rto_minutes"], duration_seconds=round(time.monotonic() - started, 2))
            atomic_json(path, progress)
            if action in ("run", "drill"):
                atomic_json(root / "data/professional/backups" / f"{user}-{action}.json", progress)
            return progress
        except Exception:
            progress.update(state="failed", step="operation-failed", completed_at=utcnow(), updated_at=utcnow())
            atomic_json(path, progress)
            raise

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("init", "run", "check", "drill", "retention", "plan"))
    parser.add_argument("--user", required=True, type=username)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--root", type=Path, default=Path("/usr/local/hestia"))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(); require_root()
    cfg = settings(args.config)
    if args.action == "plan" or not args.apply:
        print(json.dumps({"mode": "plan", "action": args.action, "user": args.user, "rpo_hours": cfg["rpo_hours"], "rto_minutes": cfg["rto_minutes"], "keep_daily": cfg["keep_daily"], "repository_configured": True}, indent=2)); return 0
    print(json.dumps(execute(args.action, args.user, cfg, args.root), ensure_ascii=False, indent=2)); return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, RuntimeError, OSError, subprocess.TimeoutExpired) as error:
        # Runtime messages are intentionally generic and cannot contain repository passwords.
        print(f"Backup operation failed: {type(error).__name__}; check configuration and journal", file=sys.stderr)
        sys.exit(1)
