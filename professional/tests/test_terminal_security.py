"""Terminal security regression tests with real PHP sessions and an isolated Node VM."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'professional'))
import terminal_guard as guard
import apply as overlay

class TerminalPHPTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.php=os.environ.get('PHP_BINARY') or shutil.which('php');self.assertTrue(self.php)
        (self.root/'data/sessions').mkdir(parents=True);(self.root/'conf').mkdir()
        (self.root/'conf/hestia.conf').write_text("VERSION='1.10.5'\nWEB_TERMINAL='true'\nROOT_USER='admin'\nPOLICY_SYSTEM_PROTECTED_ADMIN='yes'\n")
        self.user('admin','admin');self.user('clientone','user');self.user('otheradmin','admin')
        self.sid='SYNTHETICSESSION0123456789012345'
        self.session={'user':'admin','look':'','userContext':'admin','LAST_ACTIVITY':int(time.time()),
                      'INACTIVE_SESSION_TIMEOUT':'60','user_combined_ip':'203.0.113.10'}
    def user(self,name,role,**changes):
        folder=self.root/'data/users'/name;folder.mkdir(parents=True,exist_ok=True)
        data={'ROLE':role,'SUSPENDED':'no','LOGIN_DISABLED':'no','SHELL':'bash',**changes}
        (folder/'user.conf').write_text(''.join(f"{k}='{v}'\n" for k,v in data.items()))
    def call(self,session=None,payload=None,argv=False):
        env={**os.environ,'HESTIA':str(self.root),'QA_SESSION':json.dumps(session or self.session)}
        code="session_name('HESTIASID');session_save_path(getenv('HESTIA').'/data/sessions');session_id('"+self.sid+"');session_start();$_SESSION=json_decode(getenv('QA_SESSION'),true);session_write_close();"
        write=subprocess.run([self.php,'-n','-r',code],env=env,capture_output=True,text=True,timeout=10)
        self.assertEqual(write.returncode,0,write.stderr)
        before=(self.root/'data/sessions'/('sess_'+self.sid)).read_bytes()
        args=[self.php,'-n',str(ROOT/'professional/terminal-auth.php')]+([self.sid] if argv else [])
        result=subprocess.run(args,input=json.dumps(payload or {'session_id':self.sid,'remote_ip':'203.0.113.10'}),
                              env=env,capture_output=True,text=True,timeout=10)
        self.assertNotIn(self.sid,result.stdout+result.stderr)
        self.assertEqual((self.root/'data/sessions'/('sess_'+self.sid)).read_bytes(),before)
        return result.returncode,json.loads(result.stdout)
    def test_valid_session_uses_stdin_without_modifying_session(self):
        code,data=self.call();self.assertEqual(code,0);self.assertEqual(data,{'ok':True,'user':'admin','look':''})
    def test_argv_credentials_and_invalid_identifiers_are_refused(self):
        self.assertNotEqual(self.call(argv=True)[0],0)
        for sid in ('../secret','bad\nsession','a'*129):
            self.assertFalse(self.call(payload={'session_id':sid,'remote_ip':'203.0.113.10'})[1]['ok'])
    def test_suspension_login_disable_shell_and_role_revocation_are_live(self):
        for changes in ({'SUSPENDED':'yes'},{'LOGIN_DISABLED':'yes'},{'SHELL':'nologin'},{'ROLE':'user'}):
            with self.subTest(changes=changes):
                self.user('admin','admin',**changes);self.assertFalse(self.call()[1]['ok'])
    def test_expired_future_missing_context_and_changed_ip_are_refused(self):
        for changes in ({'LAST_ACTIVITY':int(time.time())-7200},{'LAST_ACTIVITY':int(time.time())+3600},
                        {'userContext':''},{'INACTIVE_SESSION_TIMEOUT':0},{'user_combined_ip':'203.0.113.11'}):
            self.assertFalse(self.call(session={**self.session,**changes})[1]['ok'])
    def test_impersonation_requires_live_admin_and_protected_target_is_refused(self):
        user_session={**self.session,'user':'clientone','userContext':'user','look':'admin'}
        self.assertFalse(self.call(session=user_session)[1]['ok'])
        admin_session={**self.session,'user':'otheradmin','look':'admin'}
        self.assertFalse(self.call(session=admin_session)[1]['ok'])
        self.assertTrue(self.call(session={**self.session,'look':'clientone'})[1]['ok'])
        self.user('clientone','user',SUSPENDED='yes')
        self.assertFalse(self.call(session={**self.session,'look':'clientone'})[1]['ok'])

class TerminalNodeTests(unittest.TestCase):
    def test_handshake_secrets_groups_periodic_revocation_and_limits(self):
        node=shutil.which('node');self.assertTrue(node)
        script=r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert');
let source=fs.readFileSync(process.argv[1],'utf8').replace(/^import .*;\n/gm,'');
function fixture(responses=[{ok:true,user:'clientone',look:''}]){
 const state={logs:[],auth:[],groups:null,timer:null,killed:false,spawned:0};
 class WSS{constructor(options){state.options=options;this.clients=new Set();state.wss=this;}on(name,fn){state.connection=fn;}}
 const pty={pid:123,on(){},write(){},kill(){state.killed=true;}};
 const sandbox={Buffer,console:{log:(...v)=>state.logs.push(v.join(' ')),error:(...v)=>state.logs.push(v.join(' '))},
  process:{env:{HESTIA:'/reviewed/hestia'},getuid:()=>0,setgroups:v=>{state.groups=v;}},
  execFileSync:(file,args,options)=>{
   if(file==='/bin/hostname')return 'panel.example.invalid';
   if(file.endsWith('v-list-sys-ips'))return '{}';
   if(file.endsWith('v-list-sys-config'))return JSON.stringify({config:{BACKEND_PORT:'8083',WEB_TERMINAL_PORT:'8085'}});
   state.auth.push({args,options});const next=responses.shift()||{ok:false};if(next instanceof Error)throw next;return JSON.stringify(next);
  },
  readFileSync:()=> 'clientone:x:1001:1001::/home/clientone:/bin/bash\n',
  spawn:()=>{state.spawned++;return pty;},WebSocketServer:WSS,
  setInterval:fn=>{state.timer=fn;return 42;},clearInterval:()=>{state.timer=null;},};
 vm.runInNewContext(source,sandbox);return state;
}
for(const name of ['constructor','__proto__','toString']){
 const state=fixture();let result;
 state.options.verifyClient({origin:'https://panel.example.invalid:8083',req:{headers:{cookie:name+'=x; HESTIASID=SYNTHETICSESSION0123456789'}}},(...args)=>result=args);
 assert.strictEqual(result[0],true);assert.strictEqual(state.options.host,'127.0.0.1');assert.strictEqual(state.options.maxPayload,65536);
 assert.strictEqual(JSON.stringify(state.groups),'[]');
}
for(const headers of [{cookie:'HESTIASID=a; HESTIASID=b'}, {cookie:'HESTIASID=bad/value'}, {cookie:'constructor=x'}]){
 const state=fixture();let result;state.options.verifyClient({origin:'https://panel.example.invalid:8083',req:{headers}},(...args)=>result=args);
 assert.strictEqual(result[0],false);assert.strictEqual(result[1],401);
}
const sid='SYNTHETICSESSION0123456789';const state=fixture();const events={};let closed;
const ws={readyState:1,bufferedAmount:0,on:(name,fn)=>events[name]=fn,send(){},close:(code,reason)=>{closed={code,reason};if(events.close)events.close();}};
state.connection(ws,{headers:{cookie:'HESTIASID='+sid,'x-real-ip':'203.0.113.10'},socket:{remoteAddress:'127.0.0.1'}});
assert.strictEqual(state.spawned,1);assert.strictEqual(state.auth.length,1);
assert(!JSON.stringify(state.auth[0].args).includes(sid));assert(JSON.parse(state.auth[0].options.input).session_id===sid);
assert(!state.logs.join('\n').includes(sid));assert.strictEqual(state.auth[0].options.timeout,2000);
state.timer();assert.strictEqual(closed.code,1000);assert.strictEqual(state.killed,true);
const failed=fixture([new Error('synthetic error containing '+sid)]);
failed.connection(ws,{headers:{cookie:'HESTIASID='+sid},socket:{remoteAddress:'203.0.113.10'}});
assert(!failed.logs.join('\n').includes(sid));assert.strictEqual(failed.spawned,0);
console.log('isolated terminal security assertions passed');
'''
        result=subprocess.run([node,'-e',script,str(ROOT/'professional/terminal-runtime.js')],capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
    def test_package_sources_match_deployed_runtime_assets(self):
        for name,(asset,_,_) in guard.FILES.items():
            self.assertEqual((ROOT/'src/deb/web-terminal'/name).read_bytes(),(ROOT/'professional'/asset).read_bytes())

class TerminalPatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)/'hestia'
        self.source=Path(self.tmp.name)/'source';(self.source/'professional').mkdir(parents=True)
        (self.root/'web-terminal').mkdir(parents=True)
        self.before={};mapping={}
        for name,(asset,_,mode) in guard.FILES.items():
            old=('synthetic original '+name).encode();self.before[name]=old
            path=self.root/'web-terminal'/name;path.write_bytes(old);path.chmod(0o755)
            shutil.copyfile(ROOT/'professional'/asset,self.source/'professional'/asset)
            mapping[name]=(asset,hashlib.sha256(old).hexdigest(),mode)
        self.mapping=patch.dict(guard.FILES,mapping);self.mapping.start();self.addCleanup(self.mapping.stop)
    def test_known_pair_patch_is_idempotent_and_never_claims_running_process_verified(self):
        result=guard.protect(self.root,self.source);self.assertTrue(result['changed']);self.assertFalse(result['running_process_verified'])
        self.assertFalse(guard.protect(self.root,self.source)['changed'])
        for name,(asset,_,_) in guard.FILES.items():self.assertEqual((self.root/'web-terminal'/name).read_bytes(),(self.source/'professional'/asset).read_bytes())
    def test_unknown_or_incomplete_package_is_preserved(self):
        path=self.root/'web-terminal/server.js';path.write_text('unknown local change')
        with self.assertRaises(ValueError):guard.protect(self.root,self.source)
        self.assertEqual(path.read_text(),'unknown local change');self.assertFalse((self.root/'data').exists())
        path.unlink()
        with self.assertRaises(ValueError):guard.protect(self.root,self.source)
    def test_partial_write_failure_restores_both_original_protocol_files(self):
        original=overlay.atomic_file;failed=False
        def fail(path,data,mode=0o644):
            nonlocal failed
            if path==self.root/'web-terminal/web-terminal-session-auth.php' and not failed:
                failed=True;raise OSError('synthetic write failure')
            return original(path,data,mode)
        with patch.object(overlay,'atomic_file',side_effect=fail),self.assertRaises(OSError):guard.protect(self.root,self.source)
        for name,body in self.before.items():self.assertEqual((self.root/'web-terminal'/name).read_bytes(),body)
