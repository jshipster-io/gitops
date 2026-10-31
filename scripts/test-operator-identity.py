#!/usr/bin/env python3
import copy
from pathlib import Path
import unittest
import yaml
import operator_identity

ROOT = Path(__file__).resolve().parents[1]
class IsolationTests(unittest.TestCase):
    def setUp(self):
        self.docs = []
        for name in ('isolation.yaml', 'admission.yaml'):
            self.docs.extend(yaml.safe_load_all((ROOT / 'azure-operators' / name).read_text()))
        for d in self.docs:
            d['metadata'].setdefault('namespace', 'azure-operators')
    def obj(self, kind, name=None):
        return next(d for d in self.docs if d['kind'] == kind and (name is None or d['metadata']['name'] == name))
    def rejected(self):
        with self.assertRaises(AssertionError): operator_identity.validate(self.docs)
    def test_approved_isolation(self): operator_identity.validate(self.docs)
    def test_allowing_pods_is_rejected(self):
        self.obj('ResourceQuota')['spec']['hard']['pods'] = '1'; self.rejected()
    def test_audit_only_policy_is_rejected(self):
        self.obj('ValidatingAdmissionPolicyBinding')['spec']['validationActions'] = ['Audit']; self.rejected()
    def test_broad_token_grant_is_rejected(self):
        self.obj('Role')['rules'][0].pop('resourceNames'); self.rejected()
    def test_other_subject_is_rejected(self):
        self.obj('RoleBinding')['subjects'][0]['name'] = 'another-user'; self.rejected()
    def test_broader_token_audience_is_rejected(self):
        self.obj('ValidatingAdmissionPolicy')['spec']['validations'][1]['expression'] = 'true'; self.rejected()
    def test_label_based_policy_bypass_is_rejected(self):
        self.obj('ValidatingAdmissionPolicy')['spec']['matchConditions'] = []; self.rejected()
    def test_legacy_token_secret_is_rejected(self):
        self.docs.append({'kind':'Secret','metadata':{'name':'legacy-token','namespace':'azure-operators'},'type':'kubernetes.io/service-account-token'}); self.rejected()
if __name__ == '__main__': unittest.main()
