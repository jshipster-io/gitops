#!/usr/bin/env python3
"""Read-only runtime/template checks for the staged hardening registry."""
import json
import os
import subprocess
import workload_hardening
import yaml

assert os.environ.get('KUBECONFIG'), 'Set an explicit owner KUBECONFIG'
K = ['kubectl', '--context', 'jshipster', '--request-timeout=30s']
def get(*args):
    return json.loads(subprocess.check_output(K + list(args) + ['-o', 'json'], text=True))

profiles = yaml.safe_load((workload_hardening.ROOT / 'pod-security/workloads.yaml').read_text())['workloads']
docs = [get('get', p['kind'], p['name'], '-n', p['namespace']) for p in profiles]
workload_hardening.validate(docs)
for p, obj in zip(profiles, docs):
    if p['kind'] not in ('Deployment', 'StatefulSet'):
        continue  # Never execute notification, business or backup jobs for validation.
    status, spec = obj['status'], obj['spec']
    replicas = spec.get('replicas', 1)
    if replicas == 0:
        assert p.get('replicas') == 0 and not status.get('readyReplicas', 0), p['name']
        print('PASS retained offline database:', p['name'], flush=True)
        continue
    assert status.get('observedGeneration', 0) >= obj['metadata']['generation'], p['name']
    assert status.get('updatedReplicas', 0) == replicas and status.get('availableReplicas', 0) >= replicas, p['name']
    selector = ','.join(k + '=' + v for k, v in spec['selector']['matchLabels'].items())
    pods = get('get', 'pods', '-n', p['namespace'], '-l', selector)['items']
    pods = [x for x in pods if not x['metadata'].get('deletionTimestamp')]
    assert len(pods) == replicas, f'Rollout still replacing pods: {p["name"]}'
    for pod in pods:
        assert any(c['type'] == 'Ready' and c['status'] == 'True' for c in pod['status'].get('conditions', [])), p['name']
        runtime = {'kind': p['kind'], 'metadata': obj['metadata'], 'spec': {**obj['spec'], 'template': {'spec': pod['spec']}}}
        # Admission-injected tokens/volumes must not weaken the original controls.
        i = docs.index(obj)
        actual = docs.copy(); actual[i] = runtime
        workload_hardening.validate(actual)
    print('PASS ready hardened replacement:', p['namespace'] + '/' + p['name'], flush=True)
print('No workloads or scheduled jobs were started by this verifier.')
