"""Native TOTP integration with the exact Composer-locked library, isolated from account data."""
import base64
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
PHP = os.environ.get('PHP_BINARY') or shutil.which('php')
LIBRARY = os.environ.get('TWOFA_LIBRARY_ROOT')

@unittest.skipUnless(PHP and LIBRARY, 'PHP_BINARY and Composer-locked TWOFA_LIBRARY_ROOT required')
class MfaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        shutil.copytree(ROOT / 'web/inc/2fa', self.root / 'web/inc/2fa')
        (self.root / 'professional').mkdir(); shutil.copyfile(ROOT / 'professional/qr.py', self.root / 'professional/qr.py')
        (self.root / 'web/inc/vendor').mkdir()
        library = str(Path(LIBRARY).resolve())
        self.assertNotIn("'", library)
        loader = "<?php spl_autoload_register(function($name) { $prefix='RobThree\\\\Auth\\\\'; if(str_starts_with($name,$prefix)) { $file='" + library + "/'.str_replace('\\\\','/',substr($name,strlen($prefix))).'.php'; if(is_file($file)) require $file; } });"
        (self.root / 'web/inc/vendor/autoload.php').write_text(loader)

    def tearDown(self): self.temp.cleanup()

    def test_offline_qr_and_totp_roundtrip(self):
        secret = subprocess.run([PHP, '-n', str(self.root / 'web/inc/2fa/secret.php')], capture_output=True, text=True, timeout=15)
        self.assertEqual(secret.returncode, 0, secret.stderr)
        key, qr = secret.stdout.split('-', 1)
        self.assertRegex(key, r'^[A-Z2-7]{32}$'); self.assertTrue(qr.startswith('data:image/svg+xml;base64,'))
        self.assertIn(b'<svg', base64.b64decode(qr.split(',', 1)[1]))
        code = "require '" + str(self.root / 'web/inc/vendor/autoload.php') + "'; require '" + str(self.root / 'web/inc/2fa/local-provider.php') + "'; $tfa=new RobThree\\Auth\\TwoFactorAuth(new HestiaLocalQrProvider(),'Hestia');echo $tfa->getCode(trim(fgets(STDIN)));"
        token = subprocess.run([PHP, '-n', '-r', code], input=key + '\n', capture_output=True, text=True, timeout=15)
        self.assertEqual(token.returncode, 0, token.stderr)
        check = [PHP, '-n', str(self.root / 'web/inc/2fa/check.php')]
        valid = subprocess.run(check, input=key + '\n' + token.stdout + '\n', text=True, capture_output=True, timeout=15)
        self.assertEqual(valid.returncode, 0); self.assertEqual(valid.stdout, 'ok')
        for bad in ('not-a-token', '1234567890123456', '<script>'):
            invalid = subprocess.run(check, input=key + '\n' + bad + '\n', text=True, capture_output=True, timeout=15)
            self.assertNotEqual(invalid.returncode, 0); self.assertNotIn(key, invalid.stdout + invalid.stderr)

    def test_http_arguments_and_missing_helper_cannot_leak_or_enable_mfa(self):
        check = [PHP, '-n', str(self.root / 'web/inc/2fa/check.php'), 'SYNTHETICSECRETHEADER', '123456']
        result = subprocess.run(check, input='', text=True, capture_output=True, timeout=15)
        self.assertNotEqual(result.returncode, 0); self.assertEqual(result.stdout, '')
        (self.root / 'professional/qr.py').unlink()
        result = subprocess.run([PHP, '-n', str(self.root / 'web/inc/2fa/secret.php')], text=True, capture_output=True, timeout=15)
        self.assertNotEqual(result.returncode, 0); self.assertNotRegex(result.stdout, r'[A-Z2-7]{32}')

if __name__ == '__main__': unittest.main()
