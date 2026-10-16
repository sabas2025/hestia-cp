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
        (cls.root/'web/inc/main.php').write_text('''<?php
if (!isset($_SERVER['HTTP_X_TEST_USER'])) { header('Location: /login/'); exit; }
$_SESSION=['user'=>$_SERVER['HTTP_X_TEST_USER'],'userContext'=>$_SERVER['HTTP_X_TEST_CONTEXT']??'user','look'=>'','ROOT_USER'=>'admin','VERSION'=>$_SERVER['HTTP_X_TEST_VERSION']??'1.10.5','APP_NAME'=>'Test'];
$user_data=['ROLE'=>$_SERVER['HTTP_X_TEST_ROLE']??'user','SUSPENDED'=>$_SERVER['HTTP_X_TEST_SUSPENDED']??'no'];
function get_user_data($name) { return [$name=>['ROLE'=>'user','SUSPENDED'=>'no','WEB_DOMAINS'=>'0','MAIL_DOMAINS'=>'0','DNS_DOMAINS'=>'0','DATABASES'=>'0','CRON_JOBS'=>'0','BACKUPS'=>'0']]; }
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
    def request(self,path='/professional/',headers=None,method='GET'):
        request=urllib.request.Request(self.base+path,headers=headers or {},method=method)
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
    def test_unreviewed_upgrade_is_explicitly_unavailable(self):
        self.assertEqual(self.request(headers=self.user(**{'X-Test-Version':'1.11.0'}))[0],503)
    def test_admin_snapshot_and_direct_template_guard(self):
        status,headers,body=self.request('/professional/?format=json',{'X-Test-User':'admin','X-Test-Context':'admin','X-Test-Role':'admin'})
        self.assertEqual(status,200);self.assertIn('SERVER_ONLY',body)
        self.assertEqual(self.request('/professional/view.php')[0],403)

if __name__=='__main__':unittest.main()
