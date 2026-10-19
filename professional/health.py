#!/usr/bin/env python3
"""Read-only health inspection; --write publishes a non-secret dashboard snapshot."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import ssl
import sys
from ops import atomic_json, command, config, require_root, utcnow
import security
from apply import verify_deployment

def collect(root=Path("/usr/local/hestia"), runner=command):
    conf = config(root / "conf/hestia.conf")
    data = {"schema": 1, "generated_at": utcnow(), "version": conf.get("VERSION", "unknown"),
            "checks": [], "services": [], "php": [], "certificate": {"status": "unknown"}}
    def check(name, state, detail):
        data["checks"].append({"name": name, "state": state, "detail": detail})
    usage = shutil.disk_usage("/")
    percent = round(100 * usage.used / max(usage.total, 1), 1)
    check("Disco", "critical" if percent >= 95 else "warning" if percent >= 85 else "ok", f"{percent}% utilizado")
    stat = os.statvfs("/")
    inodes = round(100 * (stat.f_files - stat.f_favail) / max(stat.f_files, 1), 1)
    check("Inodes", "critical" if inodes >= 95 else "warning" if inodes >= 85 else "ok", f"{inodes}% utilizado")
    required = {"hestia": "hestia"}
    for key in ("WEB_SYSTEM", "PROXY_SYSTEM", "DB_SYSTEM", "DNS_SYSTEM", "MAIL_SYSTEM", "IMAP_SYSTEM", "FIREWALL_EXTENSION"):
        for value in conf.get(key, "").replace(",", " ").split():
            if value and value not in ("no", "none"):
                service = {"pgsql": "postgresql", "mysql": "mariadb" if shutil.which("mariadbd") else "mysql"}.get(value, value)
                required[value] = service
    if conf.get("WEB_BACKEND") == "php-fpm":
        for path in sorted(Path("/etc/php").glob("*/fpm/php-fpm.conf")):
            required[f"php{path.parts[3]}-fpm"] = f"php{path.parts[3]}-fpm"
    for label, service in sorted(required.items()):
        # Only configuration-selected unit names consisting of safe characters.
        if not service.replace("-", "").replace(".", "").isalnum():
            continue
        status, output = runner(["systemctl", "is-active", service], timeout=10)
        healthy = status == 0 and output.strip() == "active"
        data["services"].append({"name": label, "state": "ok" if healthy else "critical"})
        check(label, "ok" if healthy else "critical", "Ativo" if healthy else "Serviço indisponível")
    for version in ("8.2", "8.3", "8.4", "8.5"):
        binary = shutil.which("php" + version)
        if binary:
            status, output = runner([binary, "-r", "echo PHP_VERSION;"], timeout=10)
            data["php"].append({"version": version, "cli": output.strip() if status == 0 else "unknown"})
    cert = root / "ssl/certificate.crt"
    if cert.is_file():
        status, output = runner(["openssl", "x509", "-in", str(cert), "-noout", "-enddate", "-issuer", "-subject"], timeout=10)
        try:
            endline = next(x for x in output.splitlines() if x.startswith("notAfter="))
            expires = datetime.fromtimestamp(ssl.cert_time_to_seconds(endline.split("=", 1)[1]), timezone.utc)
            days = (expires - datetime.now(timezone.utc)).days
            issuer = next(x.split("=", 1)[1] for x in output.splitlines() if x.startswith("issuer="))
            subject = next(x.split("=", 1)[1] for x in output.splitlines() if x.startswith("subject="))
            state = "critical" if days < 0 else "warning" if days < 21 or issuer == subject else "ok"
            data["certificate"] = {"status": state, "days": days, "expires": expires.isoformat(), "self_signed": issuer == subject}
            check("Certificado do painel", state, f"{days} dias restantes" + ("; autoassinado" if issuer == subject else ""))
        except (ValueError, StopIteration, OverflowError):
            check("Certificado do painel", "critical", "Não foi possível validar o certificado")
    else:
        check("Certificado do painel", "critical", "Certificado ausente")
    # The command runner contract for health reports returns a status/output tuple.
    def security_runner(args):
        code, output = runner(args, timeout=15)
        if code: raise RuntimeError('Security collector failed')
        return output
    data['protection'] = security.collect(root, security_runner)
    admins = [config(p) for p in (root / 'data/users').glob('*/user.conf') if not p.is_symlink()]
    admins = [a for a in admins if a.get('ROLE') == 'admin' and a.get('SUSPENDED') == 'no']
    missing_twofa = sum(not a.get('TWOFA') for a in admins)
    data['twofa_admins'] = {'active': len(admins), 'without_twofa': missing_twofa}
    check('A2F dos administradores', 'warning' if missing_twofa or not admins else 'ok',
          f'{missing_twofa} de {len(admins)} administradores sem A2F' if admins else 'Sem inventário de administradores')
    for key, title in [('waf', 'Módulo WAF'), ('fail2ban', 'Fail2Ban')]:
        available = data['protection'][key] == 'available'
        check(title, 'ok' if available else 'warning', 'Disponível; revise política efetiva' if available else 'Sem confirmação de funcionamento')
    try:
        deployment = verify_deployment(root)
        check('Integridade da camada', 'ok' if deployment['state'] == 'verified' else 'critical',
              'Manifesto confere' if deployment['state'] == 'verified' else 'Arquivos divergentes; revisar atualização')
    except (ValueError, KeyError, OSError):
        check('Integridade da camada', 'warning', 'Manifesto indisponível; reaplique de uma origem revisada')
    failed = 0; stale_jobs = 0; job_count = 0
    for path in (root / 'data/professional/jobs').glob('*.json'):
        if path.is_symlink() or path.stat().st_size > 1048576: continue
        try:
            job = json.loads(path.read_text())
            job_count += 1
            failed += job.get('state') == 'failed'
            stamp = datetime.fromisoformat(job.get('updated_at', '')).timestamp()
            stale_jobs += job.get('state') == 'running' and datetime.now(timezone.utc).timestamp() - stamp > 86400
        except (ValueError, OSError, TypeError): stale_jobs += 1
    check('Tarefas de backup', 'warning' if failed or stale_jobs or not job_count else 'ok',
          f'{failed} falhas e {stale_jobs} tarefas sem atualização; revise por conta' if job_count else 'Nenhuma execução registrada; configure e teste os backups')
    data["status"] = "critical" if any(c["state"] == "critical" for c in data["checks"]) else "warning" if any(c["state"] == "warning" for c in data["checks"]) else "ok"
    return data

def installation_checks(root, runner=command):
    conf = config(root / "conf/hestia.conf")
    commands = [[str(root / "nginx/sbin/hestia-nginx"), "-t"]]
    if conf.get("PROXY_SYSTEM") == "nginx" or conf.get("WEB_SYSTEM") == "nginx":
        commands.append(["nginx", "-t"])
    if conf.get("WEB_SYSTEM") == "apache2":
        commands.append(["apache2ctl", "configtest"])
    commands.append(["/usr/sbin/sshd", "-t"])
    if conf.get("WEB_BACKEND") == "php-fpm":
        for path in Path("/etc/php").glob("*/fpm/php-fpm.conf"):
            commands.append([f"php-fpm{path.parts[3]}", "-t"])
    failures = [args[0] for args in commands if runner(args, timeout=30)[0] != 0]
    return failures

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("/usr/local/hestia"))
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--installation-check", action="store_true")
    args = parser.parse_args()
    if args.write or args.installation_check:
        require_root()
    data = collect(args.root)
    if args.installation_check:
        failures = installation_checks(args.root)
        data["configuration_failures"] = failures
        if failures:
            data["status"] = "critical"
    if args.write or args.installation_check:
        atomic_json(args.root / "data/professional/health.json", data)
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 2 if data["status"] == "critical" else 0

if __name__ == "__main__":
    sys.exit(main())
