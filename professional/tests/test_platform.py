"""Boundary and failure-path tests for cloud backups, protection and project management."""
import base64
import io
import json
import os
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'professional'))
import assistant
import cloud_backup as cloud
import ops
import projects
import security
import stacks

def private(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body); path.chmod(0o600)
    return path

def archive(path, names):
    with tarfile.open(path, 'w') as tar:
        for name in names:
            data = b'test-fixture'; item = tarfile.TarInfo(name); item.size = len(data)
            tar.addfile(item, io.BytesIO(data))

class CloudTests(unittest.TestCase):
    def fixture(self, root, provider='google-drive', options=''):
        types = cloud.PROVIDERS
        password = private(root / 'password', 'synthetic-password')
        rc = private(root / 'remote.conf', f'[remote]\ntype = {types[provider]}\n' + options)
        cfg = {'schema': 2, 'targets': [{'id': 'main-copy', 'provider': provider, 'remote': 'remote', 'path': 'backups/account', 'password_file': str(password), 'rclone_config': str(rc)}]}
        path = private(root / 'cloud.json', json.dumps(cfg))
        return path, cfg, rc

    def test_provider_and_tls_validation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for provider, options in [('google-drive', ''), ('amazon-s3', 'provider = AWS\n'), ('private-s3', 'provider = Other\nendpoint = https://storage.example.invalid\n'), ('ftps', 'explicit_tls = true\n'), ('private-webdav', 'url = https://storage.example.invalid\n')]:
                with self.subTest(provider=provider):
                    path, _, _ = self.fixture(root, provider, options)
                    self.assertEqual(cloud.settings(path)['targets'][0]['repository'], 'rclone:remote:backups/account')
            for provider, options in [('ftps', ''), ('private-s3', 'endpoint = http://storage.invalid\n'), ('private-webdav', 'url = http://storage.invalid\n'), ('google-drive', 'no_check_certificate = true\n')]:
                path, _, _ = self.fixture(root, provider, options)
                with self.subTest(provider=provider), self.assertRaises(ValueError): cloud.settings(path)

    def test_plain_ftp_requires_explicit_opt_in(self):
        with tempfile.TemporaryDirectory() as td:
            path, cfg, _ = self.fixture(Path(td), 'ftp')
            with self.assertRaises(ValueError): cloud.settings(path)
            cfg['targets'][0]['allow_plain_ftp'] = True; path.write_text(json.dumps(cfg))
            self.assertEqual(cloud.settings(path)['targets'][0]['provider'], 'ftp')

    def test_remote_injection_duplicate_repository_and_secrets(self):
        with tempfile.TemporaryDirectory() as td:
            path, cfg, rc = self.fixture(Path(td))
            original = json.loads(json.dumps(cfg))
            for changes in [{'remote': ':local:/etc'}, {'path': '../public'}, {'path': 'x/../y'}, {'path': '-flag'}]:
                cfg = json.loads(json.dumps(original)); cfg['targets'][0].update(changes); path.write_text(json.dumps(cfg))
                with self.subTest(changes=changes), self.assertRaises(ValueError): cloud.settings(path)
            cfg = original; cfg['targets'].append({**cfg['targets'][0], 'id': 'duplicate-copy'}); path.write_text(json.dumps(cfg))
            with self.assertRaises(ValueError): cloud.settings(path)
            path, _, rc = self.fixture(Path(td)); rc.chmod(0o644)
            with self.assertRaises(ValueError): cloud.settings(path)

    def test_symlink_ancestor_and_fifo_secret_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); real = root / 'real'; real.mkdir(); private(real / 'key', 'secret')
            (root / 'link').symlink_to(real, target_is_directory=True)
            with self.assertRaises(ValueError): ops.private_read(root / 'link/key')
            os.mkfifo(root / 'fifo', 0o600)
            with self.assertRaises(ValueError): ops.private_read(root / 'fifo')

    def test_archive_checks_every_site_and_database_without_extracting(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'account.tar'; expected = {'web': ['site.invalid'], 'db': ['app_main']}
            archive(path, ['web/site.invalid/domain_data.tar.gz'])
            with self.assertRaises(ValueError): cloud.validate_archive(path, expected)
            archive(path, ['web/site.invalid/domain_data.tar.gz', 'db/app_main/app_main.mysql.sql.gz'])
            self.assertFalse(cloud.validate_archive(path, expected)['sql_import_tested'])
            archive(path, ['../../etc/passwd'])
            with self.assertRaises(ValueError): cloud.validate_archive(path, expected)

    def account(self, root):
        private(root / 'data/users/testuser/user.conf', "SUSPENDED='no'\n")
        private(root / 'data/users/testuser/web.conf', "DOMAIN='site.invalid'\n")
        private(root / 'data/users/testuser/db.conf', "DB='app_main'\n")
        folder = root / 'archives'; folder.mkdir()
        private(root / 'conf/hestia.conf', f"BACKUP='{folder}'\nBACKUP_SYSTEM='local'\n")
        return folder

    def test_one_native_backup_partial_provider_failure_never_reports_global_success(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); folder = self.account(root); path, _, _ = self.fixture(root); cfg = cloud.settings(path)
            cfg['targets'].append({**cfg['targets'][0], 'id': 'second-copy', 'repository': 'rclone:remote:other'})
            calls = []; counts = {'native': 0}
            def runner(args, env=None):
                calls.append((args, env))
                if args[0].endswith('v-backup-user'):
                    counts['native'] += 1; archive(folder / 'testuser.new.tar', ['web/site.invalid/domain_data.tar.gz', 'db/app_main/app_main.mysql.sql.gz']); counts['mode'] = (folder / 'testuser.new.tar').stat().st_mode; return ''
                if env and env.get('RESTIC_REPOSITORY') == 'rclone:remote:other': raise RuntimeError('provider failure with sensitive details')
                if args[1] == 'backup': return json.dumps({'message_type': 'summary', 'snapshot_id': 'a' * 64})
                return ''
            with patch.dict(os.environ, {'RESTIC_PASSWORD': 'do-not-inherit', 'RCLONE_CONFIG_REMOTE_TYPE': 'local', 'LD_PRELOAD': 'bad'}):
                result = cloud.execute('run', 'testuser', cfg, root, runner=runner)
            self.assertEqual(counts['native'], 1); self.assertEqual(result['state'], 'failed')
            self.assertEqual((folder / 'testuser.new.tar').stat().st_mode, counts['mode'])
            self.assertFalse(list((root / 'data/professional-staging').iterdir()))
            self.assertEqual([t['state'] for t in result['targets']], ['succeeded', 'failed'])
            self.assertFalse((root / 'data/professional/backups/testuser-run.json').exists())
            self.assertTrue((root / 'data/professional/backups/testuser-main-copy-run.json').exists())
            self.assertNotIn('sensitive details', json.dumps(result))
            for args, env in calls:
                if args[0] == 'restic':
                    self.assertNotIn('RESTIC_PASSWORD', env); self.assertNotIn('LD_PRELOAD', env); self.assertNotIn('RCLONE_CONFIG_REMOTE_TYPE', env)

    def test_missing_database_dump_aborts_before_cloud_upload(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); folder = self.account(root); path, _, _ = self.fixture(root); calls = []
            def runner(args, env=None):
                calls.append(args); archive(folder / 'testuser.new.tar', ['web/site.invalid/domain_data.tar.gz']); return ''
            with self.assertRaises(ValueError): cloud.execute('run', 'testuser', cloud.settings(path), root, runner=runner)
            self.assertEqual(len(calls), 1)
            self.assertEqual(json.loads((root / 'data/professional/jobs/testuser.json').read_text())['state'], 'failed')

    def test_retention_and_init_require_one_target(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); self.account(root); path, _, _ = self.fixture(root)
            for action in ('init', 'retention', 'drill'):
                with self.subTest(action=action), self.assertRaises(ValueError): cloud.execute(action, 'testuser', cloud.settings(path), root)

class ProtectionTests(unittest.TestCase):
    def test_existing_fail2ban_exemptions_are_preserved_without_interpolation(self):
        existing = security.effective_ignores(lambda args: 'These IP addresses/networks are ignored:\n|- 198.51.100.10/32\n|- 2001:db8::/64\n`- trusted.example.org\n')
        cfg = {'profile': 'basico', 'waf': False, 'fail2ban': True, 'admin_cidrs': ['203.0.113.10/32'], 'request_body_limit': 134217728}
        text = security.render(cfg, existing)[security.JAIL]
        self.assertIn('198.51.100.10/32', text); self.assertIn('trusted.example.org', text); self.assertNotIn('%(', text)
    def fixture(self, fs):
        hestia = fs / 'hestia'; private(hestia / 'conf/hestia.conf', "VERSION='1.10.5'\nWEB_SYSTEM='apache2'\n")
        private(fs / security.WAF, '<IfModule security2_module>\nIncludeOptional /etc/modsecurity/*.conf\n</IfModule>\n')
        private(fs / 'etc/modsecurity/modsecurity.conf', 'SecRuleEngine DetectionOnly\n')
        private(fs / 'etc/modsecurity/crs/crs-setup.conf', '# stock CRS\n')
        private(fs / 'usr/share/modsecurity-crs/rules/REQUEST-901-INITIALIZATION.conf', '# fixture\n')
        private(fs / 'etc/fail2ban/jail.local', '[ssh-iptables]\n[hestia-iptables]\n')
        cfg = {'profile': 'basico', 'waf': True, 'fail2ban': True, 'admin_cidrs': ['203.0.113.10/32'], 'request_body_limit': 134217728}
        return hestia, cfg

    def test_config_failure_restores_all_original_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            fs = Path(td); hestia, cfg = self.fixture(fs); before = (fs / security.WAF).read_bytes(); failed = False
            def runner(args):
                nonlocal failed
                if args == ['apache2ctl', '-M']: return 'security2_module'
                if args == ['apache2ctl', 'configtest'] and not failed: failed = True; raise RuntimeError('bad syntax')
                return 'ok'
            with self.assertRaisesRegex(RuntimeError, 'restored'): security.apply_profile(fs, hestia, cfg, runner)
            self.assertEqual((fs / security.WAF).read_bytes(), before)
            self.assertFalse((fs / security.JAIL).exists()); self.assertFalse((hestia / 'data/professional/security.json').exists())

    def test_success_rollback_and_current_ssh_recovery_ip(self):
        with tempfile.TemporaryDirectory() as td:
            fs = Path(td); hestia, cfg = self.fixture(fs); before = (fs / security.WAF).read_bytes()
            runner = lambda args: 'security2_module' if args == ['apache2ctl', '-M'] else 'ok'
            with self.assertRaises(ValueError): security.apply_profile(fs, hestia, cfg, runner, peer='203.0.113.11')
            result = security.apply_profile(fs, hestia, cfg, runner, peer='203.0.113.10')
            self.assertIn('SecRuleEngine On', (fs / security.WAF).read_text())
            security.rollback(fs, hestia, result['rollback_id'], runner)
            self.assertEqual((fs / security.WAF).read_bytes(), before)
            with self.assertRaises(ValueError): security.rollback(fs, hestia, '../escape', runner)

    def test_waf_refuses_nginx_only_and_unknown_custom_policy(self):
        with tempfile.TemporaryDirectory() as td:
            fs = Path(td); hestia, cfg = self.fixture(fs); runner = lambda args: 'security2_module'
            (hestia / 'conf/hestia.conf').write_text("VERSION='1.10.5'\nWEB_SYSTEM='nginx'\n")
            with self.assertRaises(ValueError): security.prerequisites(fs, hestia, cfg, runner)
            (hestia / 'conf/hestia.conf').write_text("VERSION='1.10.5'\nWEB_SYSTEM='apache2'\n")
            (fs / security.WAF).write_text('SecRuleEngine On\n')
            with self.assertRaises(ValueError): security.prerequisites(fs, hestia, cfg, runner)

class AssistantProjectTests(unittest.TestCase):
    def test_dns_plan_has_no_fabricated_dkim_or_writes(self):
        plan = assistant.plan('email', 'example.org', '8.8.8.8')
        self.assertFalse(plan['changes_applied']); self.assertFalse(plan['dkim_generated'])
        self.assertTrue(any(r['name'] == '_dmarc.example.org' for r in plan['records']))
        for domain in ('--help', 'x;touch.invalid', '../example.org', '8.8.8.8'):
            with self.assertRaises(ValueError): assistant.plan('dns', domain, '8.8.8.8')
        with self.assertRaises(ValueError): assistant.plan('dns', 'example.org', '127.0.0.1')

    def test_docker_objects_never_become_options_or_shell(self):
        for target in ('--privileged', '$(touch /tmp/no)', 'a;id'):
            with self.assertRaises(ValueError): projects.docker_command('container-start', target)
        args, writes = projects.docker_command('container-stop', 'project-app')
        self.assertEqual(args, ['docker', 'stop', 'project-app']); self.assertTrue(writes)
        with self.assertRaises(ValueError): projects.docker_command('image-pull', 'nginx:latest')

    def test_compose_rejects_socket_privilege_host_network_and_public_bind(self):
        project = {'type': 'compose', 'compose_file': '/root/approved.json'}
        bad = [{'privileged': True}, {'network_mode': 'host'}, {'ports': [{'host_ip': '0.0.0.0'}]}, {'volumes': [{'type': 'bind', 'source': '/var/run/docker.sock'}]}]
        for service in bad:
            runner = lambda args, service=service: json.dumps({'services': {'app': service}})
            with self.subTest(service=service), self.assertRaises(ValueError): projects.compose_command('project', project, 'up', runner)
        doc = {'services': {'app': {'image': 'nginx@sha256:' + 'a' * 64, 'ports': [{'host_ip': '127.0.0.1'}]}}}
        args, writes = projects.compose_command('project', project, 'down', lambda args: json.dumps(doc))
        self.assertTrue(writes); self.assertNotIn('--volumes', args); self.assertIn('/dev/null', args)

    def test_unsafe_volume_driver_rejected(self):
        doc = {'services': {'app': {'image': 'x@sha256:' + 'a' * 64}}, 'volumes': {'host': {'driver_opts': {'device': '/'}}}}
        with self.assertRaises(ValueError): projects.compose_command('project', {'type': 'compose', 'compose_file': '/root/x'}, 'up', lambda args: json.dumps(doc))

    def test_proxy_only_loopback_and_preserves_acme(self):
        for tls in (False, True):
            body = projects.proxy_template(3100, tls)
            self.assertIn('proxy_pass http://127.0.0.1:3100', body); self.assertIn('acme-challenge', body)
            self.assertIn('X-Forwarded-For $remote_addr', body)
        with self.assertRaises(ValueError): projects.proxy_template(22)

    def test_generated_stacks_pin_images_and_separate_full_docker_console(self):
        digest = 'registry/image@sha256:' + 'a' * 64
        admin = stacks.portainer(digest); self.assertIn('/var/run/docker.sock:/var/run/docker.sock', admin['services']['portainer']['volumes'])
        marketing = stacks.marketing(digest, digest, {'db_password': 'long-synthetic-password', 'admin_username': 'administrator', 'admin_password': 'another-long-password'})
        self.assertNotIn('/var/run/docker.sock', json.dumps(marketing)); self.assertEqual(marketing['services']['app']['ports'], ['127.0.0.1:9100:9000'])
        with self.assertRaises(ValueError): stacks.portainer('portainer/portainer-ce:latest')

if __name__ == '__main__': unittest.main()
