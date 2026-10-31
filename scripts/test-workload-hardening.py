#!/usr/bin/env python3
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import yaml
import workload_hardening

class HardeningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        (root / 'pod-security').mkdir()
        (root / 'pod-security/workloads.yaml').write_text(yaml.safe_dump({'workloads': [{'namespace': 'test', 'kind': 'Deployment', 'name': 'api', 'uid': 1001, 'kubernetesToken': False, 'reason': 'No Kubernetes API calls'}]}))
        self.patch = patch.object(workload_hardening, 'ROOT', root)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.doc = {'kind': 'Deployment', 'metadata': {'namespace': 'test', 'name': 'api'}, 'spec': {'template': {'spec': {'automountServiceAccountToken': False, 'securityContext': {'runAsUser': 1001, 'runAsNonRoot': True, 'seccompProfile': {'type': 'RuntimeDefault'}}, 'containers': [{'name': 'api', 'securityContext': {'allowPrivilegeEscalation': False, 'readOnlyRootFilesystem': True, 'capabilities': {'drop': ['ALL']}}}], 'volumes': [{'name': 'tmp', 'emptyDir': {'sizeLimit': '32Mi'}}]}}}}
    def test_accepts_hardened_workload(self):
        workload_hardening.validate([self.doc])
    def test_rejects_regressions_beyond_psa(self):
        for field in ['token', 'filesystem', 'unbounded', 'missing', 'init']:
            d = copy.deepcopy(self.doc); s = d['spec']['template']['spec']
            if field == 'token': s['automountServiceAccountToken'] = True
            if field == 'filesystem': s['containers'][0]['securityContext']['readOnlyRootFilesystem'] = False
            if field == 'unbounded': s['volumes'][0]['emptyDir'] = {}
            if field == 'init': s['initContainers'] = [{'name': 'unsafe'}]
            with self.subTest(field=field), self.assertRaises(AssertionError):
                workload_hardening.validate([] if field == 'missing' else [d])

if __name__ == '__main__': unittest.main()
