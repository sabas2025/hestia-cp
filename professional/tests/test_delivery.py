"""Production permission compatibility, editor isolation and administrative queue boundaries."""
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'professional'))
import business as b
import editor as e
import control_plane as c
import health
from mfa import root_json

def mapped_ids():
    try:
        mappings=[tuple(map(int,line.split())) for line in Path('/proc/self/uid_map').read_text().splitlines()]
        return any(start<=1002<start+count for start,_,count in mappings)
    except OSError:return True

USER_IDS_AVAILABLE=mapped_ids()

class DeliveryFixture(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name);self.root=self.base/'hestia';self.fs=self.base/'fs';self.home=self.base/'home'
        (self.root/'conf').mkdir(parents=True)
        (self.root/'conf/hestia.conf').write_text("VERSION='1.10.5'\nROOT_USER='admin'\nWEB_SYSTEM='apache2'\nPROXY_SYSTEM='nginx'\n")
        (self.root/'conf/hestia.conf').chmod(0o660)
        for owner,role,uid in [('admin','admin',1000),('clientone','user',1001),('clienttwo','user',1002)]:
            p=self.root/'data/users'/owner;p.mkdir(parents=True);p.chmod(0o770)
            (p/'user.conf').write_text(f"ROLE='{role}'\nSUSPENDED='no'\nLOGIN_DISABLED='no'\nTWOFA='SYNTHETICSEED'\n")
            (p/'user.conf').chmod(0o660)
            (p/'web.conf').write_text("DOMAIN='example.com' SUSPENDED='no'\n");(p/'web.conf').chmod(0o660)
            web=self.home/owner/'web/example.com/public_html';web.mkdir(parents=True)
            if USER_IDS_AVAILABLE:os.chown(web,uid,uid)
        self.web=self.home/'clientone/web/example.com/public_html'
        self.file=self.web/'index.txt';self.file.write_text('original source')
        if USER_IDS_AVAILABLE:os.chown(self.file,1001,1001)
        self.lookup=lambda owner:types.SimpleNamespace(pw_uid={'admin':1000,'clientone':1001,'clienttwo':1002}[owner],pw_gid={'admin':1000,'clientone':1001,'clienttwo':1002}[owner])
    def read(self,actor='clientone',owner='clientone',path='index.txt'):
        return e.read(self.root,actor,owner,'example.com',path,self.home,self.lookup)
    def save(self,content='changed source',expected=None,path='index.txt'):
        return e.save(self.root,'clientone','clientone','example.com',path,content,expected or self.read()['sha256'],self.home,self.lookup)

class NativePermissionsTests(DeliveryFixture):
    def test_native_660_files_and_770_root_group_directories_work(self):
        self.assertEqual(b.account(self.root,'admin')['ROLE'],'admin')
        self.assertEqual(b.record(self.root,'clientone','web','example.com')['DOMAIN'],'example.com')
    @unittest.skipUnless(USER_IDS_AVAILABLE,'Requires mapped Linux account IDs; mandatory CI runs as native root')
    def test_group_write_for_nonroot_group_and_other_write_still_rejected(self):
        p=self.root/'data/users/clientone/user.conf';os.chown(p,0,1001)
        with self.assertRaises(ValueError):b.account(self.root,'clientone')
        os.chown(p,0,0);p.chmod(0o662)
        with self.assertRaises(ValueError):b.account(self.root,'clientone')

@unittest.skipUnless(USER_IDS_AVAILABLE,'Requires mapped Linux account IDs; mandatory CI runs as native root')
class EditorTests(DeliveryFixture):
    def test_read_is_account_scoped_and_root_owned_files_are_not_writable(self):
        self.assertEqual(self.read()['content'],'original source')
        with self.assertRaises(ValueError):self.read(actor='clienttwo')
        self.assertEqual(self.read(actor='admin')['content'],'original source')
        os.chown(self.file,0,0)
        with self.assertRaises(ValueError):self.read()
    def test_paths_links_hardlinks_and_binary_files_are_rejected(self):
        for path in ('../user.conf','/etc/shadow','a/../../secret','.env','name\n.php'):
            with self.subTest(path=path),self.assertRaises(ValueError):self.read(path=path)
        (self.web/'link.txt').symlink_to(self.file)
        with self.assertRaises(OSError):self.read(path='link.txt')
        os.link(self.file,self.web/'hard.txt')
        with self.assertRaises(ValueError):self.read()
        (self.web/'hard.txt').unlink();self.file.write_bytes(b'binary\0payload')
        with self.assertRaises(ValueError):self.read()
    def test_directory_symlink_cannot_escape_workspace(self):
        (self.web/'escape').symlink_to(self.base,target_is_directory=True)
        with self.assertRaises(OSError):e.browse(self.root,'clientone','clientone','example.com','escape',self.home,self.lookup)
    def test_save_preserves_owner_mode_and_creates_private_revision(self):
        self.file.chmod(0o640);result=self.save()
        self.assertEqual(self.file.read_text(),'changed source');self.assertEqual(self.file.stat().st_uid,1001)
        self.assertEqual(self.file.stat().st_mode&0o777,0o640)
        revision=self.root/'data/professional-editor/revisions'/(result['revision']+'.json')
        self.assertEqual(revision.stat().st_mode&0o777,0o600)
        summary=e.history(self.root,'clientone','clientone')
        self.assertNotIn('original source',json.dumps(summary));self.assertNotIn('previous',json.dumps(summary))
    def test_concurrent_change_is_preserved_and_restore_is_hash_guarded(self):
        before=self.read()['sha256'];self.file.write_text('external edit')
        with self.assertRaises(ValueError):self.save(expected=before)
        self.assertEqual(self.file.read_text(),'external edit')
        result=self.save();self.file.write_text('second external edit')
        with self.assertRaises(ValueError):e.restore(self.root,'clientone',result['revision'],self.home,self.lookup)
        self.assertEqual(self.file.read_text(),'second external edit')
    def test_revision_restores_original_and_rejects_foreign_owner(self):
        result=self.save()
        with self.assertRaises(ValueError):e.restore(self.root,'clienttwo',result['revision'],self.home,self.lookup)
        e.restore(self.root,'clientone',result['revision'],self.home,self.lookup)
        self.assertEqual(self.file.read_text(),'original source')
    def test_new_file_never_overwrites_existing_file(self):
        with self.assertRaises(ValueError):self.save(expected='absent')
        self.save('new file',expected='absent',path='new.txt')
        self.assertEqual((self.web/'new.txt').read_text(),'new file')
    def test_invalid_json_and_php_fail_before_replacement(self):
        with self.assertRaises(ValueError):self.save('{broken',expected='absent',path='new.json')
        self.assertFalse((self.web/'new.json').exists())
        with patch.object(e.shutil,'which',return_value='/usr/bin/php'),tempfile.TemporaryDirectory() as td:
            calls=[]
            def fail(args,**kwargs):calls.append(args);return types.SimpleNamespace(returncode=1)
            with self.assertRaises(ValueError):e.validate_text(Path(td),Path('app.php'),b'<?php invalid',fail)
            self.assertEqual(calls[0][1:3],['-n','-l'])
    def test_mutation_protocol_refuses_missing_factor_before_save(self):
        with patch('sys.argv',['editor','--actor','admin','--op','save']),patch('sys.stdin',io.StringIO('{}')),patch.object(e,'authorize'),patch.object(e,'account',return_value={'TWOFA':''}),patch.object(e,'save') as save:
            with self.assertRaises(ValueError):e.main()
            save.assert_not_called()

class ControlPlaneTests(DeliveryFixture):
    def test_nonadmins_cannot_inspect_or_change_docker(self):
        for method in ('summary','docker','projects','backups','jobs'):
            with self.subTest(method=method),self.assertRaises(ValueError):c.inventory(self.root,self.fs,'clientone',method,{})
        with self.assertRaises(ValueError):c.spec(self.root,self.fs,'clientone','docker-operation','clientone',{})
    def test_docker_targets_deletion_and_local_daemon_are_guarded(self):
        for target in ('--privileged','x; id','$(id)'):
            with self.subTest(target=target),self.assertRaises(ValueError):c.operation(self.root,self.fs,'admin','docker-operation','clientone',{'operation':'container-start','target':target,'confirmation':''})
        with self.assertRaises(ValueError):c.operation(self.root,self.fs,'admin','docker-operation','clientone',{'operation':'volume-remove','target':'important','confirmation':''})
        value=c.operation(self.root,self.fs,'admin','docker-operation','clientone',{'operation':'container-stop','target':'app-one','confirmation':''})
        self.assertEqual(value['command'][:2],['docker','--host=unix:///var/run/docker.sock'])
    def test_read_inventory_cannot_be_used_for_mutations(self):
        calls=[]
        with self.assertRaises(ValueError):c.inventory(self.root,self.fs,'admin','docker',{'operation':'volume-remove','target':'data'},lambda a:calls.append(a))
        self.assertEqual(calls,[])
    def test_business_plan_is_admin_only_and_does_not_offer_fake_rollback(self):
        params={'operation':'container-start','target':'app-one','confirmation':''}
        plan=b.create(self.root,self.fs,'admin','docker-operation','clientone',params)
        self.assertFalse(plan['reversible']);self.assertNotIn('password',json.dumps(plan))
        with self.assertRaises(ValueError):b.create(self.root,self.fs,'clientone','docker-operation','clientone',params)
    def queued(self):
        ident='a'*32;nonce='b'*32
        job={'id':ident,'nonce':nonce,'actor':'admin','owner':'clientone','action':'docker-operation',
             'params':{'operation':'container-start','target':'app-one','confirmation':''},
             'state':'queued','created':0,'expires':9999999999,'watch':{}}
        root_json(c.jobs_folder(self.root)/(ident+'.json'),job);return ident,nonce
    def test_worker_executes_once_and_keeps_commands_out_of_history(self):
        ident,nonce=self.queued();calls=[]
        result=c.worker(self.root,self.fs,ident,nonce,runner=lambda a:calls.append(a),integrity=lambda r:{'state':'verified'})
        self.assertEqual(result['state'],'succeeded');self.assertEqual(len(calls),1)
        self.assertNotIn('params',result);self.assertNotIn('nonce',result)
        with self.assertRaises(ValueError):c.worker(self.root,self.fs,ident,nonce,runner=lambda a:calls.append(a))
    def test_worker_refuses_stale_config_revoked_actor_and_expired_ticket(self):
        for failure in ('config','actor','expired'):
            with self.subTest(failure=failure):
                ident,nonce=self.queued();path=c.jobs_folder(self.root)/(ident+'.json');job=json.loads(path.read_text())
                actor=self.root/'data/users/admin/user.conf';old=actor.read_text()
                if failure=='actor':actor.write_text(old.replace("ROLE='admin'","ROLE='user'"))
                elif failure=='expired':job['expires']=0;root_json(path,job)
                else:job['watch']={str(self.file):'0'*64};root_json(path,job)
                calls=[]
                with self.assertRaises(ValueError):c.worker(self.root,self.fs,ident,nonce,runner=lambda a:calls.append(a),integrity=lambda r:{'state':'verified'})
                self.assertEqual(calls,[]);self.assertEqual(json.loads(path.read_text())['state'],'failed');actor.write_text(old)
    def test_worker_failure_never_reports_success(self):
        ident,nonce=self.queued()
        def fail(args):raise RuntimeError('synthetic failure')
        with self.assertRaises(RuntimeError):c.worker(self.root,self.fs,ident,nonce,runner=fail,integrity=lambda r:{'state':'verified'})
        self.assertEqual(json.loads((c.jobs_folder(self.root)/(ident+'.json')).read_text())['state'],'failed')

class BackupVisibilityTests(DeliveryFixture):
    def test_native_catalog_and_cloud_jobs_are_distinguished(self):
        archive=self.base/'backup';archive.mkdir();name='clientone.2026-10-25_19-55-05.tar';(archive/name).write_bytes(b'fixture only')
        conf=self.root/'conf/hestia.conf';conf.write_text(conf.read_text()+f"BACKUP='{archive}'\n")
        (self.root/'data/users/clientone/backup.conf').write_text(f"BACKUP='{name}' TYPE='local' MAIL='example.com'\n")
        native=health.native_backups(self.root)
        self.assertEqual(native['catalogued'],1);self.assertEqual(native['local_present'],1);self.assertFalse(native['restoration_tested'])
        (archive/name).unlink();self.assertEqual(health.native_backups(self.root)['local_missing'],1)
