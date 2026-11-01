#!/usr/bin/env python3
"""Publish allowlisted vulnerability fields; never publish raw image metadata."""
import argparse
import collections
import hashlib
import json
from pathlib import Path


def summarize(image, metadata, report):
    findings = []
    for result in report.get('Results', []):
        for item in result.get('Vulnerabilities') or []:
            findings.append({key: item.get(key, '') for key in (
                'VulnerabilityID', 'PkgName', 'InstalledVersion', 'FixedVersion',
                'Severity', 'Status', 'PrimaryURL')})
    return {
        'image': image, **metadata, 'status': 'scanned',
        'imageID': report.get('Metadata', {}).get('ImageID'),
        'repoDigests': report.get('Metadata', {}).get('RepoDigests', []),
        'os': report.get('Metadata', {}).get('OS', {}),
        'counts': dict(collections.Counter(v['Severity'] for v in findings)),
        'fixableCritical': sum(v['Severity'] == 'CRITICAL' and bool(v['FixedVersion']) for v in findings),
        'highCriticalFindings': [v for v in findings if v['Severity'] in ('CRITICAL', 'HIGH')],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reports', type=Path, required=True)
    parser.add_argument('--targets', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--identity-map', type=Path)
    args = parser.parse_args()
    targets = json.loads(args.targets.read_text())
    identities = json.loads(args.identity_map.read_text()) if args.identity_map else {}
    results = []
    for image, metadata in sorted(targets.items()):
        identity = identities.get(image, {})
        scanned_reference = identity.get('reportReference', image)
        report_file = args.reports / (hashlib.sha256(scanned_reference.encode()).hexdigest()[:20] + '.json')
        try:
            report = json.loads(report_file.read_text())
            if identity and report.get('Metadata', {}).get('ImageID') != identity['expectedImageID']:
                raise ValueError('Container image config digest mismatch')
            if 'Results' not in report:
                raise ValueError('Missing scanner results')
            results.append(summarize(image, {**metadata, 'scannedReference': scanned_reference, **({'identityVerification': identity} if identity else {})}, report))
        except (OSError, ValueError):
            results.append({'image': image, **metadata, 'status': 'unverified'})
    args.output.write_text(json.dumps(results, indent=2) + '\n')
    print(f"{sum(r['status'] == 'scanned' for r in results)}/{len(results)} references scanned")


if __name__ == '__main__':
    main()
