#!/usr/bin/env python3
"""Read-only evidence. A successful command does not prove production efficacy."""
import argparse
import json
from pathlib import Path
import pwd
import sys
from ops import command, require_root
from assistant import domain

def diagnose(root, owner, name, runner=command):
    from business import account, record
    account(root,owner,target=True); name = domain(name)
    record(root,owner,'dns',name)
    queries = [(name,t) for t in ('A','AAAA','NS','SOA','MX','TXT','CAA','DS','DNSKEY')]
    queries += [('_dmarc.'+name,'TXT'),('mail._domainkey.'+name,'TXT'),('default._domainkey.'+name,'TXT')]
    answers = []
    for host, kind in queries:
        status, text = runner(['dig','+time=2','+tries=1','+short',host,kind],timeout=4)
        answers.append({'name':host,'type':kind,'completed':status==0,'answer':text[:8192] if status==0 else ''})
    def answer(host,kind): return next(x['answer'] for x in answers if x['name']==host and x['type']==kind)
    txt = answer(name,'TXT'); spf = sum('v=spf1' in line for line in txt.splitlines())
    ns = answer(name,'NS').splitlines()
    return {'domain':name,'queries':answers,'observations':{'spf_records':spf,'spf_single_record':spf==1,
            'dmarc_present':'v=DMARC1' in answer('_dmarc.'+name,'TXT'), 'mx_present':bool(answer(name,'MX')),
            'nameserver_count':len(ns),'dnssec_ds_present':bool(answer(name,'DS'))},
            'dnssec_chain_validated':False,'mail_delivery_tested':False,
            'limitations':['Local resolver answers are not a global propagation test.',
                            'Two DKIM selector examples do not cover every selector.',
                            'PTR, authoritative server independence, DNSSEC validation and real delivery need separate tests.']}

def coverage(owner, proc=Path('/proc')):
    from ops import username
    username(owner); uid = pwd.getpwnam(owner).pw_uid
    if uid < 1000: raise ValueError('System account is not eligible')
    inside = outside = unreadable = 0
    prefix = f'/user.slice/user-{uid}.slice'
    for entry in proc.iterdir():
        if not entry.name.isdigit(): continue
        try:
            lines = (entry/'status').read_text().splitlines()
            values = next(line.split()[1:] for line in lines if line.startswith('Uid:'))
            if str(uid) not in values: continue
            groups = (entry/'cgroup').read_text().splitlines()
            paths = [line.split(':',2)[-1] for line in groups]
            if paths and all(path==prefix or path.startswith(prefix+'/') for path in paths): inside += 1
            else: outside += 1
        except FileNotFoundError: continue
        except (OSError,StopIteration): unreadable += 1
    return {'owner':owner,'uid':uid,'inside_user_slice':inside,'outside_user_slice':outside,
            'unreadable_processes':unreadable,'coverage': 'observed' if inside and not outside and not unreadable else 'incomplete',
            'future_processes_covered':False,'note':'Observation only; PHP pools, Docker, mail and database services may run outside the user slice.'}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--owner',required=True); parser.add_argument('--domain')
    parser.add_argument('--root',type=Path,default=Path('/usr/local/hestia'))
    args = parser.parse_args(); require_root()
    from business import account
    account(args.root,args.owner,target=True)
    print(json.dumps(diagnose(args.root,args.owner,args.domain) if args.domain else coverage(args.owner)))

if __name__ == '__main__': main()
