#!/usr/bin/env python3
"""Read-only audit of a supplied source tree; service/cloud calls are fixture runners.

Usage: python3 reproduce_findings.py --source PATH --php PHP_BINARY --output FILE
No installation, VPS access, firewall action or network backup is performed.
"""
import argparse
from html.parser import HTMLParser
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from urllib.parse import parse_qs, urlsplit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--php', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = args.source.resolve()
    sys.path[:0] = [str(root / 'professional'), str(root / 'professional/tests')]
    import cloud_backup as cloud
    import security
    from test_platform import CloudTests, ProtectionTests, archive
    from test_operations import OperationsTests, apply_overlay

    class Links(HTMLParser):
        def __init__(self):
            super().__init__(); self.urls = []
        def handle_starttag(self, tag, attrs):
            href = dict(attrs).get('href', '')
            if tag == 'a' and href.startswith('/edit/user/'):
                self.urls.append(href)

    php = args.php
    rendered = subprocess.check_output([php, '-n', '-r',
        '$_SESSION=["token"=>"AUDIT_SYNTHETIC_TOKEN"];require $argv[1];',
        str(root / 'professional/tests/render_preview.php')], text=True)
    links = Links(); links.feed(rendered)
    native = (root / 'web/inc/main.php').read_text()
    begin = native.index('function verify_csrf(')
    end = native.index('\n}\n', begin) + 2
    checker = native[begin:end]
    csrf_results = []
    for url in links.urls:
        query = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
        result = subprocess.check_output([php, '-n', '-d', 'display_errors=0', '-r',
            checker + ';$_SESSION=["token"=>"AUDIT_SYNTHETIC_TOKEN"];'
            'echo json_encode(verify_csrf(json_decode($argv[1],true),true));',
            json.dumps(query)], text=True, stderr=subprocess.DEVNULL)
        csrf_results.append({'url': url, 'native_csrf_accepts': json.loads(result)})

    with tempfile.TemporaryDirectory(prefix='hestia-audit-security-') as td:
        fs = Path(td)
        hestia, cfg = ProtectionTests().fixture(fs)
        runner = lambda command: 'security2_module' if command == ['apache2ctl', '-M'] else 'ok'
        security.apply_profile(fs, hestia, cfg, runner)
        second = security.apply_profile(fs, hestia, {**cfg, 'waf': False}, runner)
        policy_retained = 'SecRuleEngine On' in (fs / security.WAF).read_text()
        security_proof = {'snapshot_waf': second['waf'], 'managed_rule_engine_still_on': policy_retained,
                          'service_commands_simulated': True}

    with tempfile.TemporaryDirectory(prefix='hestia-audit-backup-') as td:
        fs = Path(td); fixture = CloudTests(); folder = fixture.account(fs)
        path, _, _ = fixture.fixture(fs); cfg = cloud.settings(path)
        def success(command, env=None):
            if command[0].endswith('v-backup-user'):
                archive(folder / 'testuser.new.tar', ['web/site.invalid/domain_data.tar.gz',
                        'db/app_main/app_main.mysql.sql.gz'])
            if command[:2] == ['restic', 'backup']:
                return json.dumps({'message_type': 'summary', 'snapshot_id': 'a' * 64})
            return ''
        cloud.execute('run', 'testuser', cfg, fs, runner=success)
        def failure(command, env=None):
            if command[:2] == ['restic', 'backup']:
                raise RuntimeError('synthetic provider failure')
            return success(command, env)
        failed = cloud.execute('run', 'testuser', cfg, fs, runner=failure)
        target = json.loads((fs / 'data/professional/backups/testuser-main-copy-run.json').read_text())
        backup_proof = {'latest_job_state': failed['state'], 'target_snapshot_state': target['state'],
                        'target_snapshot_retains_last_success': True, 'cloud_commands_simulated': True}

    with tempfile.TemporaryDirectory(prefix='hestia-audit-refresh-') as td:
        fs = Path(td); OperationsTests().fixture_hestia(fs)
        apply_overlay.apply_files(fs, root)
        target = fs / 'web/inc/2fa/secret.php'
        # Simulate a package replacing a protected file while VERSION stays unchanged.
        replacement = b'<?php /* AUDIT_SYNTHETIC_PACKAGE_REPLACEMENT */\n'
        target.write_bytes(replacement)
        refreshed = apply_overlay.apply_files(fs, fs, refresh=True)
        refresh_proof = {'same_version_package_replacement_simulated': True,
                         'refresh_status': refreshed['status'],
                         'modified_mfa_file_retained': target.read_bytes() == replacement,
                         'real_package_upgrade_performed': False}

    result = {
        'source': str(root), 'vps_accessed': False, 'production_services_changed': False,
        'csrf_links': csrf_results,
        'waf_selection_vs_effective_state': security_proof,
        'backup_latest_attempt_vs_last_success': backup_proof,
        'refresh_source_equals_destination': refresh_proof,
        'native_resources': {
            'command_exists': (root / 'bin/v-update-user-cgroup').is_file(),
            'package_gui_exists': 'v_cpu_quota' in (root / 'web/templates/pages/edit_package.php').read_text(),
            'memory_high_without_memory_max': 'MemoryHigh=' in (root / 'bin/v-update-user-cgroup').read_text()
                and 'MemoryMax=' not in (root / 'bin/v-update-user-cgroup').read_text(),
            'runtime_enforcement_tested': False},
        'native_dns_cluster_exists': (root / 'bin/v-sync-dns-cluster').is_file(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
