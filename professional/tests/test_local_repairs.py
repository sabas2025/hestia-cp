"""Regression tests for real integration failures; no production services are changed."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'professional'))
import business
import cloud_setup as cloud
import maintenance
from mfa import root_json

class CloudRegistrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.base=Path(self.tmp.name)
        self.config=self.base/'config/cloud.json';self.secrets=self.base/'config/secrets';self.transport=self.base/'transport.conf'
        token=json.dumps({'access_token':'PRIVATE-ACCESS','refresh_token':'PRIVATE-REFRESH'})
        self.transport.write_text('[drivebackup]\ntype = drive\nclient_id = PRIVATE-CLIENT\nclient_secret = PRIVATE-SECRET\ntoken = '+token+'\n')
        self.transport.chmod(0o600);self.calls=[]
    def configure(self,**kwargs):
        args=dict(name='google',provider='google-drive',remote='drivebackup',folder='ctba/restic',transport=self.transport,
                  password='PRIVATE-REPOSITORY-PASSWORD',config=self.config,secret_dir=self.secrets,
                  runner=lambda args:self.calls.append(args) or '',guard=lambda:None)
        args.update(kwargs);return cloud.configure(**args)
    def test_registers_without_claiming_backup_or_exposing_credentials(self):
        result=self.configure();self.assertTrue(result['connection_read_tested'])
        self.assertFalse(result['backup_sent']);self.assertFalse(result['repository_initialized']);self.assertFalse(result['schedule_enabled'])
        self.assertEqual(self.config.stat().st_mode & 0o777,0o600)
        self.assertEqual((self.secrets/'google.password').stat().st_mode & 0o777,0o600)
        for text in (json.dumps(result),json.dumps(self.calls),self.config.read_text()):
            self.assertNotIn('PRIVATE-',text)
        self.assertEqual(cloud.settings(self.config)['targets'][0]['provider'],'google-drive')
    def test_existing_target_and_retention_are_preserved_and_duplicate_refused(self):
        self.configure();cfg=json.loads(self.config.read_text());cfg['keep_daily']=19;root_json(self.config,cfg)
        original=cfg['targets'][0].copy();self.configure(name='second',folder='ctba/second')
        final=json.loads(self.config.read_text());self.assertEqual(final['targets'][0],original);self.assertEqual(final['keep_daily'],19)
        with self.assertRaises(ValueError):self.configure()
    def test_connection_failure_removes_new_password_and_preserves_configuration(self):
        self.configure();before=self.config.read_bytes()
        def fail(args):raise RuntimeError('private provider detail')
        with self.assertRaises(RuntimeError):self.configure(name='failed',folder='ctba/failed',runner=fail)
        self.assertEqual(self.config.read_bytes(),before);self.assertFalse((self.secrets/'failed.password').exists())
    def test_concurrent_configuration_change_is_not_overwritten(self):
        def change(args):root_json(self.config,{'schema':2,'targets':[],'keep_daily':31});return ''
        with self.assertRaises(ValueError):self.configure(runner=change)
        self.assertEqual(json.loads(self.config.read_text())['keep_daily'],31)
        self.assertFalse((self.secrets/'google.password').exists())
    def test_webdav_missing_oauth_and_unsafe_transport_are_rejected(self):
        with self.assertRaises(ValueError):self.configure(provider='private-webdav')
        self.transport.write_text('[drivebackup]\ntype = drive\n')
        with self.assertRaises(ValueError):self.configure()
        self.transport.chmod(0o644)
        with self.assertRaises(ValueError):self.configure()
    def test_existing_webdav_destination_is_preserved_without_connecting_to_it(self):
        old_transport=self.base/'webdav.conf';old_transport.write_text('[private]\ntype = webdav\nurl = https://private.example.invalid/\n')
        old_transport.chmod(0o600);old_password=self.base/'old.password';old_password.write_text('OLD-PRIVATE-REPOSITORY');old_password.chmod(0o600)
        original={'id':'private','provider':'private-webdav','remote':'private','path':'old/restic',
                  'rclone_config':str(old_transport),'password_file':str(old_password)}
        root_json(self.config,{'schema':2,'targets':[original],'keep_daily':17})
        before=old_transport.read_bytes();self.configure()
        self.assertEqual(json.loads(self.config.read_text())['targets'][0],original)
        self.assertEqual(old_transport.read_bytes(),before)
        self.assertEqual(len(self.calls),1);self.assertIn('drivebackup:',self.calls[0]);self.assertNotIn('private:',self.calls[0])

class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.base=Path(self.tmp.name)
        self.root=self.base/'hestia';self.fs=self.base/'fs';self.root.mkdir();self.fs.mkdir()
    def test_exact_security_versions_and_legacy_are_not_conflated(self):
        for old,new in [('8.2.34','8.2.35'),('8.3.35','8.3.36'),('8.4.26','8.4.27'),('8.5.11','8.5.12')]:
            self.assertEqual(maintenance.php_version(old)['october_21_fix'],'upgrade-required')
            self.assertEqual(maintenance.php_version(new)['october_21_fix'],'included-in-reported-binary')
            self.assertFalse(maintenance.php_version(new)['running_workers_verified'])
        self.assertEqual(maintenance.php_version('8.1.35')['october_21_fix'],'vendor-backport-or-branch-review-required')
    def test_explicit_filemanager_enable_preserves_integrity_and_a2f_checks(self):
        policy=self.root/'data/professional-filemanager/policy.json';root_json(policy,{'schema':1,'enabled':False})
        with patch.object(maintenance,'verify_deployment',return_value={'state':'verified'}):
            result=maintenance.repair(self.root,self.fs,enable_filemanager=True)
        self.assertTrue(json.loads(policy.read_text())['enabled']);self.assertFalse(result['twofa_bypassed'])
        self.assertFalse(result['nextcloud_or_webdav_modified']);self.assertFalse(result['packages_upgraded'])
    def test_invalid_policy_or_integrity_does_not_get_overwritten(self):
        policy=self.root/'data/professional-filemanager/policy.json';root_json(policy,{'schema':1,'enabled':'yes'})
        before=policy.read_bytes()
        with patch.object(maintenance,'verify_deployment',return_value={'state':'verified'}),self.assertRaises(ValueError):
            maintenance.repair(self.root,self.fs,enable_filemanager=True)
        self.assertEqual(policy.read_bytes(),before)
        with patch.object(maintenance,'verify_deployment',return_value={'state':'review-required'}),self.assertRaises(ValueError):
            maintenance.repair(self.root,self.fs)
    def test_nginx_never_started_after_failed_validation(self):
        calls=[]
        def runner(args):calls.append(args);return 1,''
        with patch.object(maintenance,'verify_deployment',return_value={'state':'verified'}),self.assertRaises(ValueError):
            maintenance.repair(self.root,self.fs,start_nginx=True,runner=runner)
        self.assertEqual(calls,[['/usr/sbin/nginx','-t']])

class NativeFilemanagerUITests(unittest.TestCase):
    def render(self,professional):
        php=os.environ.get('PHP_BINARY') or shutil.which('php');self.assertTrue(php,'PHP is required')
        source=(ROOT/'web/templates/pages/edit_server.php').read_text()
        start=source.index("<?php if (is_file(dirname(__DIR__, 2) . '/professional/editor.php'))")
        end=source.index('<?php } ?>',start)+len('<?php } ?>')
        fragment=source[start:end]
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp)/'web';(base/'templates/pages').mkdir(parents=True)
            if professional:(base/'professional').mkdir();(base/'professional/editor.php').write_text('<?php')
            file=base/'templates/pages/form.php'
            file.write_text("<?php function tohtml($s){return htmlspecialchars($s);} if(!function_exists('_')){function _($s){return $s;}} $_SESSION=['FILE_MANAGER'=>'false']; ?>"+fragment)
            result=subprocess.run([php,'-n',str(file)],capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr);return result.stdout
    def test_professional_settings_link_to_real_manager_instead_of_legacy_activation(self):
        output=self.render(True);self.assertIn('href="/professional/editor.php"',output)
        self.assertNotIn('name="v_filemanager"',output);self.assertIn('A2F',output)
    def test_native_fallback_is_retained_without_professional(self):
        self.assertIn('name="v_filemanager"',self.render(False))
