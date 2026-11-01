#!/usr/bin/env python3
"""Owner-only: record public KSOPS resource identities; never persist decrypted values."""
import os
from pathlib import Path
import subprocess
import yaml
ROOT=Path(__file__).resolve().parents[1]
from argocd_projects import identity_hash
def main():
    assert os.environ.get('SOPS_AGE_KEY_FILE'),'Set the owner age-key file; never run this in CI'
    files=set()
    for p in ROOT.rglob('kustomization.yaml'):
        for ref in yaml.safe_load(p.read_text()).get('generators',[]):
            gen=yaml.safe_load((p.parent/ref).read_text())
            assert gen['kind']=='ksops'
            for f in gen['files']:
                path=(p.parent/f).resolve();assert path.is_relative_to(ROOT.resolve());files.add(path)
    result={}
    for p in sorted(files):
        encrypted=list(yaml.safe_load_all(p.read_text()))
        raw=subprocess.run(['sops','--decrypt',str(p)],capture_output=True,text=True,check=True).stdout
        plain=list(yaml.safe_load_all(raw));assert len(plain)==len(encrypted)
        records=[]
        for enc,doc in zip(encrypted,plain):
            assert doc['apiVersion']=='v1' and doc['kind']=='Secret'
            records.append({'identityFingerprint':identity_hash(enc),'metadata':{k:v for k,v in doc['metadata'].items() if k in ('name','namespace')}})
        result[str(p.relative_to(ROOT.resolve()))]=records
    (ROOT/'argo-projects/secret-identities.yaml').write_text(yaml.safe_dump(result,sort_keys=True))
    print('Recorded public identities for',len(result),'KSOPS files; no decrypted values persisted')
if __name__=='__main__':main()
