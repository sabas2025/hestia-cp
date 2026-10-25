"""Operation boundaries and failure recovery. Native daemons are mocked explicitly."""
from datetime import datetime, timedelta, timezone
import json
import io
import os
import subprocess
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import business as b
import assurance
import backup
import cloud_backup
import ssh_keys
from cache_pool_entry import install
from mfa import root_json

ROOT = Path(__file__).resolve().parents[2]
class BusinessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)/'hestia'; self.fs = Path(self.tmp.name)/'system'
        (self.root/'conf').mkdir(parents=True)
        (self.root/'conf/hestia.conf').write_text("VERSION='1.10.5'\nROOT_USER='admin'\nWEB_SYSTEM='apache2'\nPROXY_SYSTEM='nginx'\n")
        for user,role in [('admin','admin'),('clientone','user'),('clienttwo','user')]:
            path = self.root/'data/users'/user; path.mkdir(parents=True)
            (path/'user.conf').write_text(f"SUSPENDED='no'\nLOGIN_DISABLED='no'\nROLE='{role}'\nTWOFA='JBSWY3DPEHPK3PXP'\n")
        self.user = self.root/'data/users/clientone'
        (self.user/'dns').mkdir(); (self.user/'dns/example.com.conf').write_text("ID='1' TYPE='A' VALUE='192.0.2.1'\n")
        (self.user/'dns.conf').write_text("DOMAIN='example.com' TTL='3600' SUSPENDED='no'\n")
        (self.user/'mail.conf').write_text("DOMAIN='example.com' RATE_LIMIT='100'\n")
        (self.user/'web.conf').write_text("DOMAIN='example.com' PROXY='default' PROXY_EXT='jpg,css,woff2'\n")
        target = self.root/'data/templates/web/nginx'; target.mkdir(parents=True)
        for p in (ROOT/'professional/cache-templates').glob('*'):
            (target/p.name).write_bytes(p.read_bytes())
        root_json(self.root/'professional/business-access.json',{'schema':1,'grants':{'clientone':['dns-ttl','mail-rate','cache-profile']}})
    def plan(self,action='mail-rate',params=None,actor='admin',now=1000):
        return b.create(self.root,self.fs,actor,action,'clientone',params or {'domain':'example.com','value':200},now)
    def runner(self,args):
        if args[0].endswith('v-change-mail-domain-rate-limit'):
            value = '' if args[3]=='system' else args[3]
            (self.user/'mail.conf').write_text(f"DOMAIN='example.com' RATE_LIMIT='{value}'\n")
        if args[0].endswith('v-change-web-domain-proxy-tpl'):
            (self.user/'web.conf').write_text(f"DOMAIN='example.com' PROXY='{args[3]}' PROXY_EXT='{args[4]}'\n")
            if args[3]=='professional-safe': install(self.root,self.fs,'clientone','example.com')
        return ''
    def test_authorization_is_scoped_and_live(self):
        self.plan(actor='clientone')
        with self.assertRaises(ValueError): b.create(self.root,self.fs,'clienttwo','dns-ttl','clientone',{'domain':'example.com','value':600},1000)
        with self.assertRaises(ValueError): b.authorize(self.root,'clientone','ssh-policy','clientone')
        root_json(self.root/'professional/business-access.json',{'schema':1,'grants':{}})
        with self.assertRaises(ValueError): self.plan(actor='clientone')
    def test_foreign_domain_and_unknown_fields_refused(self):
        for params in ({'domain':'other.example','value':200},{'domain':'example.com','value':200,'command':'id'}):
            with self.assertRaises(ValueError): self.plan(params=params)
    def test_expired_plan_cannot_execute(self):
        p=self.plan(); calls=[]
        with self.assertRaises(ValueError): b.execute(self.root,self.fs,'admin',p['id'],runner=lambda a:calls.append(a),now=1601)
        self.assertEqual(calls,[])
    def test_snapshot_detects_dns_record_change(self):
        p=self.plan('dns-ttl',{'domain':'example.com','value':600})
        (self.user/'dns/example.com.conf').write_text('changed')
        with self.assertRaises(ValueError): b.execute(self.root,self.fs,'admin',p['id'],runner=self.runner,now=1001)
    def test_apply_rollback_and_replay(self):
        p=self.plan(); r=b.execute(self.root,self.fs,'admin',p['id'],runner=self.runner,now=1001)
        self.assertEqual(r['state'],'applied'); self.assertIn("RATE_LIMIT='200'",(self.user/'mail.conf').read_text())
        with self.assertRaises(ValueError): b.execute(self.root,self.fs,'admin',p['id'],runner=self.runner,now=1002)
        r=b.execute(self.root,self.fs,'admin',p['id'],True,self.runner,1002)
        self.assertEqual(r['state'],'rolled-back'); self.assertIn("RATE_LIMIT='100'",(self.user/'mail.conf').read_text())
    def test_rollback_refuses_external_change(self):
        p=self.plan();b.execute(self.root,self.fs,'admin',p['id'],runner=self.runner,now=1001)
        (self.user/'mail.conf').write_text("DOMAIN='example.com' RATE_LIMIT='999'\n")
        with self.assertRaises(ValueError): b.execute(self.root,self.fs,'admin',p['id'],True,self.runner,1002)
    def test_native_partial_failure_is_reversed(self):
        p=self.plan(); calls=[]
        def runner(args):
            calls.append(args); self.runner(args)
            if args[-1]=='200': raise RuntimeError('simulated service failure')
            return ''
        with self.assertRaises(RuntimeError): b.execute(self.root,self.fs,'admin',p['id'],runner=runner,now=1001)
        self.assertEqual(b.load(self.root,p['id'])['state'],'failed-restored')
        self.assertEqual(calls[-1][-1],'100')
    def test_failed_reverse_requires_manual_recovery(self):
        p=self.plan()
        def runner(args): raise RuntimeError('failure')
        with self.assertRaises(RuntimeError): b.execute(self.root,self.fs,'admin',p['id'],runner=runner,now=1001)
        self.assertEqual(b.load(self.root,p['id'])['state'],'recovery-required')
    def test_default_mail_rate_restores_system(self):
        (self.user/'mail.conf').write_text("DOMAIN='example.com' RATE_LIMIT=''\n")
        p=self.plan();self.assertEqual(b.load(self.root,p['id'])['spec']['reverse'][0][-1],'system')
    def test_cache_preserves_extensions_and_pool_lifecycle(self):
        p=self.plan('cache-profile',{'domain':'example.com','value':'professional-safe'})
        self.assertEqual(p['commands'][0][-2:],['jpg,css,woff2','no'])
        b.execute(self.root,self.fs,'admin',p['id'],runner=self.runner,now=1001)
        pool=Path(b.pool_spec(self.fs,'clientone','example.com')['path'])
        self.assertIn('keys_zone=hpro_example.com',pool.read_text())
        off=self.plan('cache-profile',{'domain':'example.com','value':'default'},now=1002)
        b.execute(self.root,self.fs,'admin',off['id'],runner=self.runner,now=1003); self.assertFalse(pool.exists())
        b.execute(self.root,self.fs,'admin',off['id'],True,self.runner,1004); self.assertTrue(pool.exists())
    def test_unknown_configuration_not_overwritten(self):
        path=Path(b.pool_spec(self.fs,'clientone','example.com')['path']);path.parent.mkdir(parents=True);path.write_text('custom zone')
        with self.assertRaises(ValueError): self.plan('cache-profile',{'domain':'example.com','value':'professional-safe'})
    def test_cache_excludes_personalized_requests(self):
        for suffix in ('tpl','stpl'):
            text=(ROOT/f'professional/cache-templates/professional-safe.{suffix}').read_text()
            for required in ('$http_authorization','$upstream_http_set_cookie','if ($http_cookie != "")','if ($args != "")','GET|HEAD','oauth','webhook','proxy_cache hpro_%domain%'):
                self.assertIn(required,text)
            self.assertNotIn('proxy_cache_valid 404',text)
    def test_resources_preserve_native_cpu_authority(self):
        with patch('business.pwd.getpwnam',return_value=types.SimpleNamespace(pw_uid=1001)):
            p=self.plan('resources',{'uid':1001,'memory_mb':1024,'tasks':512,'io_weight':100})
        body=p['files'][0]['body'];self.assertIn('MemoryMax=1024M',body)
        self.assertNotIn('CPUQuota',body);self.assertNotIn('MemoryHigh',body)
    def test_resources_refuse_uid_mismatch(self):
        with patch('business.pwd.getpwnam',return_value=types.SimpleNamespace(pw_uid=1002)),self.assertRaises(ValueError):
            self.plan('resources',{'uid':1001,'memory_mb':1024,'tasks':512,'io_weight':100})
    def test_suspended_and_disabled_actor_and_stale_core_refused(self):
        p=self.plan()
        path=self.root/'data/users/admin/user.conf';path.write_text("ROLE='admin'\nSUSPENDED='yes'\n")
        with self.assertRaises(ValueError): b.execute(self.root,self.fs,'admin',p['id'],runner=self.runner,now=1001)
        with self.assertRaises(ValueError): self.plan(actor='clienttwo')
        path.write_text("ROLE='admin'\nSUSPENDED='no'\nLOGIN_DISABLED='yes'\n")
        with self.assertRaises(ValueError): self.plan()
        path.write_text("ROLE='admin'\nSUSPENDED='no'\n")
        (self.root/'conf/hestia.conf').write_text("VERSION='1.11.0'\n")
        with self.assertRaises(ValueError): self.plan()
    def test_admin_can_manage_login_disabled_target(self):
        path=self.user/'user.conf';path.write_text(path.read_text().replace("LOGIN_DISABLED='no'","LOGIN_DISABLED='yes'"))
        self.plan()
        with self.assertRaises(ValueError): self.plan(actor='clientone')
    def test_symlinks_and_loose_parents_refused(self):
        p=self.user/'other';p.symlink_to(self.user/'mail.conf')
        with self.assertRaises(ValueError): b.regular(p)
        path=self.root/'loose';path.mkdir();path.chmod(0o777);(path/'config').write_text('data')
        with self.assertRaises(ValueError): b.regular(path/'config')
    def test_ssh_requires_reviewed_key_and_protects_admin(self):
        (self.fs/'etc/ssh').mkdir(parents=True);(self.fs/'etc/ssh/sshd_config').write_text('Include /etc/ssh/sshd_config.d/*.conf\n')
        with self.assertRaises(ValueError): self.plan('ssh-policy',{'value':'keys-only'})
        with self.assertRaises(ValueError): b.create(self.root,self.fs,'admin','ssh-policy','admin',{'value':'disabled'},1000)
    def test_ssh_effective_override_restores_files(self):
        d=self.fs/'etc/ssh';d.mkdir(parents=True);(d/'sshd_config').write_text('Include /etc/ssh/sshd_config.d/*.conf\n')
        (d/'hestia-keys').mkdir();(d/'hestia-keys/clientone').write_text('ssh-ed25519 SYNTHETIC\n')
        p=self.plan('ssh-policy',{'value':'sftp-only'})
        with self.assertRaises(ValueError): b.execute(self.root,self.fs,'admin',p['id'],runner=lambda args:'passwordauthentication yes\n',now=1001)
        self.assertEqual(b.load(self.root,p['id'])['state'],'failed-restored');self.assertFalse(Path(p['files'][0]['path']).exists())
    def test_queue_one_use_and_no_credentials_on_argv(self):
        p=self.plan();calls=[]
        result=b.enqueue(self.root,'admin',p['id'],runner=lambda a:calls.append(a),now=1001)
        self.assertEqual(result['state'],'queued');self.assertIn('--property=RuntimeMaxSec=600',calls[0]);self.assertNotIn('password',json.dumps(calls))
        with self.assertRaises(ValueError): b.enqueue(self.root,'admin',p['id'],runner=lambda a:'',now=1001)
        ticket=json.loads((b.folder(self.root)/'queue'/(p['id']+'.json')).read_text())
        b.work(self.root,self.fs,p['id'],ticket['nonce'],self.runner,lambda r:{'state':'verified'},1002)
        self.assertEqual(b.load(self.root,p['id'])['state'],'applied')
        with self.assertRaises(ValueError): b.work(self.root,self.fs,p['id'],ticket['nonce'],self.runner,lambda r:{'state':'verified'},1003)
    def test_queue_expiry_and_revocation_prevent_execution(self):
        p=self.plan();b.enqueue(self.root,'admin',p['id'],runner=lambda a:'',now=1001)
        ticket=json.loads((b.folder(self.root)/'queue'/(p['id']+'.json')).read_text())
        calls=[]
        with self.assertRaises(ValueError): b.work(self.root,self.fs,p['id'],ticket['nonce'],lambda a:calls.append(a),lambda r:{'state':'verified'},1100)
        self.assertEqual(calls,[]);self.assertEqual(b.history(self.root,'admin')['plans'][0]['job_state'],'job-failed')
    def test_queue_launch_failure_recorded(self):
        p=self.plan()
        def runner(args):raise RuntimeError('no systemd')
        with self.assertRaises(RuntimeError): b.enqueue(self.root,'admin',p['id'],runner=runner,now=1001)
        self.assertEqual(b.history(self.root,'admin')['plans'][0]['job_state'],'queue-failed')
    def test_queue_refuses_unverified_deployment(self):
        p=self.plan();b.enqueue(self.root,'admin',p['id'],runner=lambda a:'',now=1001)
        ticket=json.loads((b.folder(self.root)/'queue'/(p['id']+'.json')).read_text())
        with self.assertRaises(ValueError): b.work(self.root,self.fs,p['id'],ticket['nonce'],self.runner,lambda r:{'state':'review-required'},1002)
    def test_queue_rechecks_actor_after_submission(self):
        p=self.plan();b.enqueue(self.root,'admin',p['id'],runner=lambda a:'',now=1001)
        ticket=json.loads((b.folder(self.root)/'queue'/(p['id']+'.json')).read_text())
        path=self.root/'data/users/admin/user.conf';path.write_text("ROLE='user'\nSUSPENDED='no'\n")
        with self.assertRaises(ValueError):b.work(self.root,self.fs,p['id'],ticket['nonce'],self.runner,lambda r:{'state':'verified'},1002)
    def test_requeued_expired_ticket_invalidates_old_worker_nonce(self):
        p=self.plan();b.enqueue(self.root,'admin',p['id'],runner=lambda a:'',now=1001)
        first=json.loads((b.folder(self.root)/'queue'/(p['id']+'.json')).read_text())
        b.enqueue(self.root,'admin',p['id'],runner=lambda a:'',now=1062)
        second=json.loads((b.folder(self.root)/'queue'/(p['id']+'.json')).read_text())
        self.assertNotEqual(first['nonce'],second['nonce'])
        with self.assertRaises(ValueError):b.work(self.root,self.fs,p['id'],first['nonce'],self.runner,lambda r:{'state':'verified'},1063)
        b.work(self.root,self.fs,p['id'],second['nonce'],self.runner,lambda r:{'state':'verified'},1063)
    def test_cli_requires_real_fresh_totp_before_enqueue(self):
        import mfa
        p=self.plan();now=1800000000
        code=mfa.totp('JBSWY3DPEHPK3PXP',now//30)
        request={'id':p['id'],'password':'synthetic-password','code':code}
        def reauth(root,user,action,req):
            return mfa.operate(root,user,action,req,verifier=lambda u,pw:pw=='synthetic-password',now=now)
        argv=['business.py','--root',str(self.root),'--actor','admin','--op','apply']
        with patch('sys.argv',argv),patch('sys.stdin',io.StringIO(json.dumps(request))),patch('sys.stdout',io.StringIO()),patch('business.verify_deployment',return_value={'state':'verified'}),patch('business.reauthenticate',side_effect=reauth),patch('business.enqueue',return_value={'state':'queued'}) as enqueue:
            b.main();enqueue.assert_called_once()
        # The same TOTP cannot authorize another queue submission.
        with patch('sys.argv',argv),patch('sys.stdin',io.StringIO(json.dumps(request))),patch('business.verify_deployment',return_value={'state':'verified'}),patch('business.reauthenticate',side_effect=reauth),patch('business.enqueue') as enqueue:
            with self.assertRaises(ValueError):b.main()
            enqueue.assert_not_called()
    def test_empty_php_request_reaches_python_history_as_object(self):
        # Exercise the real client serializer and Python entry protocol together.
        php=os.environ.get('PHP_BINARY','php')
        file=str(ROOT/'web/professional/business-client.php')
        code='define("HST_PRO_BUSINESS",true);require '+json.dumps(file)+';echo pro_business_encode([]);'
        wire=subprocess.check_output([php,'-n','-r',code],text=True)
        self.assertIsInstance(json.loads(wire),dict)
        stdout=io.StringIO()
        with patch('sys.argv',['business.py','--root',str(self.root),'--actor','admin','--op','history']),patch('sys.stdin',io.StringIO(wire)),patch('sys.stdout',stdout):
            b.main()
        self.assertEqual(json.loads(stdout.getvalue()),{'plans':[]})
    def test_diagnosis_is_read_only_and_limited(self):
        calls=[]
        def runner(args,timeout):calls.append(args);return 0,'"v=spf1 -all"\n' if args[-2:] == ['example.com','TXT'] else ''
        result=assurance.diagnose(self.root,'clientone','example.com',runner)
        self.assertEqual(len(calls),12);self.assertTrue(result['observations']['spf_single_record']);self.assertFalse(result['dnssec_chain_validated'])
        with self.assertRaises(ValueError):assurance.diagnose(self.root,'clientone','foreign.example',runner)
    def test_cgroup_coverage_detects_php_outside_user_slice(self):
        proc=Path(self.tmp.name)/'proc';proc.mkdir()
        for pid,cgroup in [('1','/user.slice/user-1001.slice/session-1.scope'),('2','/system.slice/php8.4-fpm.service')]:
            p=proc/pid;p.mkdir();(p/'status').write_text('Uid:\t1001\t1001\t1001\t1001\n');(p/'cgroup').write_text('0::'+cgroup+'\n')
        with patch('assurance.pwd.getpwnam',return_value=types.SimpleNamespace(pw_uid=1001)):
            result=assurance.coverage('clientone',proc)
        self.assertEqual(result['outside_user_slice'],1);self.assertEqual(result['coverage'],'incomplete')
    def test_append_only_blocks_prune_in_both_backup_engines(self):
        calls=[]
        for module in (backup,cloud_backup):
            with self.assertRaises(ValueError):module.execute('retention','clientone',{'append_only':True},self.root,runner=lambda a,env=None:calls.append(a))
        self.assertEqual(calls,[])
    def test_public_key_lease_duplicate_and_newline_boundaries(self):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import Encoding,PublicFormat
        public=Ed25519PrivateKey.generate().public_key().public_bytes(Encoding.OpenSSH,PublicFormat.OpenSSH).decode()
        now=datetime(2026,10,25,tzinfo=timezone.utc)
        ident,line=ssh_keys.lease_line(public,(now+timedelta(hours=1)).isoformat(),['192.0.2.1/32'],now)
        self.assertIn('restrict,expiry-time=',line);self.assertIn('from="192.0.2.1/32"',line)
        with self.assertRaises(ValueError):ssh_keys.update(public+' permanent',ident,line)
        self.assertIn('oldkey\nrestrict',ssh_keys.update('oldkey',ident,line))
        self.assertEqual(ssh_keys.update(line,ident),'')
        with self.assertRaises(ValueError):ssh_keys.lease_line(public,(now+timedelta(days=60)).isoformat(),[],now)
    def test_custom_template_preflight_precedes_overlay_mutation(self):
        from test_operations import OperationsTests,apply_overlay
        target=Path(self.tmp.name)/'installed'; OperationsTests().fixture_hestia(target)
        p=target/'data/templates/web/nginx/professional-safe.tpl';p.parent.mkdir(parents=True);p.write_text('custom')
        with self.assertRaises(ValueError):apply_overlay.apply_files(target,ROOT)
        self.assertFalse((target/'web/professional').exists());self.assertFalse((target/'bin/v-professional-business').exists())

if __name__=='__main__':unittest.main()
