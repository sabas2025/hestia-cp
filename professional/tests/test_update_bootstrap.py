"""Pinned updater queue: no SSH credentials, no reinstall and no early success."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('update_bootstrap',ROOT/'ops/vps-atualizar.py')
u=importlib.util.module_from_spec(spec);spec.loader.exec_module(u)

class UpdateBootstrapTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name);self.source=self.base/'source';self.source.mkdir()
        self.patcher=patch.object(u,'STATE',self.base/'state');self.patcher.start();self.addCleanup(self.patcher.stop)
        self.calls=[]
    def runner(self,args,**kwargs):
        self.calls.append(args)
        if 'plan' in args:return '{"state":"ready"}'
        if 'apply' in args:return '{"state":"succeeded","backup":"private-fixture"}'
        if '--components' in args:return '{"state":"succeeded","results":{}}'
        return '{}'
    def test_task_contains_no_secret_and_acceptance_is_not_success(self):
        result=u.start('backup',None,self.runner,lambda:self.source)
        self.assertEqual(result['state'],'queued');self.assertFalse(result['installer_executed'])
        self.assertFalse(any('hst-install' in ' '.join(args) for args in self.calls))
        self.assertNotIn('password',json.dumps(result))
        job=u.read_json(u.STATE/'job.json')
        value=u.worker(job['nonce'],self.runner,lambda:self.source)
        self.assertEqual(value['state'],'succeeded');self.assertTrue(value['overlay_updated'])
        self.assertNotIn('nonce',value);self.assertNotIn('components',value)
        with self.assertRaises(ValueError):u.worker(job['nonce'],self.runner,lambda:self.source)
    def test_dependency_failure_preserves_overlay_success_but_fails_whole_job(self):
        u.start('backup',None,self.runner,lambda:self.source);job=u.read_json(u.STATE/'job.json')
        def fail(args,**kwargs):
            if '--components' in args:raise RuntimeError('synthetic package failure')
            return self.runner(args,**kwargs)
        with self.assertRaises(RuntimeError):u.worker(job['nonce'],fail,lambda:self.source)
        value=u.status();self.assertEqual(value['state'],'failed');self.assertTrue(value['overlay_updated'])
        self.assertEqual(value['phase'],'prerequisites')
    def test_wrong_nonce_and_invalid_components_never_execute(self):
        for value in ('backup;id','backup,backup','unexpected'):
            with self.assertRaises(ValueError):u.start(value,None,self.runner,lambda:self.source)
        self.assertEqual(self.calls,[])
        u.start('',None,self.runner,lambda:self.source);calls=len(self.calls)
        with self.assertRaises(ValueError):u.worker('bad',self.runner,lambda:self.source)
        self.assertEqual(len(self.calls),calls)
    def test_manifest_verifies_all_source_bytes_and_rejects_tampering(self):
        (self.source/'file.txt').write_text('approved source')
        sums=hashlib.sha256(b'approved source').hexdigest()+'  file.txt\n'
        (self.source/'SHA256SUMS').write_text(sums)
        expected=hashlib.sha256(sums.encode()).hexdigest()
        u.verify_bundle(self.source,expected,2)
        (self.source/'file.txt').write_text('unapproved source')
        with self.assertRaises(ValueError):u.verify_bundle(self.source,expected,2)
    def test_systemd_cleanup_removes_only_own_temporary_policy_and_marks_interruption(self):
        u.start('',None,self.runner,lambda:self.source);job=u.read_json(u.STATE/'job.json')
        policy=self.base/'policy-rc.d';policy.write_bytes(u.TEMPORARY_POLICY);policy.chmod(0o755)
        with patch.object(u,'POLICY',policy):
            with self.assertRaises(ValueError):u.cleanup('foreign nonce')
            self.assertTrue(policy.exists());result=u.cleanup(job['nonce'])
        self.assertFalse(policy.exists());self.assertEqual(result['state'],'interrupted-review')
        command=self.calls[-1];self.assertTrue(any(value.startswith('--property=ExecStopPost=') for value in command))
    def test_cleanup_preserves_custom_policy_and_duplicate_requests_are_refused(self):
        u.start('',None,self.runner,lambda:self.source);job=u.read_json(u.STATE/'job.json')
        with self.assertRaises(ValueError):u.start('',None,self.runner,lambda:self.source)
        policy=self.base/'policy-rc.d';policy.write_text('custom administrator policy');policy.chmod(0o755)
        with patch.object(u,'POLICY',policy):u.cleanup(job['nonce'])
        self.assertEqual(policy.read_text(),'custom administrator policy')

    def source_fixture(self):
        target=u.STATE/'sources'/u.SOURCE;target.mkdir(parents=True)
        code=b'value=42\n';(target/'fixture_source.py').write_bytes(code)
        sums=hashlib.sha256(code).hexdigest()+'  fixture_source.py\n';(target/'SHA256SUMS').write_text(sums)
        raw=io.BytesIO()
        with zipfile.ZipFile(raw,'w') as archive:
            archive.writestr('source/fixture_source.py',code);archive.writestr('source/SHA256SUMS',sums)
        data=raw.getvalue()
        class Response(io.BytesIO):
            def geturl(self):return 'https://codeload.github.com/sabas2025/hestia-cp/zip/'+u.SOURCE
        opener=type('Opener',(),{'open':lambda *args,**kwargs:Response(data)})()
        constants=patch.multiple(u,SUMS_SHA256=hashlib.sha256(sums.encode()).hexdigest(),EXPECTED_FILES=2)
        constants.start();self.addCleanup(constants.stop)
        network=patch.object(u.urllib.request,'build_opener',return_value=opener);network.start();self.addCleanup(network.stop)
        return target

    def test_real_python_import_cache_is_rejected_preserved_and_replaced_by_verified_source(self):
        target=self.source_fixture();u.verify_bundle(target)
        code='import sys;sys.path.insert(0,'+repr(str(target))+');import fixture_source'
        subprocess.run([sys.executable,'-I','-c',code],check=True)
        self.assertTrue(list(target.glob('__pycache__/*.pyc')))
        with self.assertRaisesRegex(ValueError,'Unexpected source files'):u.verify_bundle(target)
        fresh=u.bundle();u.verify_bundle(fresh)
        self.assertFalse((fresh/'__pycache__').exists())
        saved=list((u.STATE/'quarantine').iterdir());self.assertEqual(len(saved),1)
        self.assertTrue(list(saved[0].glob('__pycache__/*.pyc')))
        self.assertEqual(u.bundle(),fresh)

    def test_unapproved_extra_or_corrupt_source_is_never_accepted_or_deleted(self):
        target=self.source_fixture();(target/'unexpected.php').write_text('unapproved fixture')
        (target/'fixture_source.py').write_text('modified fixture')
        fresh=u.bundle();u.verify_bundle(fresh)
        preserved=list((u.STATE/'quarantine').iterdir())[0]
        self.assertEqual((preserved/'unexpected.php').read_text(),'unapproved fixture')
        self.assertEqual((preserved/'fixture_source.py').read_text(),'modified fixture')
        self.assertEqual((fresh/'fixture_source.py').read_text(),'value=42\n')

    def test_invalid_cache_is_not_moved_under_a_pending_task(self):
        target=self.source_fixture();(target/'unexpected.txt').write_text('fixture')
        u.write_json(u.STATE/'job.json',{'state':'running'})
        with self.assertRaisesRegex(ValueError,'pending'):u.bundle()
        self.assertTrue(target.exists());self.assertFalse((u.STATE/'quarantine').exists())

    def test_preflight_and_worker_disable_bytecode_and_blocked_plan_never_queues(self):
        result=u.inspect_plan(self.source,self.runner);self.assertEqual(result['state'],'ready')
        self.assertIn('-B',self.calls[-1])
        with self.assertRaisesRegex(ValueError,'local configuration differs'):
            u.start('',None,lambda args:'{"state":"blocked","reason":"local configuration differs"}',lambda:self.source)
        self.assertFalse((u.STATE/'job.json').exists())
        u.start('',None,self.runner,lambda:self.source);job=u.read_json(u.STATE/'job.json')
        u.worker(job['nonce'],self.runner,lambda:self.source)
        source_calls=[args for args in self.calls if str(self.source/'professional/upgrade.py') in args]
        self.assertTrue(source_calls)
        for args in source_calls:self.assertIn('-B',args)

    def test_real_probe_reports_blocker_without_creating_bytecode(self):
        professional=self.source/'professional';professional.mkdir()
        (professional/'upgrade.py').write_text(
            "regular=lambda *args:None\n"
            "class overlay:\n"
            " @staticmethod\n"
            " def verify_deployment(root):return {'state':'verified'}\n"
            "def preflight(root,source):raise ValueError('fixture native configuration mismatch')\n")
        result=u.inspect_plan(self.source)
        self.assertEqual(result['state'],'blocked');self.assertEqual(result['phase'],'installed-preflight')
        self.assertEqual(result['reason'],'fixture native configuration mismatch')
        self.assertFalse((professional/'__pycache__').exists())

    def test_main_reports_blocked_plan_with_nonzero_exit_and_without_requiring_network_cidr(self):
        import contextlib
        out=io.StringIO()
        with patch('sys.argv',['update','plan']),patch.object(u,'bundle',return_value=self.source),patch.object(u,'inspect_plan',return_value={'state':'blocked','reason':'fixture mismatch'}),contextlib.redirect_stdout(out):
            self.assertEqual(u.main(),1)
        self.assertEqual(json.loads(out.getvalue())['reason'],'fixture mismatch')
