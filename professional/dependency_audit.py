#!/usr/bin/env python3
"""Generate a deterministic dependency inventory from locks; never resolve or execute packages."""
import argparse
import hashlib
import json
from pathlib import Path

def inventory(root):
    components = []
    locks = sorted(set(root.rglob('composer.lock')) | set(root.rglob('package-lock.json')))
    for path in locks:
        if any(p in ('node_modules', '.git', '.qa') for p in path.parts): continue
        value = json.loads(path.read_text()); relative = str(path.relative_to(root))
        if path.name == 'composer.lock':
            for section in ('packages', 'packages-dev'):
                for item in value.get(section, []):
                    components.append({'ecosystem':'composer','name':item['name'],'version':item['version'],
                        'reference':item.get('source',{}).get('reference'), 'lock':relative,'development':section=='packages-dev',
                        'deployment':'blocked-optional' if relative.startswith('install/deb/filemanager/') else 'active-source'})
        else:
            for name, item in sorted(value.get('packages', {}).items()):
                if not name or not item.get('version'): continue
                components.append({'ecosystem':'npm','name':name.split('node_modules/')[-1], 'version':item['version'],
                    'integrity':item.get('integrity'), 'lock':relative,'development':item.get('dev',False)})
    assets = []
    for line in (root/'install/assets.lock.tsv').read_text().splitlines():
        name,digest,url=line.split('\t');assets.append({'name':name,'sha256':digest,'url':url})
    return {'schema':1,'overlay':json.loads((root/'professional/component-policy.json').read_text())['overlay_version'],
            'scope':'locked source dependencies and downloaded assets; excludes actual VPS packages and external service images',
            'advisories_checked':False, 'components':components, 'assets':assets,
            'lock_hashes':{str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in locks
                           if not any(x in ('node_modules','.git','.qa') for x in p.parts)}}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True,type=Path)
    p.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1]);a=p.parse_args()
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(inventory(a.root),ensure_ascii=False,indent=2)+'\n')

if __name__=='__main__':main()
