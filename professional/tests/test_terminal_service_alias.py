"""Run real service wrappers with an isolated systemctl, preserving error exits."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]

class TerminalAliasTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.base=Path(self.tmp.name)
        self.root=self.base/'hestia';self.bin=self.base/'bin';self.bin.mkdir();(self.root/'func').mkdir(parents=True);(self.root/'conf').mkdir()
        self.trace=self.base/'trace';self.trace.write_text('');self.calls=self.base/'calls';self.calls.write_text('')
        # Bootstrap/auth functions are explicit stand-ins; routing and result
        # handling come from the actual released service wrappers.
        (self.root/'func/main.sh').write_text('''source_conf() { :; }
check_args() { :; }
is_format_valid() { :; }
check_hestia_demo_mode() { :; }
multiphp_versions() { printf '8.3 8.4'; }
log_event() { :; }
check_result() { if [ "$1" -ne 0 ]; then printf '%s\\n' "$2"; exit "${3:-$1}"; fi; }
E_RESTART=20
OK=0
ARGUMENTS=''
''')
        self.bootstrap=self.base/'bootstrap';self.bootstrap.write_text(f'HESTIA={self.root}\nBIN={self.bin}\nDEBUG_MODE=false\n')
        for name,script in {
            'systemctl':'''#!/bin/sh
printf '%s\n' "$*" >> "$QA_TRACE"
case "$1" in reset-failed) exit 0 ;; *) exit "$QA_RESULT" ;; esac
''',
            'v-log-action':'''#!/bin/sh
printf '%s\n' "$*" >> "$QA_CALLS"
exit 0
''',
            'v-update-firewall':'#!/bin/sh\nprintf "firewall update\\n" >> "$QA_TRACE"\nexit "$QA_RESULT"\n',
            'v-stop-firewall':'#!/bin/sh\nprintf "firewall stop\\n" >> "$QA_TRACE"\nexit "$QA_RESULT"\n',
        }.items():p=self.bin/name;p.write_text(script);p.chmod(0o755)
        self.systemd=self.base/'systemd';self.systemd.mkdir()
    def call(self,operation,service='web-terminal',result=0,restart='yes'):
        script=(ROOT/'bin'/('v-'+operation+'-service')).read_text().replace('source /etc/hestiacp/hestia.conf','source '+str(self.bootstrap)).replace('/run/systemd/system',str(self.systemd))
        path=self.base/'script';path.write_text(script)
        self.trace.write_text('');self.calls.write_text('')
        env={**os.environ,'PATH':str(self.bin)+':/usr/bin:/bin','QA_TRACE':str(self.trace),'QA_CALLS':str(self.calls),'QA_RESULT':str(result)}
        args=['bash',str(path),service]+([restart] if operation=='restart' else [])
        completed=subprocess.run(args,env=env,capture_output=True,text=True,timeout=10)
        return completed,self.trace.read_text().splitlines(),self.calls.read_text()
    def test_display_name_maps_to_actual_unit_for_all_operations(self):
        for op in ('start','stop','restart'):
            with self.subTest(op=op):
                r,trace,_=self.call(op);self.assertEqual(r.returncode,0,r.stdout+r.stderr)
                expected=[op+' hestia-web-terminal']
                if op=='restart':expected.insert(0,'reset-failed hestia-web-terminal')
                self.assertEqual(trace,expected)
    def test_canonical_unit_and_unrelated_services_keep_their_names(self):
        for name in ('hestia-web-terminal','nginx','apache2','exim4','dovecot','named','ssh','fail2ban'):
            for op in ('start','stop','restart'):
                with self.subTest(name=name,op=op):
                    r,trace,_=self.call(op,name);self.assertEqual(r.returncode,0);self.assertEqual(trace[-1],op+' '+name)
        r,trace,_=self.call('restart','nginx',restart='no');self.assertEqual(r.returncode,0);self.assertEqual(trace,['reload-or-restart nginx'])
    def test_start_stop_errors_are_not_hidden_by_successful_logging(self):
        for op in ('start','stop'):
            with self.subTest(op=op):
                r,trace,logs=self.call(op,result=1);self.assertEqual(r.returncode,20);self.assertIn('failed',r.stdout);self.assertIn('Error',logs)
                self.assertIn(op+' hestia-web-terminal',trace)
    def test_restart_failure_is_preserved_on_systemd_host(self):
        r,trace,_=self.call('restart',result=1);self.assertEqual(r.returncode,20);self.assertIn('hestia-web-terminal failed',r.stdout)
    def test_firewall_failure_and_php_multi_instance_handling_are_preserved(self):
        for op in ('start','stop'):
            with self.subTest(op=op):
                r,trace,_=self.call(op,'iptables',result=1);self.assertEqual(r.returncode,20);self.assertIn('firewall',trace[0])
                r,trace,_=self.call(op,'php-fpm');self.assertEqual(r.returncode,0);self.assertEqual(trace,[op+' php8.3-fpm',op+' php8.4-fpm'])

if __name__=='__main__':unittest.main()
