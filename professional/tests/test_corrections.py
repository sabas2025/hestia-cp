"""Regression tests for the findings in the 19 October audit. No production actions."""
import ctypes
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit, parse_qs
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'professional'))
import apply as deployment
import cloud_backup as cloud
import backup_auth
import mfa
import security
import test_operations as legacy_ops
import test_platform as fixtures
archive = fixtures.archive
private = fixtures.private


class DeploymentCorrections(unittest.TestCase):
    def test_preferences_links_pass_the_native_csrf_contract(self):
        php = os.environ.get('PHP_BINARY')
        if not php: self.fail('PHP_BINARY required for this release check')
        output = subprocess.check_output([php,'-n',str(ROOT/'professional/tests/render_preview.php')],text=True)
        class Links(HTMLParser):
            def __init__(self): super().__init__(); self.urls=[]
            def handle_starttag(self,tag,attrs):
                url=dict(attrs).get('href','')
                if tag=='a' and url.startswith('/edit/user/'):self.urls.append(url)
        links=Links();links.feed(output);self.assertEqual(len(links.urls),2)
        native=(ROOT/'web/inc/main.php').read_text();start=native.index('function verify_csrf(');end=native.index('\n}\n',start)+2
        for url in links.urls:
            query={k:v[0]for k,v in parse_qs(urlsplit(url).query).items()}
            code=native[start:end]+";$_SESSION=['token'=>'PREVIEW_ONLY'];echo json_encode(verify_csrf(json_decode($argv[1],true),true));"
            result=subprocess.check_output([php,'-n','-r',code,json.dumps(query)],text=True)
            self.assertEqual(result,'true')

    def test_refresh_refuses_changed_mfa_without_resealing(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); legacy_ops.OperationsTests().fixture_hestia(root)
            deployment.apply_files(root, ROOT)
            manifest = (root / 'professional/deployment.json').read_bytes()
            target = root / 'web/inc/2fa/secret.php'; target.write_text('<?php /* synthetic replacement */')
            result = deployment.apply_files(root, root, refresh=True)
            self.assertEqual(result['status'], 'review-required')
            self.assertIn('web/inc/2fa/secret.php', result['mismatched'])
            self.assertEqual((root / 'professional/deployment.json').read_bytes(), manifest)
            self.assertIn('synthetic', target.read_text())

    def test_verified_refresh_and_missing_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); legacy_ops.OperationsTests().fixture_hestia(root)
            deployment.apply_files(root, ROOT)
            self.assertEqual(deployment.apply_files(root, root, refresh=True)['status'], 'verified')
            (root / 'professional/deployment.json').unlink()
            self.assertEqual(deployment.apply_files(root, root, refresh=True)['status'], 'review-required')

    def test_experimental_modules_are_not_deployed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); legacy_ops.OperationsTests().fixture_hestia(root)
            deployment.apply_files(root, ROOT)
            for name in deployment.EXPERIMENTAL:
                self.assertFalse((root / 'professional' / name).exists(), name)
            self.assertFalse((root / 'professional/hestia-professional-enterprise.service').exists())

    def test_manifest_detects_permission_changes(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);legacy_ops.OperationsTests().fixture_hestia(root);deployment.apply_files(root,ROOT)
            (root/'web/inc/2fa/secret.php').chmod(0o666)
            self.assertIn('web/inc/2fa/secret.php',deployment.verify_deployment(root)['mismatched'])

    def test_filemanager_requires_explicit_quarantine_and_preserves_contents(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);legacy_ops.OperationsTests().fixture_hestia(root)
            fm=root/'web/fm';fm.mkdir();(fm/'index.php').write_text('legacy optional UI')
            with self.assertRaisesRegex(ValueError,'quarantine'):deployment.apply_files(root,ROOT)
            deployment.apply_files(root,ROOT,quarantine_filemanager=True)
            self.assertFalse(fm.exists())
            saved=list((root/'professional/quarantine').glob('*/index.php'))
            self.assertEqual(len(saved),1);self.assertEqual(saved[0].read_text(),'legacy optional UI')
            self.assertEqual(deployment.config(root/'conf/hestia.conf')['FILE_MANAGER'],'false')
            self.assertIn('HESTIA_PROFESSIONAL_FILEMANAGER_REVIEW',(root/'bin/v-add-sys-filemanager').read_text())

    def test_unknown_auth_hotfix_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); legacy_ops.OperationsTests().fixture_hestia(root)
            target = root / 'web/edit/user/index.php'; target.parent.mkdir(parents=True)
            target.write_text('<?php /* unknown local security patch */')
            with self.assertRaises(ValueError): deployment.apply_files(root, ROOT)
            self.assertIn('unknown local', target.read_text())


class ProtectionCorrections(unittest.TestCase):
    def test_turning_off_managed_components_changes_policy_and_reload(self):
        with tempfile.TemporaryDirectory() as td:
            fs = Path(td); root, cfg = fixtures.ProtectionTests().fixture(fs); calls = []
            def runner(args):
                calls.append(args); return 'security2_module' if args == ['apache2ctl','-M'] else 'ok'
            security.apply_profile(fs, root, cfg, runner)
            off = security.apply_profile(fs, root, {**cfg, 'waf':False, 'fail2ban':False}, runner)
            self.assertIn('SecRuleEngine Off', (fs / security.WAF).read_text())
            self.assertIn('enabled = false', (fs / security.JAIL).read_text())
            self.assertEqual(off['effective_policy'], {'waf':'off','fail2ban':'off'})
            self.assertEqual(off['desired_state'], {'waf':False,'fail2ban':False})
            self.assertTrue(off['managed']['waf'])
            self.assertIn(['systemctl','reload','apache2'], calls)
            security.rollback(fs, root, off['rollback_id'], runner)
            self.assertIn('SecRuleEngine On', (fs / security.WAF).read_text())

    def test_unmanaged_disabled_component_is_not_claimed_off(self):
        with tempfile.TemporaryDirectory() as td:
            fs = Path(td); root, cfg = fixtures.ProtectionTests().fixture(fs)
            result = security.apply_profile(fs, root, {**cfg, 'waf':False}, lambda _: 'ok')
            self.assertIsNone(result['waf'])
            self.assertEqual(result['effective_policy']['waf'], 'unmanaged')


class MfaCorrections(unittest.TestCase):
    def fixture(self, root):
        private(root / 'conf/hestia.conf', "VERSION='1.10.5'\nDEMO_MODE='no'\n")
        return private(root / 'data/users/clientone/user.conf', "SUSPENDED='no'\nLOGIN_DISABLED='no'\nTWOFA=''\nQRCODE=''\n")

    def op(self, root, action, code='', now=1800000000, password='correct', binding='a'*64):
        return mfa.operate(root, 'clientone', action, {'password':password,'code':code,'binding':binding},
                           verifier=lambda user, password: user == 'clientone' and password == 'correct', now=now, keystore=root/'external-keys')

    def enroll(self, root):
        pending = self.op(root, 'prepare'); seed = pending['manual_key']
        enabled = self.op(root, 'enable', mfa.totp(seed, 1800000000//30))
        return seed, enabled

    def test_rfc_totp_vector_and_password_libcrypt(self):
        self.assertEqual(mfa.totp('GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ', 1), '287082')
        lib = ctypes.CDLL('libcrypt.so.1'); lib.crypt.argtypes = [ctypes.c_char_p,ctypes.c_char_p]; lib.crypt.restype=ctypes.c_char_p
        digest = lib.crypt(b'synthetic-password', b'$6$audit-test$').decode()
        with patch.object(Path, 'read_text', return_value='clientone:'+digest+':0:0:0:0:0:0:0\n'):
            self.assertTrue(mfa.password_ok('clientone', 'synthetic-password'))
            self.assertFalse(mfa.password_ok('clientone', 'wrong'))

    def test_pending_does_not_enable_and_wrong_code_refused(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); account=self.fixture(root); pending=self.op(root,'prepare')
            self.assertEqual(mfa.config(account)['TWOFA'],'')
            wrong = str((int(mfa.totp(pending['manual_key'],1800000000//30))+123)%1000000).zfill(6)
            with self.assertRaises(ValueError): self.op(root,'enable',wrong)
            self.assertEqual(mfa.config(account)['TWOFA'],'')

    def test_session_expiry_and_password_are_required(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); self.fixture(root)
            with self.assertRaises(ValueError): self.op(root,'prepare',password='wrong')
            pending=self.op(root,'prepare'); code=mfa.totp(pending['manual_key'],1800000000//30)
            with self.assertRaises(ValueError): self.op(root,'enable',code,binding='b'*64)
            with self.assertRaises(ValueError): self.op(root,'enable',code,now=1800000700)

    def test_pending_seed_is_encrypted_and_bound_to_account(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);self.fixture(root);pending=self.op(root,'prepare')
            record=json.loads((root/'data/professional-mfa/clientone.json').read_text())
            self.assertNotIn(pending['manual_key'],json.dumps(record))
            cipher=record['pending']['seed']
            self.assertEqual(mfa.reveal_seed(cipher,'clientone',root/'external-keys'),pending['manual_key'])
            with self.assertRaises(ValueError):mfa.reveal_seed(cipher,'anotheruser',root/'external-keys')

    def test_codes_are_hashed_single_use_and_seed_is_not_recovery(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); self.fixture(root); seed,enabled=self.enroll(root)
            state=root/'data/professional-mfa/clientone.json'; raw=state.read_text()
            self.assertNotIn('pending',raw); self.assertNotIn(seed,raw)
            self.assertEqual(state.stat().st_mode & 0o777,0o600)
            for code in enabled['recovery_codes']: self.assertNotIn(code,raw)
            code=enabled['recovery_codes'][0]
            self.assertEqual(self.op(root,'verify',code)['state'],'verified')
            with self.assertRaises(ValueError): self.op(root,'verify',code)
            with self.assertRaises(ValueError): self.op(root,'verify',seed)

    def test_disable_requires_password_and_fresh_factor(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); account=self.fixture(root); seed,_=self.enroll(root)
            current=mfa.totp(seed,1800000030//30)
            with self.assertRaises(ValueError): self.op(root,'disable',current,password='wrong',now=1800000030)
            self.assertTrue(mfa.config(account)['TWOFA'])
            self.assertEqual(self.op(root,'disable',current,now=1800000030)['state'],'disabled')
            self.assertEqual(mfa.config(account)['TWOFA'],'')

    def test_replay_rate_limit_and_recovery_rotation(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); self.fixture(root); seed,enabled=self.enroll(root)
            with self.assertRaises(ValueError): self.op(root,'verify',mfa.totp(seed,1800000000//30))
            self.op(root,'recovery',enabled['recovery_codes'][0])
            with self.assertRaises(ValueError): self.op(root,'verify',enabled['recovery_codes'][1])
            for _ in range(10):
                with self.assertRaises(ValueError): self.op(root,'verify','invalid')
            with self.assertRaises(ValueError): self.op(root,'verify',mfa.totp(seed,1800000030//30),now=1800000030)

    def test_readonly_and_suspended_refuse_mutation(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); account=self.fixture(root)
            (root/'conf/hestia.conf').write_text("DEMO_MODE='yes'\n")
            with self.assertRaises(ValueError): self.op(root,'prepare')
            (root/'conf/hestia.conf').write_text("DEMO_MODE='no'\n")
            account.write_text("SUSPENDED='yes'\n")
            with self.assertRaises(ValueError): self.op(root,'prepare')

    def test_password_change_reauth_requires_the_enrolled_factor(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);self.fixture(root);seed,_=self.enroll(root)
            with self.assertRaises(ValueError):self.op(root,'reauth',now=1800000030)
            code=mfa.totp(seed,1800000030//30)
            self.assertEqual(self.op(root,'reauth',code,now=1800000030)['state'],'reauthenticated')

    def test_native_seed_rotation_invalidates_old_recovery(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);account=self.fixture(root);_,enabled=self.enroll(root)
            new_seed='GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ'
            mfa.set_seed(account,new_seed)
            with self.assertRaises(ValueError):self.op(root,'verify',enabled['recovery_codes'][0])
            code=mfa.totp(new_seed,1800000000//30)
            self.assertEqual(self.op(root,'verify',code)['state'],'verified')


class BackupCorrections(unittest.TestCase):
    def test_archive_with_live_mfa_seed_is_refused(self):
        import tarfile
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'unsafe.tar'
            with tarfile.open(path,'w')as tar:
                raw=b"TWOFA='SYNTHETIC_SEED'\nQRCODE=''\n"
                info=tarfile.TarInfo('hestia/user.conf');info.size=len(raw);tar.addfile(info,io.BytesIO(raw))
            with self.assertRaisesRegex(ValueError,'MFA'):cloud.validate_archive(path,{'web':[],'db':[]})
    def test_native_backup_copy_omits_seed_and_requires_reenrollment(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);root.chmod(0o700);copy=root/'hestia/user.conf'
            original=private(root/'original.conf',"TWOFA='SYNTHETIC_SEED'\nQRCODE='SYNTHETIC_QR'\nLOGIN_DISABLED='no'\n")
            private(copy,original.read_text());before=original.read_bytes()
            self.assertTrue(backup_auth.sanitize(copy))
            text=copy.read_text();self.assertNotIn('SYNTHETIC_SEED',text);self.assertNotIn('SYNTHETIC_QR',text)
            self.assertEqual(cloud.config(copy)['LOGIN_DISABLED'],'yes')
            self.assertEqual(original.read_bytes(),before)
            with self.assertRaises(ValueError):backup_auth.sanitize(original)

    def test_attempt_failure_is_saved_without_deleting_last_success(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); fixture=fixtures.CloudTests();folder=fixture.account(root)
            path,_,_=fixture.fixture(root); cfg=cloud.settings(path)
            def good(args,env=None):
                if args[0].endswith('v-backup-user'):
                    archive(folder/'testuser.new.tar',['web/site.invalid/domain_data.tar.gz','db/app_main/app_main.mysql.sql.gz'])
                if args[:2]==['restic','backup']:
                    self.assertTrue(args[-1].endswith('account-manifest.json'))
                    manifest=json.loads(Path(args[-1]).read_text());self.assertEqual(manifest['inventory']['db'],['app_main'])
                    return json.dumps({'message_type':'summary','snapshot_id':'a'*64})
                return ''
            cloud.execute('run','testuser',cfg,root,runner=good)
            old=(root/'data/professional/backups/testuser-main-copy-run.json').read_bytes()
            def bad(args,env=None):
                if args[:2]==['restic','backup']:raise RuntimeError('synthetic')
                return good(args,env)
            cloud.execute('run','testuser',cfg,root,runner=bad)
            self.assertEqual((root/'data/professional/backups/testuser-main-copy-run.json').read_bytes(),old)
            attempt=json.loads((root/'data/professional/backups/testuser-main-copy-attempt.json').read_text())
            self.assertEqual(attempt['state'],'failed')

    def test_nested_corruption_is_detected_and_valid_stream_checked(self):
        import tarfile
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); path=root/'account.tar'
            def make(data):
                with tarfile.open(path,'w') as outer:
                    info=tarfile.TarInfo('db/test/db.mysql.sql.gz');info.size=len(data);outer.addfile(info,io.BytesIO(data))
            make(gzip.compress(b'CREATE TABLE audit_test (id int);'))
            self.assertEqual(cloud.verify_nested(path)['compressed_streams_verified'],1)
            make(b'corrupt gzip')
            with self.assertRaises(OSError):cloud.verify_nested(path)

    def test_drill_uses_historical_inventory_and_checks_hash(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);path=root/'testuser.old.tar';archive(path,['web/old.invalid/domain_data.tar.gz'])
            manifest={'schema':1,'user':'testuser','inventory':{'web':['old.invalid'],'db':[]},'archive_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
            (root/'account-manifest.json').write_text(json.dumps(manifest))
            expected=cloud.recovery_inventory(root,path,'testuser')
            self.assertEqual(cloud.validate_archive(path,expected)['sites'],1)
            path.write_bytes(b'changed')
            with self.assertRaises(ValueError):cloud.recovery_inventory(root,path,'testuser')

    def test_legacy_drill_without_manifest_requires_review(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);path=root/'testuser.old.tar';archive(path,['web/site.invalid/domain_data.tar.gz'])
            with self.assertRaisesRegex(ValueError,'historical inventory'):cloud.recovery_inventory(root,path,'testuser')
