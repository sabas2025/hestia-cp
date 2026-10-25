"""Console registration: credentials, preservation, interruption and existing jobs."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'professional'))
import cloud_backup

spec = importlib.util.spec_from_file_location('nextcloud_setup', ROOT / 'ops/vps-nextcloud.py')
n = importlib.util.module_from_spec(spec)
spec.loader.exec_module(n)


def private(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_bytes(data if isinstance(data, bytes) else data.encode())
    path.chmod(0o600)


class NextcloudSetupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.config = self.base / 'etc/cloud.json'
        self.secret_dir = self.base / 'etc/secrets'
        self.state = self.base / 'state'
        self.calls = []
        self.guards = 0
        private(self.base / 'etc/old.conf', '[old]\ntype = webdav\nurl = https://old.example.invalid/\n')
        private(self.base / 'etc/old.password', 'EXISTING-REPOSITORY-PASSWORD')
        self.original = {'schema': 2, 'keep_daily': 13, 'append_only': True, 'targets': [{
            'id': 'old', 'provider': 'private-webdav', 'remote': 'old', 'path': 'old/repository',
            'rclone_config': str(self.base / 'etc/old.conf'),
            'password_file': str(self.base / 'etc/old.password')}]}
        private(self.config, json.dumps(self.original))
        self.before = self.config.read_bytes()

    def guard(self):
        self.guards += 1

    def runner(self, args, **kwargs):
        self.calls.append((args, kwargs))
        if 'obscure' in args:
            self.assertEqual(kwargs['data'], 'SYNTHETIC-APP-SECRET\n')
            return 'SYNTHETIC_OBSCURED_VALUE_123456\n'
        self.assertIn('lsf', args)
        return ''

    def configure(self, **changes):
        args = dict(name='nextcloud', url='https://cloud.example.invalid/remote.php/dav/files/client/',
                    user='client', password='SYNTHETIC-APP-SECRET', restic_password='SYNTHETIC-RESTIC-SECRET',
                    folder='hestia/server/restic', vendor='nextcloud', config=self.config,
                    secret_dir=self.secret_dir, state=self.state, validator=cloud_backup.settings,
                    runner=self.runner, guard=self.guard)
        args.update(changes)
        return n.configure(**args)

    def test_preserves_destinations_retention_and_no_secret_in_arguments_or_receipt(self):
        result = self.configure()
        current = json.loads(self.config.read_text())
        self.assertEqual(current['targets'][0], self.original['targets'][0])
        self.assertEqual(current['keep_daily'], 13)
        self.assertTrue(current['append_only'])
        self.assertEqual(len(current['targets']), 2)
        self.assertNotIn('repository', current['targets'][1])
        self.assertEqual(cloud_backup.settings(self.config)['targets'][1]['provider'], 'private-webdav')
        self.assertIn('vendor = nextcloud', (self.secret_dir / 'nextcloud.conf').read_text())
        self.assertNotIn('SYNTHETIC-APP-SECRET', (self.secret_dir / 'nextcloud.conf').read_text())
        self.assertEqual((self.secret_dir / 'nextcloud.password').read_text(), 'SYNTHETIC-RESTIC-SECRET\n')
        for path in (self.config, self.secret_dir / 'nextcloud.conf', self.secret_dir / 'nextcloud.password'):
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        for secret in ('SYNTHETIC-APP-SECRET', 'SYNTHETIC-RESTIC-SECRET', 'SYNTHETIC_OBSCURED_VALUE_123456'):
            self.assertNotIn(secret, json.dumps([a for a, _ in self.calls]))
            self.assertNotIn(secret, json.dumps(result))
            self.assertNotIn(secret, self.config.read_text())
        receipt = json.loads((Path(result['review_directory']) / 'receipt.json').read_text())
        self.assertEqual(receipt['state'], 'configured')
        self.assertTrue(receipt['connection_read_tested'])
        self.assertFalse(receipt['backup_sent'])
        self.assertFalse(receipt['repository_initialized'])
        self.assertFalse(receipt['restoration_tested'])
        self.assertFalse(receipt['schedule_enabled'])
        self.assertEqual((Path(result['review_directory']) / 'cloud-backup.before.json').read_bytes(), self.before)
        self.assertEqual(self.guards, 2)

    def test_connection_failure_preserves_existing_configuration_and_credentials(self):
        def fail(args, **kwargs):
            if 'lsf' in args:
                raise RuntimeError('synthetic transport failure')
            return self.runner(args, **kwargs)
        with self.assertRaises(RuntimeError):
            self.configure(runner=fail)
        self.assertEqual(self.config.read_bytes(), self.before)
        self.assertFalse((self.secret_dir / 'nextcloud.conf').exists())
        self.assertFalse((self.secret_dir / 'nextcloud.password').exists())
        receipts = list(self.state.glob('*/receipt.json'))
        self.assertEqual(len(receipts), 1)
        self.assertEqual(json.loads(receipts[0].read_text())['state'], 'failed')

    def test_final_validation_failure_rolls_back_only_new_credentials(self):
        times = []
        def validate(path):
            times.append(path)
            if len(times) == 2:
                raise ValueError('synthetic final validation failure')
            return cloud_backup.settings(path)
        with self.assertRaises(ValueError):
            self.configure(validator=validate)
        self.assertEqual(self.config.read_bytes(), self.before)
        self.assertFalse((self.secret_dir / 'nextcloud.conf').exists())
        self.assertFalse((self.secret_dir / 'nextcloud.password').exists())
        self.assertEqual((self.base / 'etc/old.password').read_text(), 'EXISTING-REPOSITORY-PASSWORD')

    def test_second_credential_write_failure_preserves_original_and_cleans_first(self):
        original = n.new_file
        def fail(path, data):
            if path == self.secret_dir / 'nextcloud.password':
                raise OSError('synthetic disk failure')
            original(path, data)
        with patch.object(n, 'new_file', fail), self.assertRaises(OSError):
            self.configure()
        self.assertEqual(self.config.read_bytes(), self.before)
        self.assertFalse((self.secret_dir / 'nextcloud.conf').exists())

    def test_receipt_failure_after_commit_reports_configuration_without_deleting_credentials(self):
        original = n.new_file
        def fail(path, data):
            if path.name == 'receipt.updated.json':
                raise OSError('synthetic receipt failure')
            original(path, data)
        with patch.object(n, 'new_file', fail):
            result = self.configure()
        self.assertEqual(result['state'], 'configured-review')
        self.assertFalse(result['receipt_recorded'])
        self.assertTrue((self.secret_dir / 'nextcloud.password').exists())
        self.assertEqual(len(cloud_backup.settings(self.config)['targets']), 2)

    def test_concurrent_configuration_change_is_not_overwritten(self):
        changed = json.dumps({**self.original, 'keep_daily': 29}).encode()
        def change(args, **kwargs):
            if 'lsf' in args:
                private(self.config, changed)
            return self.runner(args, **kwargs)
        with self.assertRaisesRegex(ValueError, 'changed-during'):
            self.configure(runner=change)
        self.assertEqual(self.config.read_bytes(), changed)
        self.assertFalse((self.secret_dir / 'nextcloud.conf').exists())

    def test_existing_target_or_credentials_are_never_rotated(self):
        with self.assertRaisesRegex(ValueError, 'existing-target'):
            self.configure(name='old')
        private(self.secret_dir / 'nextcloud.password', 'DO-NOT-ROTATE')
        with self.assertRaisesRegex(ValueError, 'never-overwritten'):
            self.configure()
        self.assertEqual((self.secret_dir / 'nextcloud.password').read_text(), 'DO-NOT-ROTATE')
        self.assertEqual(self.config.read_bytes(), self.before)
        self.assertEqual(self.calls, [])

    def test_limit_and_broken_existing_provider_are_not_bypassed(self):
        cfg = dict(self.original)
        cfg['targets'] = [dict(self.original['targets'][0], id='old-' + str(i)) for i in range(8)]
        private(self.config, json.dumps(cfg))
        with self.assertRaisesRegex(ValueError, 'target-limit'):
            self.configure()
        self.assertEqual(self.calls, [])
        private(self.config, self.before)
        (self.base / 'etc/old.conf').chmod(0o666)
        with self.assertRaises(ValueError):
            self.configure()
        self.assertFalse(any('lsf' in args for args, _ in self.calls))
        self.assertFalse((self.secret_dir / 'nextcloud.conf').exists())

    def test_rejects_links_hardlinks_and_nonprivate_existing_configuration(self):
        real = self.base / 'real.json'
        os.replace(self.config, real)
        self.config.symlink_to(real)
        with self.assertRaises((ValueError, OSError)):
            self.configure()
        self.config.unlink(); os.link(real, self.config)
        with self.assertRaisesRegex(ValueError, 'unsafe-file'):
            self.configure()
        self.config.unlink(); os.replace(real, self.config); self.config.chmod(0o644)
        with self.assertRaisesRegex(ValueError, 'unsafe-file'):
            self.configure()
        self.assertEqual(self.calls, [])

    def test_private_directory_permissions_are_not_silently_repaired(self):
        self.secret_dir.mkdir(mode=0o750)
        with self.assertRaisesRegex(ValueError, 'private-directory'):
            self.configure()
        self.assertEqual(self.secret_dir.stat().st_mode & 0o777, 0o750)
        self.assertEqual(self.config.read_bytes(), self.before)

    def test_timer_guard_and_second_setup_lock_block_mutation(self):
        def busy():
            raise ValueError('backup-timer-or-service-active')
        with self.assertRaisesRegex(ValueError, 'timer'):
            self.configure(guard=busy)
        self.assertEqual(self.config.read_bytes(), self.before)
        self.assertEqual(self.calls, [])
        nested = []
        def locked(args, **kwargs):
            if 'obscure' in args:
                with self.assertRaises(BlockingIOError):
                    self.configure()
                nested.append(True)
            return self.runner(args, **kwargs)
        self.configure(runner=locked)
        self.assertEqual(nested, [True])

    def test_invalid_transport_inputs_fail_before_credentials_are_created(self):
        cases = [dict(url='http://cloud.example.invalid/'), dict(url='https://u:p@cloud.example.invalid/'),
                 dict(url='https://cloud.example.invalid/?token=secret'), dict(url='https://cloud.example.invalid/#secret'),
                 dict(url='https://cloud.example.invalid/%0aheader'), dict(url='https://cloud.example.invalid:99999/'),
                 dict(password='secret\n[other]'), dict(user='client\npass=secret'), dict(folder='../backup'),
                 dict(folder='backup//restic'), dict(name='name;id'), dict(vendor='sharepoint'),
                 dict(restic_password='password\nextra')]
        for case in cases:
            with self.subTest(case=case), self.assertRaises(ValueError):
                self.configure(**case)
        self.assertFalse(self.state.exists())
        self.assertEqual(self.config.read_bytes(), self.before)

    def test_interruption_during_probe_never_claims_configuration_or_backup_success(self):
        def interrupt(args, **kwargs):
            if 'lsf' in args:
                raise KeyboardInterrupt()
            return self.runner(args, **kwargs)
        with self.assertRaises(KeyboardInterrupt):
            self.configure(runner=interrupt)
        self.assertEqual(self.config.read_bytes(), self.before)
        receipt = json.loads(next(self.state.glob('*/receipt.json')).read_text())
        self.assertEqual(receipt['state'], 'failed')
        self.assertFalse(receipt['backup_sent'])

    def test_generic_webdav_and_first_configuration_are_supported(self):
        self.config.unlink()
        result = self.configure(vendor='other', name='webdav')
        self.assertEqual(result['state'], 'configured')
        self.assertIn('vendor = other', (self.secret_dir / 'webdav.conf').read_text())
        self.assertEqual(len(json.loads(self.config.read_text())['targets']), 1)

    def test_environment_is_fixed_and_external_error_output_is_never_echoed(self):
        with patch.dict(os.environ, {'RCLONE_CONFIG_NEXTCLOUD_URL': 'http://untrusted.invalid', 'LD_PRELOAD': 'untrusted'}):
            with patch.object(n.subprocess, 'run', return_value=types.SimpleNamespace(returncode=0, stdout='hidden')) as execute:
                self.assertEqual(n.run(['/usr/bin/rclone', 'lsf', 'nextcloud:']), 'hidden')
                call = execute.call_args.kwargs
                self.assertEqual(call['env'], n.ENV)
                self.assertEqual(call['stdout'], subprocess.DEVNULL)
                self.assertEqual(call['stderr'], subprocess.DEVNULL)
            with patch.object(n.subprocess, 'run', return_value=types.SimpleNamespace(returncode=1, stdout='SECRET')):
                with self.assertRaisesRegex(RuntimeError, '^external-command-failed$'):
                    n.run(['/usr/bin/rclone', 'lsf', 'nextcloud:'])

    def test_active_timer_and_running_job_are_detected(self):
        with self.assertRaisesRegex(ValueError, 'timer'):
            n.idle(self.base, lambda *a, **k: 'synthetic-backup.timer loaded active waiting')
        path = self.base / 'data/professional/jobs/client.json'
        private(path, '{"state":"running"}'); path.chmod(0o640)
        with self.assertRaisesRegex(ValueError, 'pending-review'):
            n.idle(self.base, lambda *a, **k: '')
        private(path, '{"state":"succeeded"}')
        n.idle(self.base, lambda *a, **k: '')

    def test_tampered_installed_module_is_rejected_before_import(self):
        root = self.base / 'hestia'
        files = []
        for name in ('ops.py', 'cloud_backup.py'):
            path = root / 'professional' / name
            private(path, 'raise AssertionError("must not import")\n'); path.chmod(0o644)
            files.append({'file': 'professional/' + name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'mode': 0o644})
        private(root / 'professional/deployment.json', json.dumps({'files': files}))
        (root / 'professional/cloud_backup.py').write_text('raise AssertionError("tampered must not import")\n')
        with self.assertRaisesRegex(ValueError, 'integrity-failed'):
            n.verified_core(root)

