"""Existing installation updates and prerequisite failure recovery, using isolated fixtures."""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'professional'))
import apply as overlay
import dependencies as deps
import upgrade

class UpgradeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.base=Path(self.tmp.name)
        self.root=self.base/'hestia';self.source=self.base/'source';self.fs=self.base/'fs'
        for name in ('web/inc','web/templates/includes','conf','bin','php/bin'):(self.root/name).mkdir(parents=True)
        (self.root/'web/inc/main.php').write_text('<?php')
        (self.root/'web/templates/includes/panel.php').write_text('<header>native</header>')
        (self.root/'conf/hestia.conf').write_text("VERSION='1.10.5'\n")
        (self.root/'php/bin/php').write_text('fixture')
        for name in ('v-add-sys-filemanager','v-add-user-composer','v-add-sys-roundcube'):
            shutil.copy2(ROOT/'bin'/name,self.root/'bin'/name)
        overlay.apply_files(self.root,ROOT)
        files=overlay.source_files(ROOT)+list((ROOT/'professional/cache-templates').glob('*'))+[ROOT/'install/hst-common.sh',ROOT/'install/assets.lock.tsv']
        for file in files:
            target=self.source/file.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(file,target)
        self.calls=[]
    def runner(self,args):self.calls.append(args);return 'enabled' if 'is-enabled' in args else 'ok'
    def test_success_verifies_actual_new_files_and_never_invokes_installer(self):
        new=self.source/'web/professional/reviewed-new.php';new.write_text('<?php // isolated test')
        result=upgrade.run_upgrade(self.root,self.source,self.fs,self.runner,lambda r:None,lambda r:None)
        self.assertEqual(result['state'],'succeeded');self.assertEqual((self.root/new.relative_to(self.source)).read_bytes(),new.read_bytes())
        self.assertEqual(overlay.verify_deployment(self.root)['state'],'verified')
        self.assertFalse(any('hst-install' in ' '.join(args) or 'apt-get' in args for args in self.calls))
    def test_failed_validation_restores_bytes_modes_and_removes_new_targets(self):
        old=(self.root/'professional/deployment.json').read_bytes()
        old_editor=(self.root/'web/professional/editor.js').read_bytes()
        (self.source/'web/professional/editor.js').write_text('// new version\n')
        new=self.source/'web/professional/reviewed-new.php';new.write_text('<?php')
        external=self.fs/'etc/systemd/system/hestia-professional-health.service'
        external.parent.mkdir(parents=True);external.write_text('original unit');external.chmod(0o640)
        def fail(root):external.write_text('changed unit');raise RuntimeError('synthetic failed check')
        with self.assertRaises(RuntimeError):upgrade.run_upgrade(self.root,self.source,self.fs,self.runner,fail,lambda r:None)
        self.assertEqual((self.root/'professional/deployment.json').read_bytes(),old)
        self.assertEqual((self.root/'web/professional/editor.js').read_bytes(),old_editor)
        self.assertFalse((self.root/new.relative_to(self.source)).exists());self.assertEqual(external.read_text(),'original unit')
        self.assertEqual(external.stat().st_mode&0o777,0o640)
        status=list((self.fs/'var/lib/hestia-professional-upgrade').glob('*/status.json'))
        self.assertEqual(json.loads(status[0].read_text())['state'],'failed-restored')
        self.assertEqual(overlay.verify_deployment(self.root)['state'],'verified')
    def test_modified_layer_unknown_new_target_and_active_jobs_block(self):
        live=self.root/'web/professional/editor.js';old=live.read_bytes();live.write_text('local hotfix')
        with self.assertRaises(ValueError):upgrade.preflight(self.root,self.source,self.fs)
        self.assertEqual(live.read_text(),'local hotfix');live.write_bytes(old)
        new=self.source/'web/professional/custom.php';new.write_text('<?php')
        (self.root/'web/professional/custom.php').write_text('local custom page')
        with self.assertRaises(ValueError):upgrade.preflight(self.root,self.source,self.fs)
        (self.root/'web/professional/custom.php').unlink()
        from mfa import root_json
        root_json(self.root/'data/professional-platform/jobs/active.json',{'state':'running'})
        with self.assertRaises(ValueError):upgrade.preflight(self.root,self.source,self.fs)

class DependencyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.fs=Path(self.tmp.name)
        self.root=self.fs/'hestia';(self.root/'conf').mkdir(parents=True)
        (self.root/'conf/hestia.conf').write_text("VERSION='1.10.5'\n")
        (self.fs/'etc').mkdir();(self.fs/'etc/os-release').write_text('ID=ubuntu\nVERSION_ID="26.04"\n')
        self.calls=[]
    def runner(self,args):self.calls.append(args);return 'fixture version'
    def test_component_and_admin_cidr_validation(self):
        for value in ('','backup,backup','backup;id','database'):
            with self.assertRaises(ValueError):deps.selected(value)
        with patch.dict(os.environ,{'SSH_CONNECTION':'203.0.113.10 50000 179.197.72.245 22'}):
            self.assertEqual(deps.recovery_cidr(None),'203.0.113.10/32')
        with self.assertRaises(ValueError):deps.recovery_cidr('0.0.0.0/0')
    def test_authenticated_package_plan_and_service_policy_restored(self):
        def runner(args):
            self.calls.append(args)
            if '--yes' in args:self.assertIn('exit 101',(self.fs/'usr/sbin/policy-rc.d').read_text())
            return 'fixture version'
        with patch.object(deps,'verify_deployment',return_value={'state':'verified'}):
            result=deps.install(self.root,self.fs,'backup,node',runner=runner)
        self.assertEqual(result['state'],'succeeded');self.assertFalse((self.fs/'usr/sbin/policy-rc.d').exists())
        apt=[args for args in self.calls if args[0]=='apt-get']
        self.assertEqual(len(apt),3)
        for args in apt:self.assertIn('APT::Get::AllowUnauthenticated=false',args)
        self.assertIn('--no-remove',apt[-1]);self.assertIn('--no-upgrade',apt[-1])
        self.assertFalse(result['results']['backup']['delivery_tested'])
    def test_failed_install_keeps_evidence_and_removes_temporary_policy(self):
        def runner(args):
            if '--yes' in args:raise RuntimeError('synthetic package failure')
            return 'ok'
        with patch.object(deps,'verify_deployment',return_value={'state':'verified'}):
            with self.assertRaises(RuntimeError):deps.install(self.root,self.fs,'backup',runner=runner)
        self.assertFalse((self.fs/'usr/sbin/policy-rc.d').exists())
        state=json.loads((self.root/'data/professional-dependencies/status.json').read_text())
        self.assertEqual(state['state'],'package-install-failed-review');self.assertFalse(state['package_rollback'])
    def test_existing_policy_and_removal_plan_stop_before_installation(self):
        path=self.fs/'usr/sbin/policy-rc.d';path.parent.mkdir(parents=True);path.write_text('existing administrator policy')
        with patch.object(deps,'verify_deployment',return_value={'state':'verified'}):
            with self.assertRaises(ValueError):deps.install(self.root,self.fs,'backup',runner=self.runner)
            self.assertEqual(path.read_text(),'existing administrator policy');self.assertEqual(self.calls,[])
            path.unlink()
            with self.assertRaises(ValueError):deps.install(self.root,self.fs,'backup',runner=lambda a:'Remv apache2 [version]\n' if '--simulate' in a else 'ok')
            self.assertFalse(path.exists())
