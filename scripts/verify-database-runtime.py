#!/usr/bin/env python3
"""Explicit synthetic PostgreSQL rehearsal; never mounts a production data PVC."""
import argparse
import copy
import json
import os
from pathlib import Path
import subprocess
import uuid
import yaml
from runtime_probe import wait_for_completion

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = r'''
set -eu
trap 'pg_ctl -D "$PGDATA" -m fast stop >/dev/null 2>&1 || true' EXIT
start() {
 docker-entrypoint.sh postgres -c listen_addresses=127.0.0.1 -c ssl=on -c ssl_cert_file=/etc/postgresql/tls/tls.crt -c ssl_key_file=/etc/postgresql/tls/tls.key > /tmp/postgres.log 2>&1 &
 for i in $(seq 1 60); do
  if pg_isready -h 127.0.0.1 -U postgres >/dev/null 2>&1; then return; fi
  sleep 1
 done
 tail -20 /tmp/postgres.log
 exit 1
}
start
export PGHOST=shared-postgres.postgres.svc.cluster.local PGHOSTADDR=127.0.0.1 PGUSER=postgres PGDATABASE=postgres PGSSLMODE=verify-full PGSSLROOTCERT=/etc/postgresql/ca/ca.crt
psql -X -v ON_ERROR_STOP=1 -qc "CREATE DATABASE hardening_fixture;"
psql -X -v ON_ERROR_STOP=1 -d hardening_fixture -qc "CREATE EXTENSION vector; CREATE TABLE fixture(id int primary key, value text); INSERT INTO fixture VALUES(1, 'synthetic');"
pg_dump -Fc -d hardening_fixture -f /tmp/fixture.dump
psql -X -v ON_ERROR_STOP=1 -qc "CREATE DATABASE hardening_restored;"
pg_restore --exit-on-error -d hardening_restored /tmp/fixture.dump
test "$(psql -X -At -d hardening_restored -c 'SELECT count(*) FROM fixture')" = 1
pg_ctl -D "$PGDATA" -m fast -w stop >/dev/null
start
test "$(psql -X -At -d hardening_fixture -c 'SELECT count(*) FROM fixture')" = 1
test "$(id -u)" = 999
root_ro=false
while read -r device mountpoint filesystem options rest; do
 if [ "$mountpoint" = / ]; then
  case ",$options," in *,ro,*) root_ro=true;; esac
 fi
done < /proc/mounts
test "$root_ro" = true
if (touch /etc/hardening-write-probe) 2>/dev/null; then rm /etc/hardening-write-probe; exit 1; fi
test ! -e /var/run/secrets/kubernetes.io/serviceaccount/token
printf 'PASS non-root startup, verified TLS, pgvector, dump/restore, existing-data restart and read-only root\n'
'''

def build_job(filename):
    source = yaml.safe_load((ROOT/'shared-postgres'/filename).read_text())
    patches = list(yaml.safe_load_all((ROOT/'shared-postgres/pod-hardening.patch.yaml').read_text()))
    hardening = next(p for p in patches if p['metadata']['name']==source['metadata']['name'])['spec']['template']['spec']
    base = source['spec']['template']['spec']
    c = copy.deepcopy(base['containers'][0])
    pgdata = next(e['value'] for e in c['env'] if e['name']=='PGDATA')
    c.update(command=['/bin/sh','-ec'], args=[SCRIPT], env=[{'name':'PGDATA','value':pgdata},{'name':'POSTGRES_HOST_AUTH_METHOD','value':'trust'},{'name':'POSTGRES_INITDB_ARGS','value':'--data-checksums'}], resources={'requests':{'cpu':'50m','memory':'128Mi'},'limits':{'cpu':'500m','memory':'512Mi'}}, securityContext=copy.deepcopy(hardening['containers'][0]['securityContext']))
    for field in ['readinessProbe','livenessProbe','startupProbe','ports']:c.pop(field,None)
    c['volumeMounts'] += copy.deepcopy(hardening['containers'][0]['volumeMounts'])
    volumes=copy.deepcopy(base.get('volumes',[]))+copy.deepcopy(hardening['volumes'])
    # The old retained template has no CA mount, but uses the same production TLS identity.
    if not any(v['name']=='postgres-root-ca' for v in volumes):
        volumes.append({'name':'postgres-root-ca','secret':{'secretName':'shared-postgres-root-ca','items':[{'key':'tls.crt','path':'ca.crt','mode':292}]}})
        c['volumeMounts'].append({'name':'postgres-root-ca','mountPath':'/etc/postgresql/ca','readOnly':True})
    volumes.append({'name':'postgres-data','emptyDir':{'sizeLimit':'512Mi'}})
    assert not any('persistentVolumeClaim' in v for v in volumes)
    spec={'restartPolicy':'Never','automountServiceAccountToken':False,'securityContext':hardening['securityContext'],'containers':[c],'volumes':volumes}
    return {'apiVersion':'batch/v1','kind':'Job','metadata':{'name':'database-hardening-'+uuid.uuid4().hex[:10],'namespace':'postgres'},'spec':{'backoffLimit':0,'activeDeadlineSeconds':240,'ttlSecondsAfterFinished':600,'template':{'metadata':{'labels':{'app':'database-hardening-rehearsal'}},'spec':spec}}}

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run',action='store_true');args=parser.parse_args()
    assert args.run and os.environ.get('KUBECONFIG'), 'Use --run and an explicit owner KUBECONFIG'
    k=['kubectl','--context','jshipster','--request-timeout=30s','-n','postgres']
    for filename in ['statefulset-18.yaml','statefulset.yaml']:
        job=build_job(filename);name=job['metadata']['name']
        try:
            subprocess.run(k+['create','-f','-'],input=json.dumps(job),text=True,check=True,capture_output=True)
            wait_for_completion(k,name,260)
            logs=subprocess.check_output(k+['logs','job/'+name],text=True)
            assert 'PASS non-root startup' in logs, 'Rehearsal did not complete its checks'
            print(filename, 'PASS synthetic runtime rehearsal',flush=True)
        finally:
            subprocess.run(k+['delete','job',name,'--ignore-not-found=true','--wait=true'],check=True,capture_output=True)
