#!/usr/bin/env python3
"""Credential-free regressions for the live audit verifier's safety boundaries."""
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('audit', Path(__file__).with_name('verify-security-audit.py'))
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class AuditVerification(unittest.TestCase):
    def test_canary_never_grants_access_and_cleans_up_on_failure(self):
        calls = []
        def run(command, **kwargs):
            calls.append((command, kwargs))
            if 'create' in command and json.loads(kwargs['input'])['kind'] == 'Role':
                raise RuntimeError('simulated lost create response')
            return ''
        with patch.object(audit, 'run', side_effect=run):
            with self.assertRaises(RuntimeError):
                audit.create_canary('/explicit/owner/config')
        objects = [json.loads(k['input']) for _, k in calls if 'input' in k]
        self.assertEqual([o['kind'] for o in objects], ['ConfigMap', 'Role'])
        self.assertEqual(objects[1]['rules'], [])
        self.assertTrue(all(o['metadata']['namespace'] == 'default' for o in objects))
        deletes = [c for c, _ in calls if 'delete' in c]
        self.assertEqual(len(deletes), 2)
        self.assertTrue(all('--ignore-not-found=true' in c for c in deletes))

    def test_unredacted_or_stale_ingestion_fails(self):
        base = dict(Records=4, LastAudit='synthetic', BillableBytes=1000, Bodies=0, QueryStrings=0, StatusMessages=0, UserExtras=0, ExtraAnnotations=0)
        for field in ['Bodies', 'QueryStrings', 'StatusMessages', 'UserExtras', 'ExtraAnnotations']:
            with self.subTest(field=field), patch.object(audit, 'query', return_value=[dict(base, **{field: 1})]):
                with self.assertRaises(AssertionError):
                    audit.verify_events('synthetic-workspace', None)
        with patch.object(audit, 'query', side_effect=[[base], [{'Records': 0}]]):
            with self.assertRaises(AssertionError):
                audit.verify_events('synthetic-workspace', None)

    def test_canary_requires_both_resources_and_cleanup_events(self):
        base = dict(Records=4, LastAudit='synthetic', BillableBytes=1000, Bodies=0, QueryStrings=0, StatusMessages=0, UserExtras=0, ExtraAnnotations=0)
        with patch.object(audit, 'query', side_effect=[[base], [{'Records': 4}], [{'Verb': 'create', 'Resource': 'roles', 'Events': 1}]]):
            with self.assertRaises(AssertionError):
                audit.verify_events('synthetic-workspace', 'security-audit-canary-123456abcdef')


if __name__ == '__main__':
    unittest.main()
