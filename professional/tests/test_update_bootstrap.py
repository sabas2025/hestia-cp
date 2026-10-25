"""Pinned updater queue: no SSH credentials, no reinstall and no early success."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
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
