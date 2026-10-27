#!/usr/bin/env python3
"""Administrative tool inventory and fixed operations; no browser-supplied commands."""
import argparse
import base64
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import time
from business import account, authorize, integer, regular, record
from ops import config, lock, private_directory, private_read, require_root, safe_environment
from mfa import root_json
import projects
import security

PROJECTS = Path('/etc/hestiacp/professional/projects.json')
CLOUD = Path('/etc/hestiacp/professional/cloud-backup.json')
ACTIONS = {'protection-profile','docker-operation','project-operation','cloud-operation','native-backup'}

def read_command(args, timeout=12):
    result = subprocess.run(args,stdin=subprocess.DEVNULL,capture_output=True,env=safe_environment(),timeout=timeout)
    if result.returncode or len(result.stdout)>1048576:raise RuntimeError('Dependency unavailable or operation failed')
    return result.stdout.decode(errors='replace')

def admin(root, actor, owner=None):
    actual = account(root,actor)
    if actual.get('ROLE')!='admin':raise ValueError('Administrator required')
    if owner:account(root,owner,target=True)

def path_config(fs, path):return fs/str(path).lstrip('/')

def project_config(fs):
    path = path_config(fs,PROJECTS)
    return path,projects.settings(path)

def payload(value):return base64.urlsafe_b64encode(json.dumps(value,separators=(',',':')).encode()).decode()

def decode(value):
    if not isinstance(value,str) or len(value)>32768 or not re.fullmatch(r'[A-Za-z0-9_=-]+',value):raise ValueError('Invalid operation payload')
    result = json.loads(base64.urlsafe_b64decode(value))
    if not isinstance(result,dict):raise ValueError('Invalid operation payload')
    return result

def operation(root, fs, actor, action, owner, params, runner=read_command):
    admin(root,actor,owner)
    if action not in ACTIONS or not isinstance(params,dict):raise ValueError('Invalid operation')
    watch = [str(root/'conf/hestia.conf'),str(root/'data/users'/owner/'user.conf')]
    result = {'watch':watch,'notes':[],'reversible':False}
    if action=='protection-profile':
        if set(params)!={'profile','waf','fail2ban','admin_cidrs'}:raise ValueError('Invalid protection fields')
        # Reuse the actual policy parser, including bounded administrator CIDRs.
        folder = private_directory(root/'data/professional-platform/validation',0o700)
        path = folder/(secrets.token_hex(16)+'.json');root_json(path,params)
        try:cfg = security.settings(path)
        finally:path.unlink()
        security.prerequisites(fs,root,cfg,runner)
        watch += [str(fs/security.WAF),str(fs/security.JAIL),str(root/'data/professional/security.json')]
        result['notes'] = ['Aplica ModSecurity/CRS nos sites Apache e ajusta as jails nativas SSH/painel.',
                           'Comece em observação. Proxies diretos, porta 8083 e DDoS exigem outra cobertura.',
                           'O IP administrativo deve estar nas exceções. Políticas existentes são preservadas ou recusadas para revisão.']
        result['config'] = cfg
    elif action=='docker-operation':
        if set(params)!={'operation','target','confirmation'}:raise ValueError('Invalid Docker fields')
        if params['confirmation'] not in ('','EXCLUIR'):raise ValueError('Invalid deletion confirmation')
        command,changes = projects.docker_command(params['operation'],params['target'] or None)
        if not changes:raise ValueError('Use the read-only inventory for this action')
        if params['operation'].endswith('-remove') and params['confirmation']!='EXCLUIR':raise ValueError('Confirm explicit deletion')
        # Force the local daemon; do not inherit a selected remote Docker context.
        result['command'] = [command[0],'--host=unix:///var/run/docker.sock',*command[1:]]
        result['notes'] = ['Operação administrativa no Docker local; não habilita socket para o navegador.',
                           'Remoções não têm reversão automática. Volumes não são apagados por container-remove.',
                           'A execução ocorre em tarefa separada; acompanhe o resultado antes de repetir.']
    elif action=='project-operation':
        if set(params)!={'project','operation'}:raise ValueError('Invalid project fields')
        path,cfg = project_config(fs);name = projects.identifier(params['project']);item = cfg['projects'][name]
        if item['owner']!=owner:raise ValueError('Project owner mismatch')
        watch.append(str(path));kind = item['type'];op = params['operation']
        if kind in ('compose','marketing'):
            watch.append(item['compose_file'])
            command,changes = projects.compose_command(name,item,op,runner)
            if not changes:raise ValueError('Use project inventory for read-only queries')
            result['command'] = [command[0],'--host=unix:///var/run/docker.sock',*command[1:]]
        elif kind=='node' and op in ('start','stop','restart','enable','disable'):
            unit = 'hestia-node-'+name+'.service';unitfile = fs/'etc/systemd/system'/unit
            data = regular(unitfile)
            if not data or not data.startswith(b'# HESTIA_PROFESSIONAL_NODE_V1'):raise ValueError('Install the reviewed Node unit first')
            watch.append(str(unitfile));result['command'] = ['/usr/bin/systemctl',op,unit]
        else:raise ValueError('This project has no supported lifecycle action')
        result['notes'] = ['Controla o projeto registrado com configuração e proprietário verificados.',
                           'Desativar/parar não exclui os dados. Down mantém volumes; a restauração da aplicação exige backup.',
                           'O resultado desta confirmação é o pedido de execução; confira o estado da tarefa.']
    elif action=='cloud-operation':
        if set(params)!={'operation','target'} or params['operation'] not in ('init','run','check','drill','retention','enable-timer','disable-timer'):
            raise ValueError('Invalid cloud operation')
        path = path_config(fs,CLOUD)
        from cloud_backup import settings
        cfg = settings(path);watch.append(str(path))
        target = params['target']
        if target and not any(t['id']==target for t in cfg['targets']):raise ValueError('Unknown backup target')
        if params['operation'] in ('init','drill','retention') and not target:raise ValueError('Choose one explicit destination')
        if params['operation']=='retention' and cfg.get('append_only'):raise ValueError('Append-only policy blocks retention')
        if params['operation'].endswith('-timer'):
            if target:raise ValueError('Account scheduling uses all configured destinations; leave target empty')
            unit = 'hestia-professional-cloud-backup@'+owner+'.timer'
            result['command'] = ['/usr/bin/systemctl','enable' if params['operation']=='enable-timer' else 'disable','--now',unit]
        else:
            result['command'] = ['/usr/bin/python3',str(root/'professional/cloud_backup.py'),params['operation'],
                                 '--config',str(path),'--user',owner,'--apply']
            if target:result['command'] += ['--target',target]
        result['notes'] = ['Executa o fluxo criptografado usando destinos e credenciais privados já cadastrados.',
                           'O agendamento diário abrange todos os destinos cadastrados da conta; deixe o destino vazio para agendar.',
                           'Drill verifica a recuperação do arquivo; não importa SQL nem substitui teste de aplicação.',
                           'Retenção pode excluir snapshots conforme a configuração. A cópia nativa local permanece separada.']
    else:
        if params!={}:raise ValueError('Native backup takes no parameters')
        result['command'] = [str(root/'bin/v-backup-user'),owner]
        result['notes'] = ['Cria backup nativo da conta, incluindo os componentes selecionados no Hestia.',
                           'Não comprova cópia fora da VPS nem restauração da aplicação. Confira espaço e o catálogo.']
    result['watch'] = watch
    return result

def spec(root, fs, actor, action, owner, params):
    value = operation(root,fs,actor,action,owner,params)
    data = {'actor':actor,'owner':owner,'action':action,'params':params}
    return {'watch':value['watch'],'files':[],'forward':[['/usr/bin/python3','-I',str(root/'professional/platform_action_entry.py'),payload(data)]],
            'reverse':[],'validate':[],'reload':[],'notes':value['notes'], 'reversible':False}

def jobs_folder(root):return root/'data/professional-platform/jobs'

def submit(root, fs, data, runner=read_command):
    actor,owner,action,params = (data[k] for k in ('actor','owner','action','params'))
    value = operation(root,fs,actor,action,owner,params)
    from apply import verify_deployment
    if verify_deployment(root)['state']!='verified' or not account(root,actor).get('TWOFA'):raise ValueError('A2F and verified deployment required')
    ident = secrets.token_hex(16);nonce = secrets.token_hex(16)
    job = {**data,'id':ident,'nonce':nonce,'state':'queued','created':time.time(),'expires':time.time()+120,
           'watch':{p:None if regular(p) is None else __import__('hashlib').sha256(regular(p)).hexdigest() for p in value['watch']}}
    root_json(jobs_folder(root)/(ident+'.json'),job)
    try:
        runner(['/usr/bin/systemd-run','--quiet','--collect','--no-block','--unit=hestia-platform-'+ident,
                '--property=Type=exec','--property=User=root','--property=Group=root','--property=UMask=0077',
                '--property=RuntimeMaxSec=21600','--property=KillMode=control-group','--property=StandardOutput=null',
                '--property=StandardError=null','--','/usr/bin/python3','-I',str(root/'professional/platform_job_entry.py'),ident,nonce])
    except Exception:job.update(state='launch-failed');root_json(jobs_folder(root)/(ident+'.json'),job);raise
    return {'state':'queued','job':ident,'operation':action}

def worker(root, fs, ident, nonce, runner=None, integrity=None):
    try:return work_locked(root,fs,ident,nonce,runner,integrity)
    except BlockingIOError:
        if not re.fullmatch(r'[a-f0-9]{32}',ident):raise ValueError('Invalid task')
        path=jobs_folder(root)/(ident+'.json');job=json.loads(private_read(path))
        if job.get('nonce')==nonce and job.get('state')=='queued':
            job.update(state='failed',updated=time.time(),reason='another-administrative-task-is-running')
            root_json(path,job)
        raise

def work_locked(root, fs, ident, nonce, runner=None, integrity=None):
    if not re.fullmatch(r'[a-f0-9]{32}',ident) or not re.fullmatch(r'[a-f0-9]{32}',nonce):raise ValueError('Invalid task')
    path = jobs_folder(root)/(ident+'.json')
    with lock(root/'data/professional-platform/locks/execution.lock'):
        job = json.loads(private_read(path))
        if job['state']!='queued' or job['nonce']!=nonce:raise ValueError('Consumed task')
        from apply import verify_deployment
        verify = integrity or verify_deployment
        job.update(state='running',updated=time.time());root_json(path,job)
        try:
            admin(root,job['actor'],job['owner'])
            if job['expires']<time.time():raise ValueError('Expired task')
            if verify(root)['state']!='verified' or not account(root,job['actor']).get('TWOFA'):raise ValueError('Deployment or A2F changed')
            for name,expected in job['watch'].items():
                raw = regular(name)
                if (None if raw is None else __import__('hashlib').sha256(raw).hexdigest())!=expected:raise ValueError('Configuration changed')
            value = operation(root,fs,job['actor'],job['action'],job['owner'],job['params'])
            if job['action']=='protection-profile':
                result = security.apply_profile(fs,root,value['config'])
                job['result'] = {'profile':result['profile'],'effective_policy':result['effective_policy'],'rollback_id':result['rollback_id']}
            elif runner:runner(value['command'])
            else:
                # No provider output enters public task history; cloud helpers keep their own safe status.
                result = subprocess.run(value['command'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL,env=safe_environment(),timeout=21000)
                if result.returncode:raise RuntimeError('Operation failed')
            job.update(state='succeeded',updated=time.time())
        except BaseException:
            job.update(state='failed',updated=time.time(),reason='operation-or-prerequisite-failed');raise
        finally:root_json(path,job)
    return public_job(job)

def public_job(job):
    result = {k:job[k] for k in ('id','actor','owner','action','state','created','updated','reason','result') if k in job}
    if result.get('state')=='queued' and job.get('expires',0)<time.time():result['state']='queue-expired'
    if result.get('state')=='running' and time.time()-job.get('updated',0)>21600:result['state']='interrupted-review'
    return result

def inventory(root, fs, actor, op, request, runner=read_command):
    admin(root,actor)
    if op=='jobs':
        result = []
        for path in sorted(jobs_folder(root).glob('*.json'),key=lambda p:p.stat().st_mtime,reverse=True)[:100]:result.append(public_job(json.loads(private_read(path))))
        return {'jobs':result}
    if op=='summary':
        conf = config(root/'conf/hestia.conf');states = {}
        for binary in ('docker','node','restic','rclone','clamonacc','mongod','redis-server'):states[binary] = bool(shutil.which(binary))
        protection = security.collect(root,runner)
        return {'binaries':states,'protection':protection,'actor_twofa':bool(account(root,actor).get('TWOFA')),
                'projects_configured':path_config(fs,PROJECTS).is_file(),
                'cloud_configured':path_config(fs,CLOUD).is_file(),'version':conf.get('VERSION'),
                'waf_scope':'apache-backed-sites','mfa_required_for_writes':True}
    if op=='docker':
        action = request.get('operation','containers')
        if action not in ('containers','images','networks','volumes','disk','container-logs','container-stats','container-inspect'):raise ValueError('Use reviewed plan for writes')
        args,changes = projects.docker_command(action,request.get('target') or None)
        text = runner([args[0],'--host=unix:///var/run/docker.sock',*args[1:]])
        return {'operation':action,'output':text}
    if op=='projects':
        path,cfg = project_config(fs)
        poll=request.get('target') or None
        if poll:projects.identifier(poll)
        result = []
        for name,item in cfg['projects'].items():
            row = {k:item[k] for k in ('type','owner','domain','port','url') if k in item};row['id'] = name
            try:
                if name!=poll:
                    row['status']='not-polled';result.append(row);continue
                if item['type']=='node':row['status'] = runner(['/usr/bin/systemctl','is-active','hestia-node-'+name+'.service']).strip()
                elif item['type'] in ('compose','marketing'):
                    args,_ = projects.compose_command(name,item,'status',runner);row['status'] = runner([args[0],'--host=unix:///var/run/docker.sock',*args[1:]])
                else:row['status'] = 'external-or-proxy'
            except (ValueError,RuntimeError,OSError,subprocess.SubprocessError):row['status'] = 'unavailable'
            result.append(row)
        return {'projects':result}
    if op=='backups':
        from cloud_backup import settings
        path = path_config(fs,CLOUD)
        if not path.is_file():return {'configured':False,'targets':[],'next':'Cadastre as credenciais privadas pelo console.'}
        cfg = settings(path)
        return {'configured':True,'targets':[{'id':v['id'],'provider':v['provider']} for v in cfg['targets']],
                'append_only':cfg['append_only'],'rpo_hours':cfg['rpo_hours'],'rto_minutes':cfg['rto_minutes']}
    raise ValueError('Unknown inventory')

def main():
    parser = argparse.ArgumentParser(description=__doc__);parser.add_argument('--actor',required=True)
    parser.add_argument('--op',choices=('summary','docker','projects','backups','jobs'),required=True)
    args = parser.parse_args();require_root();raw = sys.stdin.read(16385)
    if len(raw)>16384:raise ValueError('Oversized request')
    request = json.loads(raw)
    if not isinstance(request,dict) or set(request)-{'operation','target'}:raise ValueError('Invalid request')
    print(json.dumps(inventory(Path('/usr/local/hestia'),Path('/'),args.actor,args.op,request)))

if __name__=='__main__':
    try:main()
    except Exception:
        print('Platform operation refused. Check prerequisites and private configuration.',file=sys.stderr);sys.exit(1)
