#!/usr/bin/env python3
"""Produce a read-only HUB migration checklist; never change DNS or application data."""
import argparse
import json
from pathlib import Path
import subprocess
from ops import username

def inspect(public, php):
    public = public.resolve()
    if public.name != "public" or not public.is_dir():
        raise ValueError("Provide the existing HUB public/ directory")
    result = subprocess.run([php, "-r", "echo json_encode(['version'=>PHP_VERSION,'extensions'=>get_loaded_extensions()]);"], capture_output=True, text=True, timeout=15)
    if result.returncode:
        raise ValueError("PHP inspection failed")
    runtime = json.loads(result.stdout)
    required = ["pdo_mysql", "curl", "openssl", "mbstring", "xml", "zip", "intl"]
    present = {x.lower() for x in runtime["extensions"]}
    missing = [x for x in required if x not in present]
    sensitive = [name for name in (".env", "config.php", "composer.json", "composer.lock", "backup.sql") if (public / name).exists()]
    return {"mode": "inspection", "php_version": runtime["version"], "php84": runtime["version"].startswith("8.4."),
            "missing_extensions": missing, "sensitive_files_in_public": sensitive,
            "htaccess_present": (public / ".htaccess").is_file(),
            "manual_acceptance": ["Dedicated non-admin Linux user and database", "Consistent database and file backup", "Restore into isolated staging and run application tests", "Match PHP CLI and FPM versions", "Test Tiny/VSM OAuth and callbacks with approved test data", "Test jobs, retries and concurrency", "Verify HTTPS and HTTP denial of private files", "Record RPO/RTO and DNS rollback procedure"],
            "changes_applied": False}

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public", required=True, type=Path)
    parser.add_argument("--php", default="php8.4")
    args = parser.parse_args()
    print(json.dumps(inspect(args.public, args.php), ensure_ascii=False, indent=2))
