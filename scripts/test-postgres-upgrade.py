#!/usr/bin/env python3
"""Ensure migration acceptance rejects data and access regressions."""
import contextlib
import copy
import importlib.util
import io
import json
import pathlib
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('verify', pathlib.Path(__file__).with_name('verify-postgres-upgrade.py'))
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)


class AcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.source = {'globals': [{'role': 'app', 'password_hash': 'original', 'super': False}],
                       'databases': {'app': [
                           {'kind': 'extension', 'name': 'vector', 'version': '0.8.6'},
                           {'kind': 'table_data', 'schema': 'public', 'table': 'items', 'count': 3, 'fingerprint': 'original'},
                           {'kind': 'sequence', 'name': 'items_id_seq', 'last_value': 9, 'is_called': True},
                           {'kind': 'database', 'name': 'app', 'acl': 'owner-only'}]}}
        self.target = copy.deepcopy(self.source)
        self.target['databases']['app'][0]['version'] = '0.8.7'

    def check(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target = (pathlib.Path(directory) / n for n in ('source.json', 'target.json'))
            source.write_text(json.dumps(self.source)); target.write_text(json.dumps(self.target))
            with contextlib.redirect_stdout(io.StringIO()):
                verify.compare(source, target)

    def test_approved_extension_upgrade(self):
        self.check()

    def test_same_row_count_different_data_fails(self):
        self.target['databases']['app'][1]['fingerprint'] = 'corrupted'
        with self.assertRaises(SystemExit): self.check()

    def test_sequence_regression_fails(self):
        self.target['databases']['app'][2]['last_value'] = 3
        with self.assertRaises(SystemExit): self.check()

    def test_credentials_and_privileges_cannot_change(self):
        for field, value in [('password_hash', 'rotated'), ('super', True)]:
            with self.subTest(field=field):
                self.target = copy.deepcopy(self.source)
                self.target['globals'][0][field] = value
                with self.assertRaises(SystemExit): self.check()

    def test_database_acl_cannot_disappear(self):
        self.target['databases']['app'][3]['acl'] = None
        with self.assertRaises(SystemExit): self.check()

    def test_database_cannot_disappear(self):
        del self.target['databases']['app']
        with self.assertRaises(SystemExit): self.check()

    def test_unapproved_extension_version_fails(self):
        self.target['databases']['app'][0]['version'] = '0.9.0'
        with self.assertRaises(AssertionError): self.check()


if __name__ == '__main__': unittest.main()
