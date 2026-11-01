#!/usr/bin/env python3
"""Verify live namespace labels and PSA admission without creating any pod.
Requires an explicit KUBECONFIG. Includes live Helm/operator workload templates.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import yaml

assert os.environ.get('KUBECONFIG'), 'Set an explicit owner KUBECONFIG'
K=['kubectl','--context','jshipster','--request-timeout=30s']
def get(*args):
    return json.loads(subprocess.check_output(K+list(args)+['-o','json'],text=True))
def submit(pod):
    return subprocess.run(K+['create','--dry-run=server','-f','-'],input=json.dumps(pod),capture_output=True,text=True)
config=yaml.safe_load((Path(__file__).resolve().parents[1]/'pod-security/profiles.yaml').read_text())
profiles=config['namespaces']
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--namespace', action='append', help='Limit checks to named profile(s); default is all')
args=parser.parse_args()
if args.namespace:
    assert set(args.namespace)<=set(profiles), 'Unknown namespace profile'
    profiles={n:p for n,p in profiles.items() if n in args.namespace}

for ns,p in profiles.items():
    live=get('get','namespace',ns)['metadata']['labels']
    expected=p['enforce'] if config['phase']=='enforce' else 'privileged'
    assert live.get('pod-security.kubernetes.io/enforce')==expected, ns+': enforcement drift'
    for mode in ('enforce','audit','warn'):
        assert live.get('pod-security.kubernetes.io/'+mode+'-version')==config['version'],ns+': version drift'
    assert live.get('pod-security.kubernetes.io/audit')=='restricted'
    assert live.get('pod-security.kubernetes.io/warn')=='restricted'
items=get('get','deployments,statefulsets,daemonsets,cronjobs','-A')['items']
checked=0
for item in items:
    ns=item['metadata']['namespace']
    if ns not in profiles:continue
    spec=item['spec']
    template=spec['jobTemplate']['spec']['template'] if item['kind']=='CronJob' else spec['template']
    pod={'apiVersion':'v1','kind':'Pod','metadata':{'namespace':ns,'name':'psa-check-'+hashlib.sha256(item['metadata']['name'].encode()).hexdigest()[:16], 'labels':template.get('metadata',{}).get('labels',{})},'spec':copy.deepcopy(template['spec'])}
    for claim in spec.get('volumeClaimTemplates', []):
        name=claim['metadata']['name']
        pod['spec'].setdefault('volumes', []).append({'name':name,'persistentVolumeClaim':{'claimName':name+'-'+item['metadata']['name']+'-0'}})
    r=submit(pod)
    assert r.returncode==0, ns+'/'+item['metadata']['name']+': '+r.stderr
    checked+=1
print(f'PASS: {checked} live controller/job templates admitted (server dry-run)',flush=True)
for ns,p in profiles.items():
    if config['phase']!='enforce' or p['enforce']=='privileged':continue
    safe={'apiVersion':'v1','kind':'Pod','metadata':{'name':'psa-admission-proof','namespace':ns},'spec':{'automountServiceAccountToken':False,'securityContext':{'runAsNonRoot':True,'runAsUser':1001,'seccompProfile':{'type':'RuntimeDefault'}},'containers':[{'name':'probe','image':'alpine:3.23','securityContext':{'allowPrivilegeEscalation':False,'capabilities':{'drop':['ALL']}}}]}}
    if ns == 'azure-operators':
        r=submit(safe)
        assert r.returncode != 0 and 'operator namespace cannot run pods' in r.stderr, 'Operator no-workloads admission weakened: '+r.stderr
        print('PASS:',ns,'intentionally rejects even compliant pods',flush=True)
        continue
    assert submit(safe).returncode==0, ns+': compliant pod rejected'
    bad=copy.deepcopy(safe);bad['spec']['containers'][0]['securityContext'].update({'privileged':True,'allowPrivilegeEscalation':True})
    r=submit(bad)
    assert r.returncode!=0 and 'violates PodSecurity' in r.stderr,ns+': privileged pod not rejected by PSA: '+r.stderr
    if p['enforce']=='restricted':
        bad=copy.deepcopy(safe);bad['spec']['securityContext']['runAsUser']=0
        r=submit(bad)
        assert r.returncode!=0 and 'violates PodSecurity' in r.stderr,ns+': root pod not rejected by PSA: '+r.stderr
    print('PASS:',ns,p['enforce'],'positive/negative admission',flush=True)
print('No test pods were created.')
