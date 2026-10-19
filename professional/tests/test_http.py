"""HTTP integration with an explicit test-only stand-in for Hestia authentication."""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time
import unittest
import urllib.request
import urllib.error
import urllib.parse

ROOT=Path(__file__).resolve().parents[2]
PHP=os.environ.get('PHP_BINARY') or shutil.which('php')

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None

@unittest.skipUnless(PHP,'PHP_BINARY or php required for HTTP integration tests')
class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary=tempfile.TemporaryDirectory();cls.root=Path(cls.temporary.name)
        shutil.copytree(ROOT/'web/professional',cls.root/'web/professional')
        (cls.root/'web/inc').mkdir()
        shutil.copytree(ROOT/'web/inc/2fa',cls.root/'web/inc/2fa')
        shutil.copytree(ROOT/'web/reset2fa',cls.root/'web/reset2fa')
        (cls.root/'web/inc/main.php').write_text('''<?php
if (!isset($_SERVER['HTTP_X_TEST_USER'])) { header('Location: /login/'); exit; }
$_SESSION=['user'=>$_SERVER['HTTP_X_TEST_USER'],'userContext'=>$_SERVER['HTTP_X_TEST_CONTEXT']??'user','look'=>$_SERVER['HTTP_X_TEST_LOOK']??'','ROOT_USER'=>'admin','VERSION'=>$_SERVER['HTTP_X_TEST_VERSION']??'1.10.5','APP_NAME'=>'Test','token'=>'TEST_SESSION_TOKEN'];
$read_only=($_SERVER['HTTP_X_TEST_READ_ONLY']??'')==='yes';
$user_data=['ROLE'=>$_SERVER['HTTP_X_TEST_ROLE']??'user','SUSPENDED'=>$_SERVER['HTTP_X_TEST_SUSPENDED']??'no'];
function get_user_data($name) { return [$name=>['ROLE'=>'user','SUSPENDED'=>'no','WEB_DOMAINS'=>'0','MAIL_DOMAINS'=>'0','DNS_DOMAINS'=>'0','DATABASES'=>'0','CRON_JOBS'=>'0','BACKUPS'=>'0']]; }
''')
        # The self-service HTTP tests verify routing/auth/CSRF. The root operation is
        # explicitly replaced in this temporary fixture; real factor checks are in test_corrections.
        trace=str(cls.root/'mfa-call.json')
        (cls.root/'web/professional/mfa-client.php').write_text('''<?php
if (!defined('HST_PRO_MFA')) { http_response_code(403); exit; }
function pro_mfa_call($user,$action,$request) {
file_put_contents('''+json.dumps(trace)+''',json_encode(['user'=>$user,'action'=>$action,'binding'=>$request['binding']]));
return ['state'=>'fixture-only']; }
''')
        (cls.root/'data/professional').mkdir(parents=True)
        (cls.root/'data/professional/health.json').write_text(json.dumps({'status':'ok','generated_at':'2099-01-01T00:00:00Z','private':'SERVER_ONLY'}))
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        cls.base=f'http://127.0.0.1:{port}'
        cls.process=subprocess.Popen([PHP,'-n','-S',f'127.0.0.1:{port}','-t',str(cls.root/'web')],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        for _ in range(50):
            try:
                with socket.create_connection(('127.0.0.1',port),timeout=.1):break
            except OSError:time.sleep(.05)
        else:raise RuntimeError('PHP test server did not start')
    @classmethod
    def tearDownClass(cls):
        cls.process.terminate();cls.process.wait(timeout=5);cls.temporary.cleanup()
    def request(self,path='/professional/',headers=None,method='GET',data=None):
        body=urllib.parse.urlencode(data).encode() if data is not None else None
        request=urllib.request.Request(self.base+path,headers=headers or {},method=method,data=body)
        try:response=urllib.request.build_opener(NoRedirect).open(request,timeout=10)
        except urllib.error.HTTPError as error:response=error
        return response.status,response.headers,response.read().decode()
    def user(self,**extra):return {'X-Test-User':'clientone',**extra}
    def test_anonymous_redirected(self):
        status,headers,body=self.request();self.assertEqual(status,302);self.assertEqual(headers['Location'],'/login/')
    def test_authenticated_page_security_headers(self):
        status,headers,body=self.request(headers=self.user())
        self.assertEqual(status,200);self.assertIn('Visão geral',body);self.assertIn('no-store',headers['Cache-Control']);self.assertIn("frame-ancestors 'none'",headers['Content-Security-Policy'])
    def test_query_cannot_change_user_scope(self):
        status,headers,body=self.request('/professional/?format=json&user=admin',self.user())
        self.assertEqual(status,200);data=json.loads(body);self.assertEqual(data['identity']['owner'],'clientone');self.assertIsNone(data['health']);self.assertNotIn('SERVER_ONLY',body)
    def test_forged_admin_rejected(self):
        status,headers,body=self.request(headers=self.user(**{'X-Test-Context':'admin','X-Test-Role':'user'}));self.assertEqual(status,403)
    def test_suspended_rejected(self):
        self.assertEqual(self.request(headers=self.user(**{'X-Test-Suspended':'yes'}))[0],403)
    def test_post_rejected_without_side_effects(self):
        status,headers,body=self.request(headers=self.user(),method='POST');self.assertEqual(status,405);self.assertEqual(headers['Allow'],'GET')
    def test_mfa_helpers_are_not_http_oracles(self):
        for name in ('secret.php', 'check.php', 'local-provider.php'):
            with self.subTest(name=name):
                status, headers, body = self.request('/inc/2fa/' + name + '?secret=SYNTHETIC&token=123456')
                self.assertEqual(status, 403); self.assertEqual(body, '')
    def test_unreviewed_upgrade_is_explicitly_unavailable(self):
        self.assertEqual(self.request(headers=self.user(**{'X-Test-Version':'1.11.0'}))[0],503)
    def test_admin_snapshot_and_direct_template_guard(self):
        status,headers,body=self.request('/professional/?format=json',{'X-Test-User':'admin','X-Test-Context':'admin','X-Test-Role':'admin'})
        self.assertEqual(status,200);self.assertIn('SERVER_ONLY',body)
        self.assertEqual(self.request('/professional/view.php')[0],403)
    def test_mfa_self_service_auth_csrf_and_readonly(self):
        self.assertEqual(self.request('/professional/twofactor.php')[0],302)
        self.assertEqual(self.request('/professional/twofactor.php',self.user())[0],200)
        for data in ({'action':'prepare'},{'action':'prepare','token':'wrong'}):
            self.assertEqual(self.request('/professional/twofactor.php',self.user(),'POST',data)[0],403)
        self.assertEqual(self.request('/professional/twofactor.php',self.user(**{'X-Test-Read-Only':'yes'}),'POST',{'token':'TEST_SESSION_TOKEN','action':'prepare'})[0],403)
        self.assertEqual(self.request('/professional/mfa-client.php')[0],403)
        self.assertEqual(self.request('/professional/twofactor-view.php')[0],403)
    def test_mfa_uses_only_session_owner_and_refuses_impersonation(self):
        status,headers,body=self.request('/professional/twofactor.php?user=admin',self.user(),'POST',
                    {'token':'TEST_SESSION_TOKEN','action':'prepare','user':'admin','password':'synthetic'})
        self.assertEqual(status,200);self.assertIn('no-store',headers['Cache-Control'])
        trace=json.loads((self.root/'mfa-call.json').read_text())
        self.assertEqual(trace['user'],'clientone');self.assertNotIn('password',trace)
        status,_,_=self.request('/professional/twofactor.php',{'X-Test-User':'admin','X-Test-Context':'admin','X-Test-Role':'admin','X-Test-Look':'clientone'})
        self.assertEqual(status,403)
    def test_legacy_recovery_cannot_disable_factor(self):
        status,headers,body=self.request('/reset2fa/',self.user(),'POST',{'user':'clientone','twofa':'SYNTHETIC_SEED'})
        self.assertEqual(status,302);self.assertEqual(headers['Location'],'/login/')

if __name__=='__main__':unittest.main()
