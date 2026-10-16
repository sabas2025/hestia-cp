"""Security regressions. Never execute an installer with --apply."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
COMMON = ROOT / "install/hst-common.sh"

def shell(code, args=(), **kw):
    return subprocess.run(['/bin/bash', '-c', 'source "$1"; shift; ' + code,
                           'test', str(COMMON), *args], capture_output=True, text=True, timeout=10, **kw)

class InstallTests(unittest.TestCase):
    def test_parser_preserves_shell_characters_as_data(self):
        value = "a'; printf INJECTED; #$(printf EXECUTED)* space"
        result = shell('hst_parse --email "$1"; printf "%s" "$email"', [value])
        self.assertNotEqual(result.returncode, 0)  # malformed email rejected, code never run
        self.assertNotIn('INJECTED', result.stdout)
        self.assertNotIn('EXECUTED', result.stdout)
        result = shell('hst_parse --password-file "$1"; printf "%s" "$HST_PASS_FILE"', [value])
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, value)

    def test_argument_validation(self):
        for args in [('--unknown','yes'), ('--port',), ('extra',), ('--apache','maybe'),
                     ('--password','SyntheticPassword123!'), ('--force',),
                     ('--port','0'), ('--port','65536'), ('--port','22x04'),
                     ('--hostname','a..example.org'), ('--hostname','127.0.0.1'),
                     ('--username','root'), ('--username','user;true'),
                     ('--multiphp','7.4'), ('--multiphp','8.4,'),
                     ('--interactive','never'), ('--password-fd','-1'),
                     ('--password-file','/a','--password-fd','3')]:
            with self.subTest(args=args):
                self.assertNotEqual(shell('hst_parse "$@"', args).returncode,0)

    def test_supported_options_and_leading_zero_port(self):
        result = shell('hst_parse --port 00883 --multiphp 8.3,8.4 --interactive no; printf "%s|%s|%s" "$port" "$multiphp" "$interactive"')
        self.assertEqual(result.stdout, '883|8.3,8.4|no')
        self.assertEqual(result.returncode,0)

    def test_distro_matrix_and_quoted_os_release(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'os-release'
            for distro,version,expected in [('debian','12',0),('debian','13',0),('ubuntu','22.04',0),('ubuntu','24.04',0),('ubuntu','26.04',0),('debian','24.04',1),('ubuntu','12',1),('ubuntu','22x04',1),('almalinux','9',1)]:
                with self.subTest(distro=distro,version=version):
                    p.write_text(f'ID="{distro}"\nVERSION_ID="{version}"\nVERSION_CODENAME="noble"\n')
                    self.assertEqual(shell('hst_os_detect "$1"',[str(p)]).returncode,expected)

    def test_os_release_never_sourced(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'os-release'; marker=Path(td)/'bad'
            p.write_text(f'ID=ubuntu\nVERSION_ID=24.04\nEVIL=$(touch {marker})\n')
            self.assertEqual(shell('hst_os_detect "$1"',[str(p)]).returncode,0)
            self.assertFalse(marker.exists())

    def test_fresh_os_blocks_existing_panel(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'etc').mkdir();(root/'etc/os-release').write_text('ID=ubuntu\nVERSION_ID=24.04\n')
            self.assertEqual(shell('hst_preflight "$1"',[td]).returncode,0)
            for name in ('usr/local/CyberCP','usr/local/hestia','www/server/panel','usr/local/cpanel'):
                p=root/name;p.mkdir(parents=True,exist_ok=True)
                self.assertNotEqual(shell('hst_preflight "$1"',[td]).returncode,0)
                p.rmdir()

    def test_existing_database_blocks_install(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'etc').mkdir();(root/'etc/os-release').write_text('ID=debian\nVERSION_ID=12\n')
            (root/'var/lib/mysql').mkdir(parents=True);(root/'var/lib/mysql/data').write_text('dummy')
            result=shell('hst_preflight "$1"',[td])
            self.assertNotEqual(result.returncode,0)
            self.assertIn('existing MySQL data',result.stdout)

    def test_noninteractive_missing_credentials_fails_without_reading(self):
        result=shell('hst_parse --interactive no; hst_credentials', input='')
        self.assertNotEqual(result.returncode,0)
        self.assertIn('requires username',result.stderr)

    def test_password_policy_handles_quotes_without_evaluation(self):
        for value in ("Test'Password1234", 'Test Password1234', 'Test$Pass*Word1234'):
            with self.subTest(value=value):self.assertEqual(shell('hst_password_valid "$1"',[value]).returncode,0)
        for value in ('weak', 'onlylowercase12345', 'NoDigitsAnywhereHere', 'Bad:Password12345', 'Has\nNewline12345'):
            with self.subTest(value=value):self.assertNotEqual(shell('hst_password_valid "$1"',[value]).returncode,0)

    def test_password_file_permissions_and_multiline(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'password';p.write_text("Test'Password1234\n");p.chmod(0o600)
            code='getent() { return 1; }; hst_parse --interactive no --username testuser --hostname hub.example.org --email a@example.org --password-file "$1"; hst_credentials; [[ "$vpass" == "Test\'Password1234" ]]'
            self.assertEqual(shell(code,[str(p)]).returncode,0)
            p.chmod(0o644);self.assertNotEqual(shell(code,[str(p)]).returncode,0)
            p.chmod(0o600);p.write_text('TestPassword1234\nsecondline');self.assertNotEqual(shell(code,[str(p)]).returncode,0)
            link=Path(td)/'link';link.symlink_to(p);self.assertNotEqual(shell(code,[str(link)]).returncode,0)

    def test_failed_apt_propagates_status_and_preserves_log(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'log';p.write_text('existing log\n')
            result=shell('LOG=$1; apt_get() { printf diagnostic >&2; return 42; }; hst_run "Install packages" apt_get',[str(p)])
            self.assertEqual(result.returncode,42)
            self.assertIn('existing log',p.read_text());self.assertIn('diagnostic',p.read_text());self.assertIn('status=42',p.read_text())

    def test_policy_restored_after_failure_and_interrupt(self):
        for status in (7,130,143):
            with self.subTest(status=status),tempfile.TemporaryDirectory() as td:
                root=Path(td);stage=root/'stage';stage.mkdir();policy=root/'policy';policy.write_text('ORIGINAL');policy.chmod(0o751)
                result=shell('HST_STAGE_DIR=$1; trap hst_cleanup EXIT; hst_policy_block "$2"; exit "$3"',[str(stage),str(policy),str(status)])
                self.assertEqual(result.returncode,status)
                self.assertEqual(policy.read_text(),'ORIGINAL');self.assertEqual(policy.stat().st_mode&0o777,0o751);self.assertFalse(stage.exists())

    def test_new_policy_removed_on_cleanup(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);stage=root/'stage';stage.mkdir();policy=root/'policy'
            self.assertEqual(shell('HST_STAGE_DIR=$1; trap hst_cleanup EXIT; hst_policy_block "$2"',[str(stage),str(policy)]).returncode,0)
            self.assertFalse(policy.exists());self.assertFalse(stage.exists())

    def test_policy_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);target=root/'target';target.write_text('KEEP');link=root/'link';link.symlink_to(target)
            self.assertNotEqual(shell('HST_STAGE_DIR=$1; hst_policy_block "$2"',[td,str(link)]).returncode,0)
            self.assertEqual(target.read_text(),'KEEP')

    def test_download_failure_and_https_enforcement(self):
        for url in ('http://example.org/file','https://example.org/file'):
            result=shell('curl() { return 22; }; hst_download "$1" "$2"',[url,'/nonexistent/not-written'])
            self.assertNotEqual(result.returncode,0)

    def test_hash_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'install').mkdir();(root/'install/assets.lock.tsv').write_text('x\t'+'0'*64+'\thttps://example.org/x\n')
            result=shell('HST_BUNDLE_ROOT=$1; hst_download() { printf unapproved > "$2"; }; hst_asset x "$1/download"',[td])
            self.assertNotEqual(result.returncode,0);self.assertIn('Integrity mismatch',result.stderr)

    def test_hash_match_succeeds(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'install').mkdir();digest=hashlib.sha256(b'approved').hexdigest();(root/'install/assets.lock.tsv').write_text(f'x\t{digest}\thttps://example.org/x\n')
            result=shell('HST_BUNDLE_ROOT=$1; hst_download() { printf approved > "$2"; }; hst_asset x "$1/download"',[td])
            self.assertEqual(result.returncode,0)

    def test_atomic_config_preserves_mode(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'config';p.write_text("Z='last'\nA='first'\n");p.chmod(0o640)
            self.assertEqual(shell('hst_publish_config "$1"',[str(p)]).returncode,0)
            self.assertEqual(p.read_text(),"A='first'\nZ='last'\n");self.assertEqual(p.stat().st_mode&0o777,0o640)

    def test_no_unsafe_old_install_constructs(self):
        for name in ('debian','ubuntu'):
            text=(ROOT/f'install/hst-install-{name}.sh').read_text()
            for bad in ('eval set','/tmp/hst.pem','/tmp/updconf','rclone.org/install.sh','restic self-update','Assert-Pubkey-Algo','killall -9 mysqld','apt-get -y upgrade >> $LOG &','read -p'):
                with self.subTest(name=name,bad=bad):self.assertNotIn(bad,text)
            self.assertIn('hst_prepare "$@"',text)
            self.assertIn('hst_run "Install selected packages"',text)
            self.assertLess(text.index('hst_run "Validate installation"'),text.index('Congratulations!'))
            self.assertIn('hst_restore_policy',text)
            self.assertIn('fpm_v="8.4"',text)

    def test_preflight_has_no_package_mutation(self):
        result=subprocess.run(['/bin/bash',str(ROOT/'install/hst-install.sh'),'--preflight'],capture_output=True,text=True,timeout=15)
        self.assertIn(result.returncode,(0,1))
        self.assertIn('inspection',result.stdout)
        self.assertNotIn('Install bootstrap',result.stdout)

if __name__=='__main__':unittest.main()
