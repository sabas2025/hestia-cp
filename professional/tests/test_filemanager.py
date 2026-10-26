"""Real filesystem transfers and isolation; no VPS, passwords or public uploads."""
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import time
import types
import unittest
from unittest.mock import patch
from test_delivery import DeliveryFixture,USER_IDS_AVAILABLE
import editor as e
import filemanager as fm

class FileManagerTests(DeliveryFixture):
    def setUp(self):
        super().setUp()
        # Native CI exercises uid 1001. The local single-ID namespace can still
        # exercise byte transfer and atomic publication with a workspace fixture.
        if not USER_IDS_AVAILABLE:
            self.uid=0
            original=e.workspace
            def local_workspace(root,owner,name,home=Path('/home'),lookup=None):
                e.authorize(root,owner,owner);e.record(root,owner,'web',name)
                return home/owner/'web'/name/'public_html',types.SimpleNamespace(pw_uid=0,pw_gid=0)
            self.mock=patch.object(e,'workspace',side_effect=local_workspace);self.mock.start();self.addCleanup(self.mock.stop)
        else:self.uid=1001
        self.args=(self.root,'clientone','clientone','example.com')
        self.kw={'home':self.home,'lookup':self.lookup}
    def owned(self,name,raw):
        p=self.web/name;p.write_bytes(raw)
        if USER_IDS_AVAILABLE:os.chown(p,self.uid,self.uid)
        return p
    def listing(self,folder='',offset=0):return fm.listing(*self.args,folder,offset,**self.kw)
    def begin(self,name='upload.bin',raw=b'\0binary\xff'):
        return fm.begin(*self.args,name,len(raw),hashlib.sha256(raw).hexdigest(),**self.kw)['upload']
    def fill(self,ident,raw):
        for off in range(0,len(raw),fm.CHUNK):fm.part(self.root,'clientone',ident,off,base64.b64encode(raw[off:off+fm.CHUNK]).decode())
    def commit(self,ident):return fm.commit(self.root,'clientone',ident,**self.kw)
    def test_binary_listing_download_and_safe_pagination(self):
        self.owned('image.png',b'\x89PNG\0\xff')
        for n in range(105):self.owned(f'doc{n:03}.txt',b'data')
        first=self.listing();second=self.listing(offset=100)
        self.assertEqual(first['total'],107);self.assertEqual(first['next'],100);self.assertIsNone(second['next'])
        self.assertEqual(len(first['entries']),100);self.assertEqual(len(second['entries']),7)
        item=next(x for x in second['entries'] if x['name']=='image.png')
        self.assertFalse(item['editable']);self.assertTrue(item['downloadable'])
        d=fm.download(*self.args,'image.png',item['etag'],0,**self.kw)
        self.assertEqual(base64.b64decode(d['data']),b'\x89PNG\0\xff');self.assertTrue(d['eof'])
    def test_download_is_consistent_across_chunks_and_rejects_changes(self):
        raw=b'ab'*(fm.CHUNK//2+5);p=self.owned('large.zip',raw)
        item=next(x for x in self.listing()['entries'] if x['name']=='large.zip')
        a=fm.download(*self.args,'large.zip',item['etag'],0,**self.kw)
        b=fm.download(*self.args,'large.zip',item['etag'],fm.CHUNK,**self.kw)
        self.assertEqual(base64.b64decode(a['data'])+base64.b64decode(b['data']),raw)
        p.write_bytes(b'changed')
        with self.assertRaises(ValueError):fm.download(*self.args,'large.zip',item['etag'],0,**self.kw)
    def test_foreign_accounts_and_suspended_accounts_are_refused(self):
        with self.assertRaises(ValueError):fm.listing(self.root,'clienttwo','clientone','example.com',**self.kw)
        (self.root/'data/users/clientone/user.conf').write_text("ROLE='user'\nSUSPENDED='yes'\n")
        with self.assertRaises(ValueError):self.listing()
    def test_traversal_dotfiles_symlinks_hardlinks_and_unsafe_parents(self):
        for name in ('../secret','/etc/shadow','.env','private/.git/config','a\\b','x\ny','.hestia-upload-test'):
            with self.subTest(name=name),self.assertRaises(ValueError):fm.begin(*self.args,name,0,hashlib.sha256(b'').hexdigest(),**self.kw)
        (self.web/'escape').symlink_to(self.base,target_is_directory=True)
        with self.assertRaises(OSError):self.listing('escape')
        (self.web/'link.bin').symlink_to(self.file)
        os.link(self.file,self.web/'hard.bin')
        self.assertFalse(any(x['name'] in ('link.bin','hard.bin','index.txt','escape') for x in self.listing()['entries']))
        with self.assertRaises((ValueError,OSError)):fm.download(*self.args,'link.bin','x',0,**self.kw)
        with self.assertRaises(ValueError):fm.download(*self.args,'hard.bin','x',0,**self.kw)
        self.web.chmod(0o777)
        with self.assertRaises(ValueError):self.listing()
    def test_root_or_foreign_owned_files_remain_unavailable(self):
        if not USER_IDS_AVAILABLE:self.skipTest('Native root CI verifies multiple Linux owners')
        os.chown(self.file,0,0)
        self.assertEqual(self.listing()['entries'],[])
        with self.assertRaises(ValueError):fm.download(*self.args,'index.txt','x',0,**self.kw)
    def test_atomic_rename_keeps_bytes_and_never_overwrites(self):
        item=self.listing()['entries'][0];self.owned('exists.txt',b'keep')
        with self.assertRaises(FileExistsError):fm.rename(*self.args,'index.txt','exists.txt',item['etag'],**self.kw)
        self.assertEqual((self.web/'exists.txt').read_bytes(),b'keep')
        with self.assertRaises(ValueError):fm.rename(*self.args,'index.txt','renamed.txt','wrong',**self.kw)
        result=fm.rename(*self.args,'index.txt','renamed.txt',item['etag'],**self.kw)
        self.assertEqual(result['state'],'renamed');self.assertFalse(self.file.exists());self.assertEqual((self.web/'renamed.txt').read_text(),'original source')
        self.assertEqual((self.web/'renamed.txt').stat().st_uid,self.uid)
    def test_rename_refuses_paths_hidden_targets_and_directory_sources(self):
        item=self.listing()['entries'][0]
        for new in ('../other','sub/file.txt','.env','/root/key'):
            with self.subTest(new=new),self.assertRaises(ValueError):fm.rename(*self.args,'index.txt',new,item['etag'],**self.kw)
        (self.web/'folder').mkdir()
        if USER_IDS_AVAILABLE:os.chown(self.web/'folder',self.uid,self.uid)
        with self.assertRaises(ValueError):fm.rename(*self.args,'folder','other','x',**self.kw)
    def test_mkdir_is_owned_by_account_and_no_overwrite(self):
        fm.mkdir(*self.args,'new folder',**self.kw)
        p=self.web/'new folder';self.assertTrue(p.is_dir());self.assertEqual(p.stat().st_uid,self.uid)
        with self.assertRaises(ValueError):fm.mkdir(*self.args,'new folder',**self.kw)
        self.assertEqual(len(list(p.iterdir())),0)
    def test_chunked_upload_checks_digest_preserves_owner_and_is_single_use(self):
        raw=b'\0\xff\x80'*(fm.CHUNK//2);ident=self.begin(raw=raw)
        self.assertFalse((self.web/'upload.bin').exists())
        self.fill(ident,raw);result=self.commit(ident)
        p=self.web/'upload.bin';self.assertEqual(p.read_bytes(),raw);self.assertEqual(p.stat().st_uid,self.uid);self.assertEqual(p.stat().st_mode&0o777,0o644)
        self.assertEqual(result['sha256'],hashlib.sha256(raw).hexdigest())
        self.assertFalse(list(self.web.glob('.hestia-upload-*')))
        with self.assertRaises((ValueError,FileNotFoundError)):self.commit(ident)
    def test_empty_upload_and_cancel(self):
        ident=self.begin('empty.txt',b'');self.commit(ident);self.assertEqual((self.web/'empty.txt').read_bytes(),b'')
        ident=self.begin('cancelled.bin');fm.cancel(self.root,'clientone',ident)
        self.assertFalse((self.web/'cancelled.bin').exists());self.assertFalse((fm.uploads(self.root)/(ident+'.bin')).exists())
    def test_chunk_order_bounds_integrity_and_incomplete_upload(self):
        raw=b'correct';ident=self.begin(raw=raw)
        with self.assertRaises(ValueError):self.commit(ident)
        for offset,data in ((1,b'a'),(0,b''),(0,b'x'*8)):
            with self.subTest(offset=offset,data=data),self.assertRaises(ValueError):fm.part(self.root,'clientone',ident,offset,base64.b64encode(data).decode())
        with self.assertRaises(ValueError):fm.part(self.root,'clientone',ident,0,'not base64!')
        self.fill(ident,b'wrong!!')
        with self.assertRaises(ValueError):self.commit(ident)
        self.assertFalse((self.web/'upload.bin').exists())
    def test_upload_actor_binding_expiry_and_replay(self):
        ident=self.begin(raw=b'one')
        for call in (lambda:fm.part(self.root,'clienttwo',ident,0,'b25l'),lambda:fm.commit(self.root,'clienttwo',ident,**self.kw),lambda:fm.cancel(self.root,'clienttwo',ident)):
            with self.assertRaises(ValueError):call()
        self.fill(ident,b'one')
        with self.assertRaises(ValueError):self.fill(ident,b'one')
        p=fm.uploads(self.root)/(ident+'.json');data=json.loads(p.read_text());data['expires']=time.time()-1;p.write_text(json.dumps(data))
        with self.assertRaises(ValueError):self.commit(ident)
        self.begin('another.bin');self.assertFalse(p.exists())
    def test_upload_collision_is_preserved_before_and_at_commit(self):
        with self.assertRaises(ValueError):self.begin('index.txt')
        ident=self.begin(raw=b'new');self.fill(ident,b'new');self.owned('upload.bin',b'keep')
        with self.assertRaises(FileExistsError):self.commit(ident)
        self.assertEqual((self.web/'upload.bin').read_bytes(),b'keep');self.assertFalse(list(self.web.glob('.hestia-upload-*')))
    def test_upload_caps_and_no_public_partial_file(self):
        for total in (-1,fm.MAX_FILE+1,True,'5'):
            with self.subTest(total=total),self.assertRaises(ValueError):fm.begin(*self.args,'a.bin',total,'a'*64,**self.kw)
        with patch.object(fm.shutil,'disk_usage',return_value=types.SimpleNamespace(free=1)):
            with self.assertRaises(ValueError):self.begin()
        self.begin('a.bin');self.begin('b.bin')
        with self.assertRaises(ValueError):self.begin('c.bin')
        self.assertEqual({p.name for p in self.web.iterdir()},{'index.txt'})
    def test_staging_symlink_and_changed_permissions_are_rejected(self):
        ident=self.begin(raw=b'a');p=fm.uploads(self.root)/(ident+'.bin');p.unlink();p.symlink_to(self.file)
        with self.assertRaises(OSError):self.fill(ident,b'a')
        p.unlink();p.write_bytes(b'');p.chmod(0o644)
        with self.assertRaises(ValueError):self.fill(ident,b'a')
        self.assertEqual(self.file.read_text(),'original source')
    def test_suspended_domain_blocks_final_publication(self):
        ident=self.begin(raw=b'x');self.fill(ident,b'x')
        (self.root/'data/users/clientone/web.conf').write_text("DOMAIN='example.com' SUSPENDED='yes'\n")
        with self.assertRaises(ValueError):self.commit(ident)
        self.assertFalse((self.web/'upload.bin').exists())
    def test_operations_require_factor_and_integrity_before_mutation(self):
        for op in ('rename','mkdir','upload-begin','upload-part','upload-commit'):
            with self.subTest(op=op),patch('sys.argv',['editor','--actor','admin','--op',op]),patch('sys.stdin',io.StringIO('{}')),patch.object(e,'authorize'),patch.object(e,'account',return_value={'TWOFA':''}),patch.object(fm,'commit') as mutate:
                with self.assertRaises(ValueError):e.main()
                mutate.assert_not_called()
    def test_administrator_can_disable_all_file_manager_operations(self):
        self.assertTrue(fm.enabled(self.root))
        folder=fm.private_directory(self.root/'data/professional-filemanager',0o700)
        fm.root_json(folder/'policy.json',{'schema':1,'enabled':False})
        self.assertFalse(fm.enabled(self.root))
        with patch('sys.argv',['editor','--actor','admin','--op','domains']),patch('sys.stdin',io.StringIO('{}')),patch.object(e,'authorize'),patch.object(fm,'enabled',return_value=False):
            with self.assertRaisesRegex(ValueError,'disabled'):e.main()
        fm.root_json(folder/'policy.json',{'schema':1,'enabled':'false'})
        with self.assertRaises(ValueError):fm.enabled(self.root)
    def test_step_up_precedes_begin_rename_and_mkdir_and_continuations_use_ticket(self):
        request={'owner':'clientone','domain':'example.com','path':'new.txt','name':'other.txt','etag':'a'*64,
                 'total':1,'sha256':'a'*64,'upload':'b'*32,'offset':0,'data':'eA==','password':'synthetic','code':'123456'}
        for op,method,reauth in [('rename','rename',True),('mkdir','mkdir',True),('upload-begin','begin',True),('upload-part','part',False),('upload-commit','commit',False)]:
            with self.subTest(op=op),patch('sys.argv',['editor','--actor','admin','--op',op]),patch('sys.stdin',io.StringIO(json.dumps(request))),patch('sys.stdout',io.StringIO()),patch.object(e,'authorize'),patch.object(e,'account',return_value={'TWOFA':'seed'}),patch.object(fm,'enabled',return_value=True),patch('apply.verify_deployment',return_value={'state':'verified'}) as integrity,patch.object(e,'reauthenticate') as factor,patch.object(fm,method,return_value={'state':'fixture'}) as action:
                e.main();integrity.assert_called_once();action.assert_called_once()
                self.assertEqual(factor.call_count,int(reauth))
                if reauth:self.assertEqual(factor.call_args.args[-1],{'password':'synthetic','code':'123456'})

if __name__=='__main__':unittest.main()
