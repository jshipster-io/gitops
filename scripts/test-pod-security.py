#!/usr/bin/env python3
import copy
import json
import subprocess
import unittest

class AdmissionTests(unittest.TestCase):
    def pod(self):
        return {'metadata': {'name': 'probe', 'namespace': 'test'}, 'spec': {
            'securityContext': {'runAsNonRoot': True, 'seccompProfile': {'type': 'RuntimeDefault'}},
            'containers': [{'name': 'test', 'image': 'alpine:3.23', 'securityContext': {
                'allowPrivilegeEscalation': False, 'capabilities': {'drop': ['ALL']}}}]}}
    def allowed(self, pod, level='restricted'):
        return subprocess.run(['psa-check'], input=json.dumps([{'Pod': pod, 'Level': level, 'Version': 'v1.35'}]), text=True, capture_output=True).returncode == 0
    def test_restricted_accepts_compliant_pod(self):
        self.assertTrue(self.allowed(self.pod()))
    def test_restricted_rejects_unsafe_init_and_ephemeral_containers(self):
        for key in ['initContainers', 'ephemeralContainers']:
            p=self.pod();p['spec'][key]=[{'name':'unsafe','image':'alpine:3.23'}]
            self.assertFalse(self.allowed(p))
    def test_baseline_rejects_host_access_and_privilege(self):
        for patch in [{'hostNetwork':True}, {'volumes':[{'name':'host','hostPath':{'path':'/'}}]}]:
            p=self.pod();p['spec'].update(patch);self.assertFalse(self.allowed(p,'baseline'))
        p=self.pod();p['spec']['containers'][0]['securityContext']['privileged']=True
        self.assertFalse(self.allowed(p,'baseline'))
    def test_baseline_allows_legacy_root_but_restricted_rejects_it(self):
        p=self.pod();p['spec']['securityContext']={'runAsUser':0}
        self.assertTrue(self.allowed(p,'baseline'));self.assertFalse(self.allowed(p))
if __name__ == '__main__': unittest.main()
