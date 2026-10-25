#!/usr/bin/env python3
"""Query OSV for locked versions. Unknown/network failures are never approval."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import urllib.request
from dependency_audit import inventory

def audit(root):
    unique = {}
    for component in inventory(root)['components']:
        key = (component['ecosystem'],component['name'],component['version'])
        unique.setdefault(key,[]).append(component.get('deployment','active-source'))
    items=list(unique); findings=[]
    for start in range(0,len(items),100):
        batch=items[start:start+100]
        queries=[{'package':{'ecosystem':{'npm':'npm','composer':'Packagist'}[e],'name':n},'version':v.removeprefix('v')} for e,n,v in batch]
        request=urllib.request.Request('https://api.osv.dev/v1/querybatch',data=json.dumps({'queries':queries}).encode(),headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(request,timeout=45) as response: result=json.load(response)['results']
        if len(result)!=len(batch):raise ValueError('Incomplete advisory response')
        for key,entry in zip(batch,result):
            if entry.get('vulns'):
                findings.append({'ecosystem':key[0],'name':key[1],'version':key[2],
                                 'ids':[v['id'] for v in entry['vulns']],'deployment':sorted(set(unique[key]))})
    active=[f for f in findings if f['deployment']!=['blocked-optional']]
    return {'queried_at':datetime.now(timezone.utc).isoformat(),'service':'OSV querybatch',
            'unique_locked_versions':len(items),'findings':findings,'active_findings':len(active),
            'status':'failed' if active else 'passed-with-blocked-component-findings' if findings else 'passed',
            'vps_packages_checked':False,'unknown_vulnerabilities_excluded':False}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1]);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    try: result=audit(a.root); code=1 if result['active_findings'] else 0
    except Exception:
        result={'status':'incomplete','error':'Advisory lookup could not be completed','queried_at':datetime.now(timezone.utc).isoformat()};code=2
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='findings'}));return code
if __name__=='__main__':sys.exit(main())
