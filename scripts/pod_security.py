"""Validate namespace policy contracts and active rendered workload templates."""
import json
import pathlib
import subprocess
import yaml
ROOT = pathlib.Path(__file__).resolve().parents[1]

def validate(docs):
    config = yaml.safe_load((ROOT / 'pod-security/profiles.yaml').read_text())
    profiles = config['namespaces']
    assert config['version'] == 'v1.35'
    assert config['phase'] in ('audit', 'enforce')
    seen = set()
    inputs = []
    for d in docs:
        kind = d['kind']
        meta = d.get('metadata', {})
        if kind == 'Namespace':
            ns = meta['name']
            if ns not in profiles:
                continue
            assert ns not in seen, 'Duplicate namespace owner: ' + ns
            seen.add(ns)
            labels = meta.get('labels', {})
            profile = profiles[ns]
            assert profile['reason'], 'Document the compatibility reason'
            for mode in ('enforce', 'audit', 'warn'):
                level = ('privileged' if config['phase'] == 'audit' else profile['enforce']) if mode == 'enforce' else 'restricted'
                assert labels.get('pod-security.kubernetes.io/' + mode) == level, ns + ': wrong ' + mode
                assert labels.get('pod-security.kubernetes.io/' + mode + '-version') == config['version'], ns + ': unpinned PSA'
            options = meta.get('annotations', {}).get('argocd.argoproj.io/sync-options', '')
            assert 'Prune=false' in options and 'Delete=false' in options, 'Protect namespace deletion: ' + ns
        if kind == 'Pod':
            template = d
        elif kind in ('Deployment', 'StatefulSet', 'DaemonSet', 'ReplicaSet', 'Job', 'Rollout'):
            template = d['spec']['template']
        elif kind == 'CronJob':
            template = d['spec']['jobTemplate']['spec']['template']
        else:
            continue
        ns = meta.get('namespace', 'default')
        assert ns in profiles, 'Missing namespace security profile: ' + ns
        inputs.append({'Level': profiles[ns]['enforce'], 'Version': config['version'],
                       'Pod': {'metadata': {**template.get('metadata', {}), 'namespace': ns, 'name': meta['name']}, 'spec': template['spec']}})
    assert seen == set(profiles), 'Missing rendered namespace policies: ' + str(set(profiles)-seen)
    subprocess.run(['psa-check'], input=json.dumps(inputs), text=True, check=True)
