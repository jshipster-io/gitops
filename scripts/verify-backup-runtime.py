#!/usr/bin/env python3
"""Explicit isolated schema-only backup probes; never overwrite scheduled archives."""
import argparse
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import uuid
import yaml
from runtime_probe import wait_for_completion

ROOT=Path(__file__).resolve().parents[1]
UPLOAD=r'''
set -eu
python3.12 /var/run/azure-workload-login/login.py
NAME="hardening-probes/PROBE_ID.txt"
cleanup() { az storage blob delete --container-name pg-backups --name "$NAME" --only-show-errors --output none; }
trap cleanup EXIT
printf 'synthetic backup hardening probe\n' > /tmp/probe.txt
az storage blob upload --container-name pg-backups --name "$NAME" --file /tmp/probe.txt --overwrite false --only-show-errors --output none
az storage blob download --container-name pg-backups --name "$NAME" --file /tmp/readback.txt --only-show-errors --output none
python3.12 -c 'from pathlib import Path; assert Path("/tmp/probe.txt").read_bytes() == Path("/tmp/readback.txt").read_bytes()'
test "$(id -u)" = 1001
test ! -e /var/run/secrets/kubernetes.io/serviceaccount/token
root_ro=false
while read -r device mountpoint filesystem options rest; do
 if [ "$mountpoint" = / ]; then
  case ",$options," in *,ro,*) root_ro=true;; esac
 fi
done < /proc/mounts
test "$root_ro" = true
if (touch /etc/hardening-write-probe) 2>/dev/null; then rm /etc/hardening-write-probe; exit 1; fi
printf 'PASS schema-only dump and synthetic Azure upload/read/delete under non-root read-only settings\n'
'''

def candidates():
    with tempfile.TemporaryDirectory(prefix='backup-hardening-render-') as tmp:
        tree=Path(tmp)/'pg-backups';shutil.copytree(ROOT/'pg-backups',tree)
        p=tree/'kustomization.yaml';d=yaml.safe_load(p.read_text());d.pop('generators',None);p.write_text(yaml.safe_dump(d))
        docs=list(yaml.safe_load_all(subprocess.check_output(['kustomize','build',str(tree)],text=True)))
    changed={x['metadata']['name'] for x in yaml.safe_load_all((ROOT/'pg-backups/pod-hardening.patch.yaml').read_text())}
    return [d for d in docs if d and d['kind']=='CronJob' and d['metadata']['name'] in changed]

def build_job(source):
    spec=copy.deepcopy(source['spec']['jobTemplate']['spec']);spec.update(backoffLimit=0,activeDeadlineSeconds=300,ttlSecondsAfterFinished=600)
    token=uuid.uuid4().hex;spec['template']['spec']['restartPolicy']='Never'
    dump=spec['template']['spec']['initContainers'][0]
    assert dump['name']=='pg-dump' and len(dump['args'])==1 and dump['args'][0].count('pg_dump ')==1
    dump['args'][0]=dump['args'][0].replace('pg_dump ','pg_dump --schema-only ')
    upload=spec['template']['spec']['containers'][0];assert upload['name']=='upload'
    upload['command']=['/bin/sh','-ec'];upload['args']=[UPLOAD.replace('PROBE_ID',token)]
    return {'apiVersion':'batch/v1','kind':'Job','metadata':{'namespace':'pg-backups','name':'backup-hardening-'+token[:10]},'spec':spec}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',action='store_true');a=p.parse_args()
    assert a.run and os.environ.get('KUBECONFIG'),'Use --run and an explicit owner KUBECONFIG'
    k=['kubectl','--context','jshipster','--request-timeout=30s','-n','pg-backups']
    for source in candidates():
        job=build_job(source);name=job['metadata']['name']
        try:
            subprocess.run(k+['create','-f','-'],input=json.dumps(job),text=True,check=True,capture_output=True)
            wait_for_completion(k,name,330)
            logs=subprocess.check_output(k+['logs','job/'+name,'-c','upload'],text=True)
            assert 'PASS schema-only dump' in logs,'Upload test did not complete'
            print(source['metadata']['name'],'PASS schema-only dump and synthetic blob round trip/cleanup',flush=True)
        finally:
            subprocess.run(k+['delete','job',name,'--ignore-not-found=true','--wait=true'],check=True,capture_output=True)
