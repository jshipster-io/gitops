"""Extra runtime controls that Pod Security Admission does not enforce."""
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]

def validate(docs):
    profiles = yaml.safe_load((ROOT / 'pod-security/workloads.yaml').read_text())['workloads']
    indexed = {(d.get('metadata', {}).get('namespace', 'default'), d.get('kind'), d.get('metadata', {}).get('name')): d for d in docs}
    for p in profiles:
        key = (p['namespace'], p['kind'], p['name'])
        assert key in indexed, f'Missing hardened workload: {key}'
        obj = indexed[key]
        spec = obj['spec']['jobTemplate']['spec']['template']['spec'] if p['kind'] == 'CronJob' else obj['spec']['template']['spec']
        context = spec.get('securityContext', {})
        assert context.get('runAsNonRoot') is True and context.get('runAsUser') == p['uid'], f'Runtime identity drift: {key}'
        assert context.get('seccompProfile', {}).get('type') == 'RuntimeDefault', f'Seccomp drift: {key}'
        assert spec.get('automountServiceAccountToken') is p['kubernetesToken'] and p['reason'], f'Token policy drift: {key}'
        for c in spec.get('initContainers', []) + spec['containers']:
            s = c.get('securityContext', {})
            assert s.get('runAsNonRoot') is not False and s.get('runAsUser', p['uid']) == p['uid'], f'Container identity override: {key}'
            assert s.get('seccompProfile', {'type': 'RuntimeDefault'}).get('type') == 'RuntimeDefault', f'Container seccomp override: {key}'
            assert s.get('allowPrivilegeEscalation') is False and s.get('readOnlyRootFilesystem') is True, f'Writable or escalating container: {key}/{c["name"]}'
            assert s.get('capabilities', {}).get('drop') == ['ALL'] and not s.get('capabilities', {}).get('add'), f'Capabilities drift: {key}'
        for v in spec.get('volumes', []):
            if 'emptyDir' in v:
                assert v['emptyDir'].get('sizeLimit'), f'Unbounded writable volume: {key}/{v["name"]}'
    print(f'PASS: {len(profiles)} hardened workload runtime contracts')
