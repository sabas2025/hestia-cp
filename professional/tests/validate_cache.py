#!/usr/bin/env python3
"""Validate rendered HTTP/TLS templates with real Nginx; never start a worker."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from business import pool_spec
ROOT=Path(__file__).resolve().parents[2]

def main():
    binary=os.environ.get('NGINX_BINARY') or shutil.which('nginx')
    if not binary: raise SystemExit('Nginx is required')
    with tempfile.TemporaryDirectory(prefix='hestia-nginx-qa-') as temporary:
        base=Path(temporary); cert=base/'cert.pem'; key=base/'key.pem'
        subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(key),'-out',str(cert),'-days','1','-subj','/CN=example.test'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        values={'ip':'127.0.0.1','proxy_port':'18080','proxy_ssl_port':'18443','web_port':'18081','web_ssl_port':'18444',
                'domain_idn':'example.test','alias_idn':'www.example.test','domain':'example.test','web_system':'apache2',
                'home':str(base/'home'),'user':'clientone','docroot':str(base/'public'),'sdocroot':str(base/'public'),
                'ssl_pem':str(cert),'ssl_key':str(key),'proxy_extensions':'jpg|css|woff2'}
        for path in ('logs','public','client_temp','proxy_temp','fastcgi_temp','uwsgi_temp','scgi_temp'):(base/path).mkdir()
        templates=[]
        for suffix in ('tpl','stpl'):
            text=(ROOT/f'professional/cache-templates/professional-safe.{suffix}').read_text()
            for name,value in values.items():text=text.replace('%'+name+'%',value)
            text=text.replace('/var/log/apache2/domains/',str(base/'logs')+'/')
            templates.append(text)
        pool=pool_spec(Path('/'),'clientone','example.test')['body'].replace('/var/cache/nginx/hestia-pro/clientone/example.test',str(base/'cache'))
        configuration=f'''user root root;
error_log {base}/error.log;
pid {base}/nginx.pid;
events {{}}
http {{
access_log off;
log_format bytes '$bytes_sent';
client_body_temp_path {base}/client_temp;
proxy_temp_path {base}/proxy_temp;
fastcgi_temp_path {base}/fastcgi_temp;
uwsgi_temp_path {base}/uwsgi_temp;
scgi_temp_path {base}/scgi_temp;
map $request_method $anti_replay {{ default 0; }}
{pool}
{''.join(templates)}
}}
'''
        path=base/'nginx.conf';path.write_text(configuration)
        result=subprocess.run([binary,'-t','-p',str(base)+'/', '-c',str(path)],capture_output=True,text=True,timeout=20)
        if result.returncode: raise SystemExit(result.stderr)
    print(json.dumps({'templates':2,'nginx_syntax':'passed','nginx_started':False,'application_cache_hit_tested':False}))
if __name__=='__main__':main()
