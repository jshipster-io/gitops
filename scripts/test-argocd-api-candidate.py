#!/usr/bin/env python3
import copy
import importlib.util
from pathlib import Path
import unittest
import argocd_bootstrap

spec = importlib.util.spec_from_file_location('candidate', Path(__file__).with_name('verify-argocd-api-candidate.py'))
candidate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(candidate)


class CanaryIsolation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        docs = argocd_bootstrap.render()
        cls.server = next(d for d in docs if d['kind'] == 'Deployment' and d['metadata']['name'] == 'argocd-server')
        cls.services = [d for d in docs if d['kind'] == 'Service']

    def test_canary_preserves_security_and_cannot_receive_service_traffic(self):
        before = copy.deepcopy(self.server)
        pod = candidate.isolated_pod(self.server, self.services, 'candidate@sha256:example', 'isolated-canary')
        self.assertEqual(before, self.server)
        original = self.server['spec']['template']['spec']
        self.assertEqual(pod['spec']['serviceAccountName'], original['serviceAccountName'])
        self.assertEqual(pod['spec']['containers'][0]['securityContext'], original['containers'][0]['securityContext'])
        self.assertEqual(pod['spec']['activeDeadlineSeconds'], 300)
        self.assertEqual(pod['spec']['restartPolicy'], 'Never')
        self.assertNotEqual(pod['metadata']['labels']['app.kubernetes.io/instance'], 'argocd')

    def test_broader_service_selector_stops_before_creation(self):
        services = [{'spec': {'selector': {'app.kubernetes.io/name': 'argocd-server'}}}]
        with self.assertRaises(AssertionError):
            candidate.isolated_pod(self.server, services, 'candidate@sha256:example', 'isolated-canary')


if __name__ == '__main__':
    unittest.main()
