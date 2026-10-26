"""Run actual tool controllers; rejected requests must never reach a privileged helper."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import test_business_controller as controller

ROOT=Path(__file__).resolve().parents[2]

class ToolControllerTests(controller.ControllerTests):
    tool='editor'
    def call(self,method='GET',post=None,changes=None,readonly=False):
        php=os.environ.get('PHP_BINARY') or shutil.which('php')
        self.assertTrue(php,'PHP required')
        session={'user':'admin','userContext':'admin','look':'','VERSION':'1.10.5','token':'TOKEN'}
        actual={'ROLE':'admin','SUSPENDED':'no','LOGIN_DISABLED':'no'}
        for key,value in (changes or {}).items():(actual if key in ('ROLE','SUSPENDED','LOGIN_DISABLED') else session)[key]=value
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'inc').mkdir()
            (root/'inc/main.php').write_text('<?php $_SESSION=json_decode(getenv("QA_SESSION"),true);$user_data=json_decode(getenv("QA_ACTUAL"),true);$read_only=getenv("QA_READONLY")==="yes";')
            code='$_SERVER["DOCUMENT_ROOT"]=getenv("QA_DOCROOT");$_SERVER["REQUEST_METHOD"]=getenv("QA_METHOD");$_POST=json_decode(getenv("QA_POST"),true);register_shutdown_function(function(){fwrite(STDERR,"HTTP=".(http_response_code()?:200));});include '+json.dumps(str(ROOT/f'web/professional/{self.tool}.php'))+';'
            env={**os.environ,'QA_DOCROOT':str(root),'QA_SESSION':json.dumps(session),'QA_ACTUAL':json.dumps(actual),
                 'QA_READONLY':'yes' if readonly else 'no','QA_METHOD':method,'QA_POST':json.dumps(post or {})}
            result=subprocess.run([php,'-n','-r',code],env=env,capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr);return int(result.stderr.split('HTTP=')[-1]),result.stdout
    def test_authorized_get_and_invalid_contexts(self):
        self.assertEqual(self.call()[0],200)
        for changes in ({'user':''},{'look':'clientone'},{'SUSPENDED':'yes'},{'LOGIN_DISABLED':'yes'},{'VERSION':'1.11.0'}):
            self.assertEqual(self.call(changes=changes)[0],403,changes)
        if self.tool=='editor':self.assertEqual(self.call(changes={'ROLE':'user','userContext':'user'})[0],200)
        else:self.assertEqual(self.call(changes={'ROLE':'user','userContext':'user'})[0],403)
    def test_direct_templates_and_clients_are_denied(self):
        php=os.environ.get('PHP_BINARY') or shutil.which('php')
        for file in ('tools-client.php',self.tool+'-view.php'):
            code='register_shutdown_function(function(){echo "HTTP=".(http_response_code()?:200);});include '+json.dumps(str(ROOT/'web/professional'/file))+';'
            result=subprocess.run([php,'-n','-r',code],capture_output=True,text=True,timeout=10)
            self.assertIn('HTTP=403',result.stdout)
    def test_foreign_scope_and_nonobject_protocol_are_denied(self):
        for value in ('[]','null','"shell"'):
            self.assertEqual(self.call('POST',{'token':'TOKEN','op':'read','request':value})[0],400)
        if self.tool=='editor':
            self.assertEqual(self.call('POST',{'token':'TOKEN','op':'read','request':'{"owner":"clienttwo"}'},
                                       changes={'ROLE':'user','userContext':'user'})[0],400)

class PlatformControllerTests(ToolControllerTests):
    tool='platform'

class FileManagerBoundaryTests(ToolControllerTests):
    def test_new_operations_reject_bad_csrf_readonly_and_foreign_scope(self):
        for op in ('files','download','rename','mkdir','upload-begin','upload-part','upload-commit','upload-cancel'):
            for token in ('','wrong',[]):
                with self.subTest(op=op,token=token):self.assertEqual(self.call('POST',{'token':token,'op':op,'request':'{}'})[0],403)
            self.assertEqual(self.call('POST',{'token':'TOKEN','op':op,'request':'{}'},readonly=True)[0],403)
            self.assertEqual(self.call('POST',{'token':'TOKEN','op':op,'request':'{"owner":"clienttwo"}'},changes={'ROLE':'user','userContext':'user'})[0],400)
