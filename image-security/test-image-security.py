#!/usr/bin/env python3
"""Exercise promotion and report-privacy boundaries without pulling images."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('audit', ROOT / 'summarize-audit.py')
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)
PARSER = (ROOT / 'scan-image.sh').read_text().split("<<'PY'\n", 1)[1].rsplit('\nPY', 1)[0]


class ImageSecurityTest(unittest.TestCase):
    def test_gate_and_summary_privacy(self):
        for severity, fixed, expected in [('CRITICAL', '2', 1), ('CRITICAL', '', 0), ('HIGH', '2', 0)]:
            with self.subTest(severity=severity, fixed=fixed), tempfile.TemporaryDirectory() as temp:
                report = {'ArtifactName': 'example@sha256:abc',
                          'Metadata': {'ImageConfig': {'Env': ['TOKEN=must-not-leak']}},
                          'Results': [{'Vulnerabilities': [{'Severity': severity, 'FixedVersion': fixed,
                                       'VulnerabilityID': 'CVE-test', 'PkgName': 'package', 'InstalledVersion': '1'}]}]}
                path = Path(temp) / 'report.json'
                summary = Path(temp) / 'summary.md'
                path.write_text(json.dumps(report))
                result = subprocess.run(['python3', '-c', PARSER, str(path)], capture_output=True, text=True,
                                        env={**os.environ, 'GITHUB_STEP_SUMMARY': str(summary)})
                self.assertEqual(result.returncode, expected, result.stderr)
                self.assertNotIn('must-not-leak', result.stdout + summary.read_text())
                self.assertIn('CVE-test', summary.read_text())
                sanitized = AUDIT.summarize('example', {}, report)
                self.assertNotIn('must-not-leak', json.dumps(sanitized))
                self.assertEqual(sanitized['fixableCritical'], int(expected != 0))

    def test_mutable_tag_rejected_before_network(self):
        result = subprocess.run(['bash', str(ROOT / 'scan-image.sh'), 'example:latest'], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('immutable image digest', result.stderr)

    def test_invalid_report_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'report.json'
            path.write_text('not JSON')
            result = subprocess.run(['python3', '-c', PARSER, str(path)], capture_output=True)
            self.assertNotEqual(result.returncode, 0)


if __name__ == '__main__':
    unittest.main()
