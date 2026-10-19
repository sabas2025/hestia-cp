#!/usr/bin/env python3
"""Local configuration assistant: deterministic plans, no AI service or arbitrary commands."""
import argparse
import ipaddress
import json
from pathlib import Path
import re
import sys
from ops import command

def domain(value):
    if not isinstance(value, str): raise ValueError('Domain required')
    value = value.rstrip('.').encode('idna').decode('ascii').lower()
    if len(value) > 253 or '.' not in value or not all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', s) for s in value.split('.')):
        raise ValueError('Invalid domain')
    try: ipaddress.ip_address(value)
    except ValueError: return value
    raise ValueError('Use a domain, not an IP address')

def plan(topic, name, address):
    name = domain(name); ip = ipaddress.ip_address(address)
    if not ip.is_global: raise ValueError('Use the public server address')
    if topic not in ('dns', 'email', 'server', 'backup', 'security'): raise ValueError('Unknown topic')
    records = [{'type': 'A' if ip.version == 4 else 'AAAA', 'name': name, 'value': str(ip)}]
    steps = ['Confirme o IP e o provedor que hospeda a zona DNS.', 'Revise os registros existentes antes de publicar qualquer alteração.']
    links = [{'label': 'DNS', 'href': '/list/dns/'}]
    if topic == 'email':
        records += [{'type': 'A' if ip.version == 4 else 'AAAA', 'name': 'mail.' + name, 'value': str(ip)},
                    {'type': 'MX', 'name': name, 'value': '10 mail.' + name},
                    {'type': 'TXT', 'name': name, 'value': f'v=spf1 ip{ip.version}:{ip} ~all'},
                    {'type': 'TXT', 'name': '_dmarc.' + name, 'value': 'v=DMARC1; p=none'}]
        steps += ['O SPF acima é exemplo para este servidor: mescle todos os remetentes autorizados em um único SPF.',
                  'Ative DKIM no domínio de e-mail e copie a chave pública real do painel; não invente a chave.',
                  'Solicite ao provedor da VPS o PTR do IP para mail.' + name + ' e confira o A/AAAA correspondente.',
                  'Confira MX, TLS, portas SMTP/IMAP e autenticação; envie e receba mensagens de teste.',
                  'DMARC começa em observação; configure relatórios e só avance para quarantine/reject após validar os remetentes.']
        links += [{'label': 'E-mail', 'href': '/list/mail/'}]
    elif topic == 'server':
        steps += ['Use hostname exclusivo do painel, com DNS e certificado válidos.', 'Revise atualizações, espaço, permissões, 2FA e usuário de aplicação dedicado.',
                  'Uma VPS com CyberPanel ou aaPanel exige migração para um servidor limpo, não instalação por cima.']
    elif topic == 'backup':
        steps += ['Ative backup local nativo para incluir arquivos dos sites e dumps dos bancos.', 'Configure os destinos e as credenciais somente nos arquivos root/0600.',
                  'Execute plan, init, run, check e drill; inicialização e retenção exigem destino explícito.',
                  'Guarde a senha de criptografia fora da VPS e teste a restauração de SQL e da aplicação em homologação.']
        links += [{'label': 'Backup da conta', 'href': '/list/backup/'}]
    elif topic == 'security':
        steps += ['ModSecurity + OWASP CRS protege requisições web; Fail2Ban limita tentativas repetidas de autenticação.',
                  'Comece o WAF em observação e valide login, API Tiny/VSM, OAuth, checkout e upload de vídeos.',
                  'Avance de PL1 para PL2/PL3 após tratar falsos positivos com exceções por regra e rota.',
                  'Antes de aplicar Fail2Ban, inclua o IP administrativo e mantenha acesso ao console e plano de rollback.']
    return {'schema': 1, 'assistant': 'local-guided-rules', 'mode': 'plan', 'topic': topic,
            'domain': name, 'records': records if topic in ('dns', 'email') else [], 'steps': steps,
            'links': links, 'changes_applied': False, 'dkim_generated': False}

def inspect(name, runner=command):
    name = domain(name)
    result = []
    for record in ('A', 'AAAA', 'MX', 'TXT'):
        status, output = runner(['dig', '+time=3', '+tries=1', '+short', name, record], timeout=6)
        result.append({'type': record, 'query_completed': status == 0, 'answers': output[:8192] if status == 0 else ''})
    return result

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--topic', required=True, choices=('dns', 'email', 'server', 'backup', 'security'))
    parser.add_argument('--domain', required=True, type=domain); parser.add_argument('--ip', required=True)
    parser.add_argument('--check-dns', action='store_true')
    args = parser.parse_args(); result = plan(args.topic, args.domain, args.ip)
    if args.check_dns: result['dns_observed'] = inspect(args.domain)
    print(json.dumps(result, ensure_ascii=False, indent=2)); return 0

if __name__ == '__main__':
    try: sys.exit(main())
    except (ValueError, UnicodeError): print('Revise o domínio e o IP público informados.', file=sys.stderr); sys.exit(1)
