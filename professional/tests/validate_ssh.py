#!/usr/bin/env python3
"""Parse the actual generated SSH policies, without listening or reloading SSH."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import business

def main():
    binary=os.environ.get('SSHD_BINARY') or shutil.which('sshd')
    if not binary:raise SystemExit('OpenSSH server binary required')
    with tempfile.TemporaryDirectory(prefix='hestia-ssh-qa-') as td:
        root=Path(td)/'hestia'; fs=Path(td)/'system'
        (root/'conf').mkdir(parents=True);(root/'conf/hestia.conf').write_text("VERSION='1.10.5'\nROOT_USER='admin'\n")
        user=root/'data/users/clientone';user.mkdir(parents=True);(user/'user.conf').write_text("ROLE='user'\nSUSPENDED='no'\n")
        ssh=fs/'etc/ssh';(ssh/'hestia-keys').mkdir(parents=True)
        (ssh/'sshd_config').write_text('Include /etc/ssh/sshd_config.d/*.conf\n')
        subprocess.run(['ssh-keygen','-t','ed25519','-N','','-f',str(Path(td)/'host')],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        (ssh/'hestia-keys/clientone').write_bytes((Path(td)/'host.pub').read_bytes())
        policies=[]
        for value in ('keys-only','sftp-only','disabled'):
            spec=business.build(root,fs,'ssh-policy','clientone',{'value':value})
            dropin=Path(td)/'policy.conf';dropin.write_text(spec['files'][0]['body'])
            # A following global directive also checks that Include/Match context is valid.
            main_conf=Path(td)/'sshd_config'
            main_conf.write_text(f'Include {dropin}\nPort 22222\nHostKey {td}/host\nPidFile {td}/pid\n')
            def invoke(args):
                result=subprocess.run([binary,'-f',str(main_conf),*args[1:]],capture_output=True,text=True,timeout=15)
                if result.returncode:raise RuntimeError(result.stderr)
                return result.stdout
            invoke(['sshd','-t'])
            business.effective_ssh({'action':'ssh-policy','owner':'clientone','params':{'value':value}},invoke)
            policies.append(value)
    print(json.dumps({'policies':policies,'syntax_and_effective_configuration':'passed','ssh_listener_started':False,'remote_login_tested':False}))
if __name__=='__main__':main()
