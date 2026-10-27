"""Run the actual shell activator against isolated runtime/service fixtures."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]

class WebTerminalTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.base=Path(self.tmp.name)
        self.root=self.base/'hestia';self.bin=self.base/'bin';self.bin.mkdir();(self.root/'func').mkdir(parents=True);(self.root/'conf').mkdir()
        (self.root/'web-terminal').mkdir();(self.root/'web-terminal/server.js').write_text('// fixture')
        (self.root/'professional').mkdir()
        (self.root/'professional/terminal_guard.py').write_text('import os\nraise SystemExit(1 if os.environ.get("QA_FAIL")=="hardening" else 0)\n')
        self.trace=self.base/'trace';self.trace.write_text('')
        (self.root/'func/main.sh').write_text('source_conf() { :; }; check_hestia_demo_mode() { :; }; log_event() { :; }; OK=0; ARGUMENTS=""\n')
        self.bootstrap=self.base/'bootstrap';self.bootstrap.write_text(f'HESTIA={self.root}\nBIN={self.bin}\nWEB_TERMINAL=false\n')
        self.node=self.bin/'node';self.executable(self.node,'#!/bin/sh\nprintf "%s\\n" "$QA_NODE"\n')
        for name in ('systemctl','apt-get','v-change-sys-config-value','v-log-action'):
            self.executable(self.bin/name,'''#!/bin/sh
printf '%s %s\n' "$(basename "$0")" "$*" >> "$QA_TRACE"
if [ "$1" = "$QA_FAIL" ]; then exit 1; fi
if [ "$(basename "$0")" = apt-get ] && [ "$QA_FAIL" = package ]; then exit 1; fi
if [ "$(basename "$0")" = apt-get ]; then touch "$HESTIA/web-terminal/server.js"; fi
exit 0
''')
        script=(ROOT/'bin/v-add-sys-web-terminal').read_text().replace('source /etc/hestiacp/hestia.conf','source '+str(self.bootstrap)).replace('/usr/bin/node',str(self.node))
        self.script=self.base/'activator';self.script.write_text(script)
    def executable(self,path,text):path.write_text(text);path.chmod(0o755)
    def run_script(self,node='v24.12.0',fail='never'):
        env={**os.environ,'PATH':str(self.bin)+':/usr/bin:/bin','QA_NODE':node,'QA_FAIL':fail,'QA_TRACE':str(self.trace),'HESTIA':str(self.root)}
        return subprocess.run(['bash',str(self.script)],env=env,capture_output=True,text=True,timeout=10)
    def test_old_missing_and_invalid_node_refuse_before_config_or_packages(self):
        for node in ('v22.22.1','unavailable','v23.1.0','invalid'):
            with self.subTest(node=node):
                r=self.run_script(node);self.assertNotEqual(r.returncode,0);self.assertIn('Node.js 24',r.stderr);self.assertEqual(self.trace.read_text(),'')
    def test_service_must_start_enable_and_be_active_before_flag_is_written(self):
        r=self.run_script();self.assertEqual(r.returncode,0,r.stderr)
        lines=self.trace.read_text().splitlines();self.assertEqual(lines[:4],['systemctl start hestia-web-terminal','systemctl enable hestia-web-terminal','systemctl is-active --quiet hestia-web-terminal','v-change-sys-config-value WEB_TERMINAL true'])
    def test_start_enable_status_and_package_failures_never_set_enabled(self):
        for failure in ('start','enable','is-active','package','hardening'):
            with self.subTest(failure=failure):
                self.trace.write_text('')
                p=self.root/'web-terminal/server.js'
                if failure=='package':p.unlink()
                r=self.run_script(fail=failure);self.assertNotEqual(r.returncode,0);self.assertNotIn('v-change-sys-config-value',self.trace.read_text())
    def test_missing_package_install_preserves_node_runtime(self):
        (self.root/'web-terminal/server.js').unlink();r=self.run_script();self.assertEqual(r.returncode,0,r.stderr)
        trace=self.trace.read_text();self.assertIn('install hestia-web-terminal',trace);self.assertNotIn('install nodejs',trace)
        self.assertNotIn('nodesource',trace)

if __name__=='__main__':unittest.main()
