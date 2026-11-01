#!/usr/bin/env python3
"""Opt-in rehearsal using only a disposable age key and synthetic encrypted data."""
import argparse
import base64
import copy
import json
import os
import subprocess
import uuid
import tempfile
import yaml
import argocd_bootstrap
from runtime_probe import wait_for_completion

SCRIPT = r'''
set -eu
test "$(id -u)" = 999
test ! -e /var/run/secrets/kubernetes.io/serviceaccount/token
root_ro=false
while read -r device mountpoint filesystem options rest; do
 if [ "$mountpoint" = / ]; then case ",$options," in *,ro,*) root_ro=true;; esac; fi
done < /proc/mounts
test "$root_ro" = true
kustomize build /fixture --enable-alpha-plugins --enable-exec > /tmp/rendered.yaml
grep -q 'probe: synthetic-only' /tmp/rendered.yaml
if SOPS_AGE_KEY_FILE=/dev/null kustomize build /fixture --enable-alpha-plugins --enable-exec >/dev/null 2>&1; then exit 1; fi
printf 'PASS non-root install, read-only plugin/root, synthetic decryption and missing-key rejection\n'
'''

def rehearsal(docs):
    name='ksops-hardening-'+uuid.uuid4().hex[:10]
    key=subprocess.run(['age-keygen'],capture_output=True,text=True,check=True).stdout
    recipient=subprocess.run(['age-keygen','-y'],input=key,capture_output=True,text=True,check=True).stdout.strip()
    fixture='apiVersion: v1\nkind: Secret\nmetadata:\n  name: synthetic-only\nstringData:\n  probe: synthetic-only\n'
    # Avoid this repository's production recipient rules for the disposable key.
    with tempfile.TemporaryDirectory(prefix="ksops-fixture-") as tmp:
        encrypted=subprocess.run(['sops','--encrypt','--age',recipient,'--input-type','yaml','--output-type','yaml','--encrypted-regex','^(data|stringData)$','/dev/stdin'],cwd=tmp,input=fixture,capture_output=True,text=True,check=True).stdout
    files={'keys.txt':key,'secret.enc.yaml':encrypted,'kustomization.yaml':'generators:\n- generator.yaml\n','generator.yaml':'apiVersion: viaduct.ai/v1\nkind: ksops\nmetadata:\n  name: fixture\nfiles:\n- secret.enc.yaml\n'}
    secret={'apiVersion':'v1','kind':'Secret','metadata':{'name':name,'namespace':'argocd'},'type':'Opaque','data':{k:base64.b64encode(v.encode()).decode() for k,v in files.items()}}
    source=next(d for d in docs if d['kind']=='Deployment' and d['metadata']['name']=='argocd-repo-server')['spec']['template']['spec']
    init=copy.deepcopy(next(c for c in source['initContainers'] if c['name']=='install-ksops'))
    original=next(c for c in source['containers'] if c['name']=='repo-server')
    main={'name':'probe','image':original['image'],'command':['/bin/sh','-ec'],'args':[SCRIPT],'securityContext':{**original['securityContext'],'runAsUser':999,'runAsGroup':999},'env':[{'name':'SOPS_AGE_KEY_FILE','value':'/fixture/keys.txt'},{'name':'KUSTOMIZE_PLUGIN_HOME','value':'/home/argocd/.config/kustomize/plugin'}],'resources':{'requests':{'cpu':'25m','memory':'128Mi'},'limits':{'cpu':'500m','memory':'384Mi'}},'volumeMounts':[copy.deepcopy(next(m for m in original['volumeMounts'] if m['name']=='custom-tools')),{'name':'fixture','mountPath':'/fixture','readOnly':True},{'name':'tmp','mountPath':'/tmp'}]}
    spec={'restartPolicy':'Never','automountServiceAccountToken':False,'initContainers':[init],'containers':[main],'volumes':[{'name':'custom-tools','emptyDir':{'sizeLimit':'64Mi'}},{'name':'fixture','secret':{'secretName':name}},{'name':'tmp','emptyDir':{'sizeLimit':'128Mi'}}]}
    job={'apiVersion':'batch/v1','kind':'Job','metadata':{'name':name,'namespace':'argocd'},'spec':{'backoffLimit':0,'activeDeadlineSeconds':240,'ttlSecondsAfterFinished':600,'template':{'metadata':{'labels':{'app':'ksops-hardening-rehearsal'}},'spec':spec}}}
    return secret,job

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run',action='store_true');a=parser.parse_args()
    assert a.run and os.environ.get('KUBECONFIG'),'Use --run and an explicit owner KUBECONFIG'
    docs=argocd_bootstrap.render();argocd_bootstrap.validate(docs)
    secret,job=rehearsal(docs);name=job['metadata']['name'];k=['kubectl','--context','jshipster','--request-timeout=30s','-n','argocd']
    try:
        for obj in (secret,job):subprocess.run(k+['create','-f','-'],input=json.dumps(obj),capture_output=True,text=True,check=True)
        wait_for_completion(k,name,270)
        output=subprocess.check_output(k+['logs','job/'+name,'-c','probe'],text=True)
        assert 'PASS non-root install' in output
        print('PASS isolated KSOPS installation, synthetic secret rendering and missing-key rejection')
    finally:
        for kind in ('job','secret'):subprocess.run(k+['delete',kind,name,'--ignore-not-found=true','--wait=true'],capture_output=True,check=True)
