"""Isolated bootstrap tests. Never install software or change host SSH settings."""
from contextlib import nullcontext
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import shutil
import stat
import tarfile
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from unittest.mock import patch
import zipfile

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('vps_deploy',ROOT/'ops/vps-implantacao.py')
d=importlib.util.module_from_spec(spec);sys.modules[spec.name]=d;spec.loader.exec_module(d)

class VPSDeployTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.base=Path(self.temp.name)
        for name,value in [('STATE',self.base/'state'),('CONFIG',self.base/'config'),('ROOT',self.base/'installed'),('KEY',self.base/'ssh/public.pub'),('AUTHORIZED',self.base/'ssh/authorized_keys'),('APT_KEYRING',self.base/'keyrings/hestia-keyring.gpg'),('NATIVE_BACKUPS',self.base/'native-backups'),('NATIVE_LOCK',self.base/'native-lock/install.lock'),('HOSTS',self.base/'hosts')]:
            patcher=patch.object(d,name,value);patcher.start();self.addCleanup(patcher.stop)
        d.private_dir(d.CONFIG);d.private_dir(d.STATE)
        d.write_json(d.CONFIG/'config.json',{'hostname':'panel.example.com','email':'admin@example.com','username':'admin','source':d.SOURCE})
        d.atomic(d.CONFIG/'admin-password',b'SyntheticPassword123!')
        self.source=self.base/'source';(self.source/'install').mkdir(parents=True)
        (self.source/'install/hst-install-ubuntu.sh').write_text('before\ncat $tmpfile | $send_mail -s "Hestia Control Panel" $email\nafter\n')
        (self.source/'install/assets.lock.tsv').write_text(d.OLD_APT_ASSET+'\n')
    def ready(self):return {'state':'ready','hostname':'panel.example.com','url':'https://panel.example.com:8083'}
    def queue(self):return d.start(runner=lambda args:'',planner=self.ready)
    def test_ssh_allowlist_rejects_shell_commands_and_setup(self):
        for action in ('plan','start','status'):self.assertEqual(d.ssh_action(str(d.HELPER)+' '+action),action)
        for cmd in ('bash','id',str(d.HELPER)+' setup',str(d.HELPER)+' set-user --username sabasadmin',str(d.HELPER)+' recover-apt-key',str(d.HELPER)+' start; id',str(d.HELPER)+' worker abc',''):
            with self.subTest(cmd=cmd),self.assertRaises(ValueError):d.ssh_action(cmd)
    def test_configuration_and_password_validation(self):
        self.assertTrue(d.valid_password('SyntheticPassword123!'))
        for pw in ('short','alllowercase123456','NOLOWERCASE123456','NoDigitsInPassword','Synthetic:Password1','SyntheticPassword1\n'):
            self.assertFalse(d.valid_password(pw))
        cfg=d.settings();cfg['source']='bad';d.write_json(d.CONFIG/'config.json',cfg)
        with self.assertRaises(ValueError):d.settings()
    def test_switch_panel_username_preserves_password_and_system_groups(self):
        before=d.read_file(d.CONFIG/'admin-password');calls=[]
        def missing(args):calls.append(args);raise RuntimeError('unknown account')
        result=d.set_user('sabasadmin',runner=missing)
        self.assertTrue(result['password_preserved']);self.assertFalse(result['system_users_or_groups_modified'])
        self.assertEqual(d.read_file(d.CONFIG/'admin-password'),before)
        self.assertEqual(d.settings()['username'],'sabasadmin')
        self.assertEqual(calls,[['/usr/bin/getent','passwd','sabasadmin'],['/usr/bin/getent','group','sabasadmin']])
        self.assertEqual(len(list(d.CONFIG.glob('config.before-user-*.json'))),1)
        args=d.installer_args(self.source,d.settings());self.assertEqual(args[args.index('--username')+1],'sabasadmin')
    def test_switch_username_refuses_reserved_existing_or_started_installation(self):
        for name in ('root','mysql','../admin','admin;id','AUser'):
            with self.subTest(name=name),self.assertRaises(ValueError):d.set_user(name)
        with self.assertRaises(ValueError):d.set_user('existing',runner=lambda args:'found')
        self.queue()
        with self.assertRaises(ValueError):d.set_user('sabasadmin',runner=lambda args:'')
        self.assertEqual(d.settings()['username'],'admin')
    def test_existing_admin_group_does_not_block_free_custom_panel_account(self):
        def runner(args):
            if 'getent' in args[0]:
                if args[1:]==['group','admin']:return 'admin:x:123:\n'
                raise RuntimeError('unknown account')
            return 'Inspection result: PASS'
        def resolver(host,port,family,kind):
            if family==socket.AF_INET6:raise socket.gaierror()
            return [(0,0,0,'',(d.TARGET_IP,port))]
        first=d.plan(resolver,runner,lambda:self.source,netplan=self.base/'netplan')
        self.assertEqual(first['state'],'blocked');self.assertIn('Administrator group already exists: admin',first['reasons'])
        d.set_user('sabasadmin',runner=runner)
        second=d.plan(resolver,runner,lambda:self.source,netplan=self.base/'netplan')
        self.assertEqual(second['state'],'ready');self.assertEqual(second['username'],'sabasadmin')
    def test_private_files_reject_modes_links_and_writable_parents(self):
        p=d.CONFIG/'admin-password';p.chmod(0o644)
        with self.assertRaises(ValueError):d.read_file(p)
        link=d.CONFIG/'link';link.symlink_to(p)
        with self.assertRaises(ValueError):d.read_file(link)
        p.chmod(0o600);d.CONFIG.chmod(0o777)
        with self.assertRaises(ValueError):d.read_file(p)
    def test_authorized_keys_preserves_other_keys_and_last_newline(self):
        key='ssh-ed25519 '+'A'*64
        old='ssh-ed25519 '+'B'*64+' existing\nrestrict,command="/usr/local/sbin/hestia-github-diagnostico" '+key+' old\nother-key-without-newline'
        result=d.replace_authorization(old,key+' comment')
        self.assertIn('other-key-without-newline\nrestrict',result)
        self.assertIn('B'*64,result);self.assertEqual(result.count('A'*64),1)
        self.assertIn('command="'+str(d.HELPER)+'"',result)
        self.assertEqual(d.replace_authorization(result,key),result)
    def test_console_setup_updates_only_dedicated_key_and_keeps_password_private(self):
        (d.CONFIG/'config.json').unlink();(d.CONFIG/'admin-password').unlink()
        d.private_dir(d.KEY.parent)
        generated=self.base/'identity'
        subprocess.run(['/usr/bin/ssh-keygen','-q','-t','ed25519','-N','','-f',str(generated)],check=True)
        d.KEY.write_bytes(generated.with_suffix('.pub').read_bytes())
        d.AUTHORIZED.write_text('ssh-ed25519 '+'B'*64+' preserve\n')
        value=d.setup('panel.example.com','admin@example.com',reader=lambda prompt:'SyntheticPassword123!')
        self.assertNotIn('SyntheticPassword',json.dumps(value))
        self.assertEqual((d.CONFIG/'admin-password').stat().st_mode&0o777,0o600)
        self.assertEqual(d.AUTHORIZED.stat().st_mode&0o777,0o600)
        self.assertIn('B'*64,d.AUTHORIZED.read_text());self.assertIn(str(d.HELPER),d.AUTHORIZED.read_text())
        self.assertEqual(len(list(d.CONFIG.glob('authorized_keys.before-*'))),1)
    def zip_bytes(self, entries):
        output=io.BytesIO()
        with zipfile.ZipFile(output,'w') as archive:
            for name,content,mode in entries:
                entry=zipfile.ZipInfo(name);entry.external_attr=mode<<16;archive.writestr(entry,content)
        return output.getvalue()
    def test_zip_paths_and_links_are_rejected(self):
        for name,mode in [('root/../outside',0o100644),('/outside',0o100644),('root/link',0o120777),('root\\outside',0o100644)]:
            target=self.base/'unpack';target.mkdir(exist_ok=True)
            with self.subTest(name=name),self.assertRaises(ValueError):d.unpack(self.zip_bytes([(name,b'bad',mode)]),target)
    def test_checksum_manifest_pinning_and_extra_files(self):
        target=self.base/'bundle';target.mkdir();(target/'file').write_bytes(b'approved')
        sums=(hashlib.sha256(b'approved').hexdigest()+'  file\n').encode();(target/'SHA256SUMS').write_bytes(sums)
        pin=hashlib.sha256(sums).hexdigest();d.verify_bundle(target,pin,2)
        (target/'extra').write_text('bad')
        with self.assertRaises(ValueError):d.verify_bundle(target,pin,2)
        (target/'extra').unlink();(target/'file').write_text('tampered')
        with self.assertRaises(ValueError):d.verify_bundle(target,pin,2)
        with self.assertRaises(ValueError):d.verify_bundle(target,'0'*64,2)
    def test_valid_zip_preserves_execution_mode(self):
        target=self.base/'valid';target.mkdir()
        d.unpack(self.zip_bytes([('root/run',b'#!/bin/bash\n',0o100755)]),target)
        self.assertEqual((target/'run').stat().st_mode&0o777,0o755)
    def test_plan_blocks_missing_and_wrong_dns_and_ipv6(self):
        def runner(args):
            if 'getent' in args[0]:raise RuntimeError('not found')
            return 'Inspection result: PASS'
        for resolver in (lambda *a:[],lambda *a:[(0,0,0,'',('192.0.2.10',8083))]):
            self.assertEqual(d.plan(resolver,runner,lambda:self.source,netplan=self.base/'netplan')['state'],'blocked')
        def ipv4_only(host,port,family,kind):
            if family==socket.AF_INET6:raise socket.gaierror()
            return [(0,0,0,'',(d.TARGET_IP,port))]
        self.assertEqual(d.plan(ipv4_only,runner,lambda:self.source,netplan=self.base/'netplan')['state'],'ready')
        (self.base/'netplan').mkdir()
        self.assertEqual(d.plan(ipv4_only,runner,lambda:self.source,netplan=self.base/'netplan')['state'],'blocked')
    def test_start_is_single_use_and_contains_no_password(self):
        calls=[];result=d.start(runner=lambda args:calls.append(args),planner=self.ready)
        self.assertEqual(result['state'],'queued');self.assertIn('--property=RuntimeMaxSec=5400',calls[0])
        self.assertNotIn('SyntheticPassword',json.dumps(calls))
        with self.assertRaises(ValueError):self.queue()
    def test_start_acknowledges_queue_even_if_worker_is_already_running(self):
        def runner(args):
            job=d.read_json(d.STATE/'job.json');job['state']='running';d.write_json(d.STATE/'job.json',job)
        response=d.start(runner=runner,planner=self.ready)
        self.assertEqual(response['state'],'queued');self.assertEqual(d.status()['state'],'running')
    def test_blocked_plan_never_starts_service(self):
        calls=[];result=d.start(runner=lambda args:calls.append(args),planner=lambda:{'state':'blocked','reasons':['DNS']})
        self.assertEqual(result['state'],'blocked');self.assertEqual(calls,[]);self.assertFalse((d.STATE/'job.json').exists())
    def test_launch_failure_is_recorded_without_deleting_password(self):
        def runner(args):raise RuntimeError('systemd unavailable')
        with self.assertRaises(RuntimeError):d.start(runner=runner,planner=self.ready)
        self.assertEqual(d.status()['state'],'launch-failed');self.assertTrue((d.CONFIG/'admin-password').exists())
    def test_install_args_use_local_password_file_and_native_profile(self):
        args=d.installer_args(self.source,d.settings())
        self.assertIn('--password-file',args);self.assertNotIn('--password',args)
        self.assertEqual(args[args.index('--hostname')+1],'panel.example.com')
        self.assertNotIn('SyntheticPassword',str(args));self.assertNotIn('--force',args)
    def test_welcome_message_is_disabled_with_exact_contract(self):
        d.suppress_welcome_email(self.source)
        self.assertNotIn('cat $tmpfile | $send_mail',(self.source/'install/hst-install-ubuntu.sh').read_text())
        with self.assertRaises(ValueError):d.suppress_welcome_email(self.source)
    def test_working_copy_uses_repository_key_and_preserves_original(self):
        target=self.base/'corrected';shutil.copytree(self.source,target)
        d.correct_apt_asset(target)
        self.assertEqual((target/'install/assets.lock.tsv').read_text(),d.APT_ASSET+'\n')
        self.assertEqual((self.source/'install/assets.lock.tsv').read_text(),d.OLD_APT_ASSET+'\n')
        with self.assertRaises(ValueError):d.correct_apt_asset(target)
        (target/'install/assets.lock.tsv').write_text(d.OLD_APT_ASSET+'\n'+d.OLD_APT_ASSET+'\n')
        with self.assertRaises(ValueError):d.correct_apt_asset(target)
    def failed_repository_fixture(self):
        job=self.queue();job.update(state='failed',phase='installing');d.write_json(d.STATE/'job.json',job)
        (d.CONFIG/'admin-password').unlink()
        (d.STATE/'working').mkdir();(d.STATE/'working/evidence').write_text('preserve')
        self.hosts_original=b'127.0.0.1 localhost\n::1 localhost ip6-localhost\n'
        d.HOSTS.write_bytes(self.hosts_original);d.HOSTS.chmod(0o644)
        output=io.BytesIO()
        with tarfile.open(fileobj=output,mode='w:gz') as archive:
            member=tarfile.TarInfo('etc/hosts');member.size=len(self.hosts_original);member.mode=0o644
            archive.addfile(member,io.BytesIO(self.hosts_original))
        d.atomic(d.STATE/'configuration-before.tar.gz',output.getvalue())
        native_name='hst_install-20261025T083303Z-18039.log'
        d.atomic(d.STATE/'installation.log',('ERROR: Refresh package indexes failed (status 100); see /root/hst_install_backups/'+native_name+'\n').encode())
        events=['START Refresh package indexes','END Refresh package indexes status=0',
                'START Install bootstrap dependencies','END Install bootstrap dependencies status=0',
                'START Refresh package indexes']
        text=''.join('2026-10-25T08:33:03Z '+v+'\n' for v in events)
        text+='W: https://apt.hestiacp.com resolute NO_PUBKEY A189E93654F0B0E5\n'
        text+='2026-10-25T08:33:25Z END Refresh package indexes status=100\n'
        d.atomic(d.NATIVE_BACKUPS/native_name,text.encode())
        d.private_dir(d.APT_KEYRING.parent);d.APT_KEYRING.parent.chmod(0o755)
        home=d.private_dir(self.base/'old-gpg')
        d.checked(['/usr/bin/gpg','--homedir',str(home),'--batch','--yes','--dearmor','--output',str(d.APT_KEYRING),str(ROOT/'install/deb/deb_signing.key')])
        self.recovery_calls=[]
        return job,d.NATIVE_BACKUPS/native_name
    def recovery_runner(self,args,timeout=60,log=None):
        self.recovery_calls.append(args)
        if args[0]=='/usr/bin/systemctl':return ''
        if args[0]=='/bin/bash':return 'Inspection result: PASS\n'
        if args[0]=='/usr/bin/curl':
            key=Path(args[args.index('--output')+1]);key.write_bytes((ROOT/'professional/tests/fixtures/hestia-apt-key.asc').read_bytes());key.chmod(0o600);return ''
        if args[0]=='/usr/bin/gpg':return d.checked(args,timeout=timeout,log=log)
        if args[0]=='/usr/bin/apt-get':
            self.assertIsNotNone(log);log.write(b'synthetic authenticated update\n');return ''
        raise AssertionError('Unexpected recovery command: '+str(args))
    def recover_fixture(self,runner=None,reader=None,planner=None):
        return d.recover_apt_key(reader=reader or (lambda prompt:'SyntheticPassword123!'),runner=runner or self.recovery_runner,
                                 planner=planner or self.ready,source_loader=lambda:self.source)
    def test_repository_recovery_preserves_evidence_and_never_installs(self):
        job,native=self.failed_repository_fixture();native_before=native.read_bytes()
        value=self.recover_fixture();history=Path(value['history'])
        self.assertEqual(value['state'],'recovered');self.assertFalse(value['installer_executed'])
        self.assertEqual(d.status()['state'],'not-started');self.assertEqual(native.read_bytes(),native_before)
        self.assertEqual(d.read_json(history/'job.json')['id'],job['id'])
        self.assertEqual((history/'working/evidence').read_text(),'preserve')
        self.assertEqual((history/'keyring-before.gpg').stat().st_mode&0o777,0o600)
        self.assertEqual(hashlib.sha256(d.APT_KEYRING.read_bytes()).hexdigest(),d.APT_KEYRING_SHA256)
        self.assertEqual(d.APT_KEYRING.stat().st_mode&0o777,0o644);self.assertEqual(d.APT_KEYRING.parent.stat().st_mode&0o777,0o755)
        self.assertTrue(d.valid_password(d.read_file(d.CONFIG/'admin-password').decode()))
        self.assertNotIn('--apply',str(self.recovery_calls));self.assertNotIn('SyntheticPassword',str(value)+str(self.recovery_calls))
        self.assertEqual([a for a in self.recovery_calls if a[0]=='/usr/bin/apt-get'],[['/usr/bin/apt-get','-o','APT::Update::Error-Mode=any','update']])
    def test_recovery_restores_only_exact_native_hosts_addition_before_real_plan(self):
        self.failed_repository_fixture()
        appended=self.hosts_original+b'127.0.0.1 panel.example.com\n';d.HOSTS.write_bytes(appended)
        def resolver(host,port,family,kind):
            if family==socket.AF_INET6:raise socket.gaierror()
            address='127.0.0.1' if b'127.0.0.1 panel.example.com' in d.HOSTS.read_bytes() else d.TARGET_IP
            return [(0,0,0,'',(address,port))]
        def runner(args):
            if args[0]=='/usr/bin/getent':raise RuntimeError('account absent')
            return 'Inspection result: PASS'
        def planner():return d.plan(resolver,runner,lambda:self.source,netplan=self.base/'netplan')
        d.atomic(d.CONFIG/'admin-password',b'SyntheticPassword123!')
        self.assertEqual(planner()['state'],'blocked');(d.CONFIG/'admin-password').unlink()
        result=self.recover_fixture(planner=planner)
        self.assertEqual(result['state'],'recovered');self.assertTrue(result['hosts_restored_from_verified_backup'])
        self.assertEqual(d.HOSTS.read_bytes(),self.hosts_original);self.assertEqual(d.HOSTS.stat().st_mode&0o777,0o644)
        self.assertEqual(d.read_file(Path(result['history'])/'hosts-before-recovery'),appended)
        self.assertEqual(planner()['state'],'ready')
    def test_unrelated_hosts_changes_are_preserved_and_block_recovery(self):
        self.failed_repository_fixture()
        changed=self.hosts_original+b'192.0.2.9 custom.example.com\n';d.HOSTS.write_bytes(changed)
        before=d.APT_KEYRING.read_bytes()
        with self.assertRaises(d.RecoveryBlocked) as error:self.recover_fixture()
        self.assertIn('/etc/hosts',str(error.exception.reasons));self.assertEqual(d.HOSTS.read_bytes(),changed)
        self.assertEqual(d.APT_KEYRING.read_bytes(),before);self.assertFalse((d.STATE/'history').exists())
    def test_hosts_change_is_reversed_when_later_plan_blocks_and_reason_is_retained(self):
        self.failed_repository_fixture()
        appended=self.hosts_original+b'127.0.0.1 panel.example.com\n';d.HOSTS.write_bytes(appended)
        reason='Review/remove AAAA until VPS IPv6 is validated'
        with self.assertRaises(d.RecoveryBlocked) as error:
            self.recover_fixture(planner=lambda:{'state':'blocked','reasons':[reason,'SyntheticPassword123!']})
        self.assertEqual(error.exception.reasons,[reason]);self.assertEqual(d.HOSTS.read_bytes(),appended)
        record=d.read_json(next((d.STATE/'history').glob('*/recovery.json')))
        self.assertEqual(record['reasons'],[reason]);self.assertEqual(record['phase'],'fresh-installation-plan')
        self.assertNotIn('SyntheticPassword',json.dumps(record));self.assertFalse((d.CONFIG/'admin-password').exists())
        self.assertEqual(d.status()['state'],'failed')
    def test_hosts_backup_rejects_links_duplicates_and_oversized_members(self):
        self.failed_repository_fixture()
        for kind in ('symlink','duplicate','oversized'):
            with self.subTest(kind=kind):
                output=io.BytesIO()
                with tarfile.open(fileobj=output,mode='w:gz') as archive:
                    member=tarfile.TarInfo('etc/hosts')
                    if kind=='symlink':member.type=tarfile.SYMTYPE;member.linkname='/etc/shadow';archive.addfile(member)
                    elif kind=='duplicate':archive.addfile(member);archive.addfile(member)
                    else:
                        member.size=1048577;archive.addfile(member,io.BytesIO(b'x'*1048577))
                d.atomic(d.STATE/'configuration-before.tar.gz',output.getvalue())
                with self.assertRaises(d.RecoveryBlocked):self.recover_fixture()
                self.assertEqual(d.HOSTS.read_bytes(),self.hosts_original)
    def test_recovery_rejects_later_stage_without_mutations(self):
        self.failed_repository_fixture();path=next(d.NATIVE_BACKUPS.glob('*.log'))
        path.write_text(path.read_text()+'2026-10-25T08:34:00Z START Upgrade installed packages\n')
        before=d.APT_KEYRING.read_bytes()
        with self.assertRaises(ValueError):self.recover_fixture()
        self.assertEqual(self.recovery_calls,[]);self.assertEqual(d.APT_KEYRING.read_bytes(),before)
        self.assertEqual(d.status()['state'],'failed');self.assertFalse((d.STATE/'history').exists())
    def test_recovery_rejects_running_unit_and_installed_panel(self):
        self.failed_repository_fixture()
        with self.assertRaises(ValueError):self.recover_fixture(runner=lambda args:'active\n')
        d.ROOT.mkdir()
        with self.assertRaises(ValueError):self.recover_fixture()
        self.assertFalse((d.CONFIG/'admin-password').exists())
    def test_recovery_rejects_wrong_key_before_replacing_keyring(self):
        self.failed_repository_fixture();before=d.APT_KEYRING.read_bytes()
        def runner(args,**kwargs):
            result=self.recovery_runner(args,**kwargs)
            if args[0]=='/usr/bin/curl':Path(args[args.index('--output')+1]).write_text('tampered key')
            return result
        with self.assertRaises(ValueError):self.recover_fixture(runner=runner)
        self.assertEqual(d.APT_KEYRING.read_bytes(),before);self.assertEqual(d.status()['state'],'failed')
        self.assertFalse(any(a[0]=='/usr/bin/apt-get' for a in self.recovery_calls))
    def test_failed_authenticated_update_restores_key_and_never_prompts(self):
        self.failed_repository_fixture();before=d.APT_KEYRING.read_bytes()
        def runner(args,**kwargs):
            if args[0]=='/usr/bin/apt-get':raise RuntimeError('APT signature failure')
            return self.recovery_runner(args,**kwargs)
        with self.assertRaises(RuntimeError):self.recover_fixture(runner=runner,reader=lambda prompt:self.fail('must not ask for password'))
        self.assertEqual(d.APT_KEYRING.read_bytes(),before);self.assertEqual(d.status()['state'],'failed')
        self.assertFalse((d.CONFIG/'admin-password').exists());self.assertTrue((d.STATE/'working/evidence').exists())
    def test_failed_recovery_plan_restores_key_and_removes_new_password(self):
        self.failed_repository_fixture();before=d.APT_KEYRING.read_bytes()
        with self.assertRaises(ValueError):self.recover_fixture(planner=lambda:{'state':'blocked'})
        self.assertEqual(d.APT_KEYRING.read_bytes(),before);self.assertFalse((d.CONFIG/'admin-password').exists())
        self.assertEqual(d.status()['state'],'failed');self.assertTrue((d.STATE/'installation.log').exists())
    def test_recovery_archive_error_restores_all_current_evidence(self):
        self.failed_repository_fixture();before=d.APT_KEYRING.read_bytes();original_rename=Path.rename
        def rename(path,target):
            if path==d.STATE/'job.json':raise OSError('synthetic archive failure')
            return original_rename(path,target)
        with patch.object(Path,'rename',rename),self.assertRaises(OSError):self.recover_fixture()
        self.assertEqual(d.APT_KEYRING.read_bytes(),before);self.assertEqual(d.status()['state'],'failed')
        self.assertTrue((d.STATE/'working/evidence').exists());self.assertTrue((d.STATE/'configuration-before.tar.gz').exists())
        self.assertFalse((d.CONFIG/'admin-password').exists())
    def test_recovery_refuses_unrecognized_current_key_and_invalid_password(self):
        self.failed_repository_fixture();before=d.APT_KEYRING.read_bytes()
        d.APT_KEYRING.write_bytes(b'foreign keyring')
        with self.assertRaises(ValueError):self.recover_fixture()
        self.assertEqual(d.APT_KEYRING.read_bytes(),b'foreign keyring')
        d.APT_KEYRING.write_bytes(before)
        with self.assertRaises(ValueError):self.recover_fixture(reader=lambda prompt:'weak')
        self.assertEqual(d.APT_KEYRING.read_bytes(),before);self.assertEqual(d.status()['state'],'failed')
    def test_worker_success_validates_then_removes_local_password(self):
        job=self.queue();calls=[]
        def runner(args,timeout=60,log=None):
            calls.append(args)
            return json.dumps({'status':'verified'}) if '--refresh' in args else ''
        with patch.object(d,'backup_configuration') as backup,patch.object(d.socket,'create_connection',return_value=nullcontext()):
            result=d.worker(job['id'],runner,self.ready,lambda:self.source)
        self.assertEqual(result['state'],'succeeded');backup.assert_called_once()
        self.assertFalse((d.CONFIG/'admin-password').exists());self.assertIn('--installation-check',str(calls))
        with self.assertRaises(ValueError):d.worker(job['id'],runner,self.ready,lambda:self.source)
    def test_worker_failure_never_reports_success_and_cannot_reinstall(self):
        job=self.queue()
        def runner(args,timeout=60,log=None):raise RuntimeError('fixture failure')
        with patch.object(d,'backup_configuration'),self.assertRaises(RuntimeError):d.worker(job['id'],runner,self.ready,lambda:self.source)
        self.assertEqual(d.status()['state'],'failed');self.assertFalse((d.CONFIG/'admin-password').exists())
        with self.assertRaises(ValueError):self.queue()
    def test_credential_cleanup_failure_does_not_publish_success(self):
        job=self.queue();original_unlink=Path.unlink
        def unlink(path,*args,**kwargs):
            if path==d.CONFIG/'admin-password':raise OSError('fixture cleanup failure')
            return original_unlink(path,*args,**kwargs)
        def runner(args,timeout=60,log=None):return json.dumps({'status':'verified'}) if '--refresh' in args else ''
        with patch.object(d,'backup_configuration'),patch.object(d.socket,'create_connection',return_value=nullcontext()),patch.object(Path,'unlink',unlink),self.assertRaises(OSError):
            d.worker(job['id'],runner,self.ready,lambda:self.source)
        self.assertEqual(d.status()['state'],'failed');self.assertEqual(d.status()['phase'],'credential-cleanup')
    def test_normal_authenticated_ssh_console_can_query_status(self):
        previous=os.umask(0o077);os.umask(previous)
        try:
            with patch.dict(os.environ,{'SSH_CONNECTION':'192.0.2.1 1234 192.0.2.2 22'},clear=True),patch('sys.argv',['bootstrap','status']),patch('sys.stdout',io.StringIO()) as output:
                self.assertEqual(d.main(),0);self.assertEqual(json.loads(output.getvalue())['state'],'not-started')
        finally:os.umask(previous)
    def test_status_does_not_expose_secrets_and_identifies_interruption(self):
        job=self.queue();raw=d.read_json(d.STATE/'job.json');raw['password']='never-return';raw['started']=0;d.write_json(d.STATE/'job.json',raw)
        value=d.status();self.assertNotIn('never-return',json.dumps(value));self.assertEqual(value['state'],'queue-expired')
        raw['state']='running';d.write_json(d.STATE/'job.json',raw);self.assertEqual(d.status()['state'],'interrupted-review')
    def workflow(self, mode):
        content=(ROOT/'.github/workflows/vps-implantacao.yml').read_text()
        script=textwrap.dedent(content.split('        run: |\n',1)[1])
        folder=self.base/'mock-bin';folder.mkdir(exist_ok=True)
        ssh=folder/'ssh';ssh.write_text('''#!/bin/bash
case "${*: -1}" in
  *" start") printf '{"state":"queued"}\\n' ;;
  *" status") printf '{"state":"%s"}\\n' "$QA_WORKER_STATE" ;;
  *) exit 1 ;;
esac
''');ssh.chmod(0o755)
        sleeper=folder/'sleep';sleeper.write_text('#!/bin/bash\nexit 0\n');sleeper.chmod(0o755)
        key=self.base/'workflow-key'
        subprocess.run(['/usr/bin/ssh-keygen','-q','-t','ed25519','-N','','-f',str(key)],check=True)
        host='179.197.72.245 '+key.with_suffix('.pub').read_text()
        env={**os.environ,'PATH':str(folder)+':'+os.environ['PATH'],'RUNNER_TEMP':str(self.base),
             'VPS_HOST':'179.197.72.245','VPS_KNOWN_HOSTS':host,'VPS_SSH_KEY':key.read_text(),
             'DEPLOY_ACTION':'install','QA_WORKER_STATE':mode}
        result=subprocess.run(['/bin/bash','-c',script],env=env,capture_output=True,text=True,timeout=15)
        self.assertNotIn('BEGIN OPENSSH PRIVATE KEY',result.stdout+result.stderr)
        self.assertEqual(list(self.base.glob('hestia-deploy.*')),[])
        return result
    def test_workflow_waits_for_real_terminal_success_state(self):
        result=self.workflow('succeeded');self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('verificacoes locais concluidas',result.stdout)
    def test_workflow_treats_reported_worker_failure_as_failure(self):
        result=self.workflow('failed');self.assertNotEqual(result.returncode,0)
        self.assertIn('interrompida ou recusada',result.stderr)
        self.assertNotIn('temporariamente indisponivel',result.stdout)

if __name__=='__main__':unittest.main()
