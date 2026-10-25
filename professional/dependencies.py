#!/usr/bin/env python3
"""Console-only prerequisite installation from authenticated distribution packages."""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import security
from apply import atomic_file, verify_deployment
from mfa import root_json
from ops import config, lock, private_directory, require_root, safe_environment

PACKAGES={'backup':['restic','rclone'],'waf':['libapache2-mod-security2','modsecurity-crs'],
          'docker':['docker.io','docker-compose-v2'],'node':['nodejs']}
APT=['apt-get','-o','APT::Get::AllowUnauthenticated=false','-o','Acquire::AllowInsecureRepositories=false',
     '-o','Dpkg::Options::=--force-confold']

def command(args, timeout=1800):
    env={**safe_environment(),'DEBIAN_FRONTEND':'noninteractive','NEEDRESTART_MODE':'l'}
    result=subprocess.run(args,stdin=subprocess.DEVNULL,capture_output=True,env=env,timeout=timeout)
    if result.returncode:
        folder=private_directory(Path('/var/lib/hestia-professional-upgrade'),0o700)
        atomic_file(folder/'dependency-error.log',(result.stdout+result.stderr)[-1048576:],0o600)
        raise RuntimeError('Dependency operation failed: '+Path(args[0]).name)
    return result.stdout.decode(errors='replace')

def selected(value):
    names=value.split(',') if isinstance(value,str) else []
    if not names or len(set(names))!=len(names) or set(names)-set(PACKAGES):raise ValueError('Invalid component selection')
    return names

def recovery_cidr(value):
    if not value:
        fields=os.environ.get('SSH_CONNECTION','').split()
        if len(fields)!=4:raise ValueError('Supply --admin-cidr from a recovery console')
        address=ipaddress.ip_address(fields[0]);value=str(address)+('/32' if address.version==4 else '/128')
    network=ipaddress.ip_network(value,strict=False)
    if network.prefixlen<(24 if network.version==4 else 64):raise ValueError('Administrator CIDR too broad')
    return str(network)

def install(root,fs,components,admin_cidr=None,runner=command):
    if config(root/'conf/hestia.conf').get('VERSION')!='1.10.5' or verify_deployment(root)['state']!='verified':
        raise ValueError('Verified installed overlay required')
    names=selected(components);cidr=recovery_cidr(admin_cidr) if 'waf' in names else None
    osfile=fs/'etc/os-release';osinfo={}
    for line in osfile.read_text().splitlines():
        if '=' in line:
            key,value=line.split('=',1);osinfo[key]=value.strip('"')
    if osinfo.get('ID')!='ubuntu' or osinfo.get('VERSION_ID') not in ('24.04','26.04'):raise ValueError('Review distribution packages for this OS')
    folder=private_directory(root/'data/professional-dependencies',0o700)
    state={'state':'preflight','components':names,'results':{},'package_rollback':False}
    with lock(folder/'install.lock'):
        policy=fs/'usr/sbin/policy-rc.d'
        # Do not replace an existing administrator/container service policy.
        if policy.exists() or policy.is_symlink():raise ValueError('Existing policy-rc.d needs console review')
        for unit in ('hestia','nginx','apache2','exim4','dovecot'):runner(['systemctl','is-active',unit])
        if 'docker' in names and shutil.which('docker') and shutil.which('docker')!='/usr/bin/docker':
            raise ValueError('Review an existing non-distribution Docker installation')
        packages=[package for name in names for package in PACKAGES[name]]
        runner(APT+['update'])
        simulated=runner(APT+['--simulate','--no-remove','--no-upgrade','--no-install-recommends','install',*packages])
        if re.search(r'^Remv\s',simulated,re.M):raise ValueError('Package plan removes installed software')
        state['state']='installing';root_json(folder/'status.json',state)
        atomic_file(policy,b'#!/bin/sh\n# HESTIA_PROFESSIONAL_DEPENDENCIES_V1\nexit 101\n',0o755)
        try:
            runner(APT+['--yes','--no-remove','--no-upgrade','--no-install-recommends','install',*packages])
        except BaseException:
            state['state']='package-install-failed-review';root_json(folder/'status.json',state);raise
        finally:
            if policy.read_bytes()!=b'#!/bin/sh\n# HESTIA_PROFESSIONAL_DEPENDENCIES_V1\nexit 101\n':
                raise ValueError('Service policy changed during package operation')
            policy.unlink()
        try:
            for name in names:
                if name=='backup':
                    runner(['restic','version']);runner(['rclone','version'])
                    state['results'][name]={'state':'available','destination_configured':False,'delivery_tested':False}
                elif name=='node':
                    version=runner(['/usr/bin/node','--version']).strip()
                    state['results'][name]={'state':'available','version':version,'project_created':False}
                elif name=='docker':
                    runner(['systemctl','start','docker'])
                    runner(['/usr/bin/docker','--host=unix:///var/run/docker.sock','info','--format','{{.ServerVersion}}'])
                    runner(['/usr/bin/docker','--host=unix:///var/run/docker.sock','compose','version'])
                    state['results'][name]={'state':'available','application_deployed':False}
                else:
                    destination=fs/'etc/modsecurity/modsecurity.conf'
                    recommended=fs/'etc/modsecurity/modsecurity.conf-recommended'
                    if not destination.exists():
                        if not recommended.is_file() or recommended.is_symlink():raise ValueError('Recommended ModSecurity policy unavailable')
                        atomic_file(destination,recommended.read_bytes(),0o644)
                    runner(['a2enmod','security2'])
                    cfg={'profile':'observacao','waf':True,'fail2ban':True,'admin_cidrs':[cidr],
                         'request_body_limit':134217728}
                    result=security.apply_profile(fs,root,cfg,runner)
                    state['results'][name]={'state':'configured','profile':'observacao','blocking':False,
                                            'scope':'apache-backed-sites','rollback_id':result['rollback_id']}
                root_json(folder/'status.json',state)
            runner(['apache2ctl','configtest']);runner(['nginx','-t'])
            for unit in ('hestia','nginx','apache2','exim4','dovecot'):runner(['systemctl','is-active',unit])
            state['state']='succeeded';root_json(folder/'status.json',state);return state
        except BaseException:
            state['state']='configuration-failed-review';root_json(folder/'status.json',state);raise

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--components',required=True)
    parser.add_argument('--admin-cidr');args=parser.parse_args();require_root()
    print(json.dumps(install(Path('/usr/local/hestia'),Path('/'),args.components,args.admin_cidr),ensure_ascii=False))

if __name__=='__main__':
    try:main()
    except Exception:
        print('Prerequisite configuration stopped. Inspect data/professional-dependencies/status.json; installed packages are retained for review.',file=sys.stderr)
        sys.exit(1)
