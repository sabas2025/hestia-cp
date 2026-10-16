from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'professional'))
import backup
import health
import ops
spec=importlib.util.spec_from_file_location('apply_overlay',ROOT/'professional/apply.py')
apply_overlay=importlib.util.module_from_spec(spec);spec.loader.exec_module(apply_overlay)

class OperationsTests(unittest.TestCase):
    def test_lock_rejects_concurrent_job(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'locks/job'
            with ops.lock(p):
                with self.assertRaises(BlockingIOError):
                    with ops.lock(p):pass

    def test_atomic_json_mode_and_symlink_directory(self):
        with tempfile.TemporaryDirectory() as td:
            r=Path(td);p=r/'state/job.json';ops.atomic_json(p,{'ok':True})
            self.assertEqual(json.loads(p.read_text()),{'ok':True});self.assertEqual(p.stat().st_mode&0o777,0o640)
            link=r/'link';link.symlink_to(r/'state',target_is_directory=True)
            with self.assertRaises(ValueError):ops.atomic_json(link/'job.json',{'bad':True})

    def test_conf_never_executes_shell(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'c';p.write_text("VERSION='1.10.5'\nX=$(touch /never-created)\n")
            self.assertEqual(ops.config(p),{'VERSION':'1.10.5'})

    def config_fixture(self,root):
        password=root/'password';password.write_text('synthetic repository password');password.chmod(0o600)
        cfg=root/'backup.json';cfg.write_text(json.dumps({'repository':'sftp:backup@example.invalid:/backups','password_file':str(password)}));cfg.chmod(0o600)
        return cfg,password

    def test_backup_config_rejects_loose_permissions(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);cfg,password=self.config_fixture(root)
            self.assertEqual(backup.settings(cfg)['keep_daily'],7)
            cfg.chmod(0o644)
            with self.assertRaises(ValueError):backup.settings(cfg)
            cfg.chmod(0o600);password.chmod(0o644)
            with self.assertRaises(ValueError):backup.settings(cfg)

    def test_backup_config_rejects_url_password_and_unknown_keys(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);cfg,password=self.config_fixture(root);data=json.loads(cfg.read_text())
            for changed in [{'repository':'s3:https://name:password@example.org/repo'},{'keep_daily':-1},{'arbitrary_command':'true'}]:
                cfg.write_text(json.dumps({**data,**changed}))
                with self.subTest(changed=changed),self.assertRaises(ValueError):backup.settings(cfg)

    def make_user(self,root):
        (root/'data/users/testuser').mkdir(parents=True);(root/'data/users/testuser/user.conf').write_text("SUSPENDED='no'\n")
        (root/'conf').mkdir();archive=root/'archives';archive.mkdir();(root/'conf/hestia.conf').write_text(f"BACKUP='{archive}'\n")
        return archive

    def test_backup_new_archive_and_tag_scoping(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);archive=self.make_user(root);cfg,password=self.config_fixture(root);calls=[]
            def runner(args,env=None):
                calls.append((args,env))
                if args[0].endswith('v-backup-user'):(archive/'testuser.2026-10-15.tar').write_bytes(b'not-a-real-tar-test-fixture')
                return ''
            result=backup.execute('run','testuser',backup.settings(cfg),root,runner)
            self.assertEqual(result['state'],'succeeded')
            self.assertEqual(calls[1][0][1:4],['backup','--tag','hestia-testuser'])
            self.assertEqual(calls[1][1]['RESTIC_PASSWORD_FILE'],str(password))
            self.assertNotIn(password.read_text(),json.dumps(result))
            self.assertTrue((root/'data/professional/backups/testuser-run.json').is_file())

    def test_failed_backup_records_failure_and_never_uploads_old_archive(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);archive=self.make_user(root);(archive/'testuser.old.tar').write_bytes(b'old');cfg,password=self.config_fixture(root);calls=[]
            def runner(args,env=None):calls.append(args);return ''
            with self.assertRaises(RuntimeError):backup.execute('run','testuser',backup.settings(cfg),root,runner)
            self.assertEqual(len(calls),1)
            self.assertEqual(json.loads((root/'data/professional/jobs/testuser.json').read_text())['state'],'failed')

    def test_backup_retention_only_selected_user(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);self.make_user(root);cfg,password=self.config_fixture(root);calls=[]
            backup.execute('retention','testuser',backup.settings(cfg),root,lambda args,env=None:calls.append(args) or '')
            self.assertIn('hestia-testuser',calls[0]);self.assertIn('--tag',calls[0])

    def test_backup_wrong_user_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);self.make_user(root);cfg,password=self.config_fixture(root)
            for user in ('../admin','unknown','admin;true'):
                with self.subTest(user=user),self.assertRaises(ValueError):backup.execute('run',user,backup.settings(cfg),root)

    def test_restore_drill_is_isolated_and_does_not_restore_live_hestia(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);self.make_user(root);cfg,password=self.config_fixture(root);calls=[]
            def runner(args,env=None):
                calls.append(args)
                if args[1]=='stats':return json.dumps({'total_size':1024})
                if args[1]=='restore':
                    target=Path(args[args.index('--target')+1]);(target/'testuser.test.tar').write_bytes(b'fixture')
                return ''
            result=backup.execute('drill','testuser',backup.settings(cfg),root,runner)
            self.assertEqual(result['drill_scope'],'restic-restore-and-tar-readability')
            self.assertNotIn('v-restore-user',' '.join(' '.join(c) for c in calls))
            restore=next(c for c in calls if c[0]=='restic' and c[1]=='restore')
            self.assertFalse(Path(restore[restore.index('--target')+1]).exists())

    def test_restore_drill_refuses_invalid_space_estimate(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);self.make_user(root);cfg,password=self.config_fixture(root);calls=[]
            def runner(args,env=None):calls.append(args);return '{}'
            with self.assertRaises(RuntimeError):backup.execute('drill','testuser',backup.settings(cfg),root,runner)
            self.assertEqual(len(calls),1)

    def test_health_reports_down_services_without_secrets(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'conf').mkdir();(root/'conf/hestia.conf').write_text("VERSION='1.10.5'\nDB_SYSTEM='mysql,pgsql'\nSECRET='do-not-publish'\n")
            data=health.collect(root,lambda args,timeout=0:(3,'inactive\n'))
            self.assertEqual(data['status'],'critical')
            self.assertIn('pgsql',[s['name'] for s in data['services']])
            self.assertNotIn('do-not-publish',json.dumps(data))

    def fixture_hestia(self,root):
        for p in ['web/inc','web/templates/includes','conf','bin']:(root/p).mkdir(parents=True,exist_ok=True)
        (root/'web/inc/main.php').write_text('<?php')
        (root/'web/templates/includes/panel.php').write_text('<header>original</header>')
        (root/'conf/hestia.conf').write_text("VERSION='1.10.5'\n")
        for n in ['v-add-sys-filemanager','v-add-user-composer','v-add-sys-roundcube']:
            shutil.copy2(ROOT/'bin'/n,root/'bin'/n)

    def test_overlay_idempotent_and_preserves_native_auth(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);self.fixture_hestia(root)
            first=apply_overlay.apply_files(root,ROOT)
            before={str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}
            second=apply_overlay.apply_files(root,ROOT)
            after={str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}
            self.assertEqual(first['status'],'applied');self.assertEqual(second['status'],'applied');self.assertEqual(before,after)
            self.assertEqual((root/'web/inc/main.php').read_text(),'<?php')
            self.assertEqual((root/'web/templates/includes/panel.php').read_text().count('pro-home-link'),1)
            for n in ['v-add-sys-filemanager','v-add-user-composer','v-add-sys-roundcube']:
                import subprocess
                self.assertEqual(subprocess.run(['/bin/bash','-n',str(root/'bin'/n)],capture_output=True).returncode,0)

    def test_security_upgrade_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);self.fixture_hestia(root);(root/'conf/hestia.conf').write_text("VERSION='1.11.0'\n")
            before=(root/'bin/v-add-sys-filemanager').read_bytes()
            result=apply_overlay.apply_files(root,ROOT,True)
            self.assertEqual(result['status'],'review-required');self.assertEqual(before,(root/'bin/v-add-sys-filemanager').read_bytes())

    def test_atomic_overlay_rejects_symlink(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);target=root/'real';target.write_text('original');link=root/'link';link.symlink_to(target)
            with self.assertRaises(ValueError):apply_overlay.atomic_file(link,b'bad')
            self.assertEqual(target.read_text(),'original')

if __name__=='__main__':unittest.main()
