#!/usr/bin/env python3
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import workload_identity

class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.config = {'tenantID': 'tenant', 'workloads': [{'kind': 'Deployment', 'namespace': 'app', 'name': 'app', 'serviceAccount': 'app', 'clientID': '11111111-1111-1111-1111-111111111111'}]}
        self.docs = [
            {'kind': 'ServiceAccount', 'metadata': {'namespace': 'app', 'name': 'app', 'annotations': {'azure.workload.identity/client-id': self.config['workloads'][0]['clientID'], 'azure.workload.identity/tenant-id': 'tenant'}}},
            {'kind': 'Deployment', 'metadata': {'namespace': 'app', 'name': 'app'}, 'spec': {'template': {'metadata': {'labels': {'azure.workload.identity/use': 'true'}}, 'spec': {'serviceAccountName': 'app', 'containers': [{'name': 'app'}]}}}},
        ]
    def test_rejects_credentials_hidden_behind_env_from(self):
        with self.assertRaises(AssertionError):
            workload_identity.reject_secret_fields({'stringData': {'AZURE_CLIENT_SECRET': 'ENC[opaque]'}})
    def test_valid_binding(self):
        workload_identity.validate(self.docs, self.config)
    def test_retired_service_cannot_reintroduce_azure_ai_keys(self):
        for name in ['AZURE_OPENAI_API_KEY', 'AZURE_SPEECH_KEY', 'AZURE_DOCUMENT_INTELLIGENCE_KEY', 'ANPR_AZURE_ACCESS_KEY']:
            docs = copy.deepcopy(self.docs)
            docs.append({'kind': 'Deployment', 'metadata': {'name': 'reactivated-app'}, 'spec': {'template': {'spec': {'containers': [{'name': 'app', 'env': [{'name': name, 'valueFrom': {'secretKeyRef': {'name': 'legacy', 'key': name}}}]}]}}}})
            with self.subTest(name=name), self.assertRaises(AssertionError):
                workload_identity.validate(docs, self.config)
    def test_configmap_env_from_cannot_restore_keys(self):
        self.docs.append({'kind': 'ConfigMap', 'metadata': {'name': 'legacy'}, 'data': {'AZURE_STORAGE_CONNECTION_STRING': 'legacy'}})
        with self.assertRaises(AssertionError):
            workload_identity.validate(self.docs, self.config)
    def test_active_unprofiled_app_secret_is_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / 'reactivated-app'
            app.mkdir()
            (app / 'kustomization.yaml').write_text('generators: [generator.yaml]\n')
            (app / 'generator.yaml').write_text('files: [secret.yaml]\n')
            (app / 'secret.yaml').write_text('stringData:\n  AZURE_OPENAI_API_KEY: ENC[opaque]\n')
            with patch.object(workload_identity, 'ROOT', root), self.assertRaises(AssertionError):
                workload_identity.validate_secret_fields({'workloads': []}, folders={'reactivated-app'})
    def test_unrelated_provider_credentials_remain_allowed(self):
        workload_identity.reject_secret_fields({'stringData': {'OPENAI_API_KEY': 'ENC[opaque]', 'POSTGRES_PASSWORD': 'ENC[opaque]'}})
    def test_rejects_missing_label_or_wrong_service_account(self):
        for location, key in [('metadata', 'labels'), ('spec', 'serviceAccountName')]:
            docs = copy.deepcopy(self.docs)
            docs[1]['spec']['template'][location].pop(key)
            with self.assertRaises(AssertionError): workload_identity.validate(docs, self.config)
    def test_rejects_long_lived_credentials_in_init_containers(self):
        self.docs[1]['spec']['template']['spec']['initContainers'] = [{'name': 'unsafe', 'env': [{'name': 'AZURE_CLIENT_SECRET', 'valueFrom': {'secretKeyRef': {'name': 'old', 'key': 'secret'}}}]}]
        with self.assertRaises(AssertionError): workload_identity.validate(self.docs, self.config)
    def test_rejects_another_identity(self):
        self.docs[0]['metadata']['annotations']['azure.workload.identity/client-id'] = '22222222-2222-2222-2222-222222222222'
        with self.assertRaises(AssertionError): workload_identity.validate(self.docs, self.config)
if __name__ == '__main__': unittest.main()
