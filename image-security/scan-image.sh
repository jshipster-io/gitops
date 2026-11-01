#!/usr/bin/env bash
# Fail closed on scanner errors and fixable CRITICAL findings before promotion.
set -euo pipefail
image=${1:?Pass the exact image digest published by this build}
[[ "$image" == *@sha256:* ]] || { echo 'An immutable image digest is required' >&2; exit 2; }
umask 077
scan_dir=$(mktemp -d)
trap 'rm -rf "$scan_dir"' EXIT
version=0.76.1
archive="trivy_${version}_Linux-64bit.tar.gz"
curl --fail --silent --show-error --location --retry 3 \
  "https://github.com/aquasecurity/trivy/releases/download/v${version}/${archive}" -o "$scan_dir/$archive"
(cd "$scan_dir" && printf '%s  %s\n' 'c7cbe3137fb8a48a17574bede3dd6beb16742d1e9772929940fc90082c39d9c0' "$archive" | sha256sum --check)
tar -xzf "$scan_dir/$archive" -C "$scan_dir" trivy
"$scan_dir/trivy" image --image-src remote --platform linux/amd64 \
  --scanners vuln --timeout 10m --format json --output "$scan_dir/report.json" "$image"
# Never publish raw scanner JSON: it can include image configuration.
python3 - "$scan_dir/report.json" <<'PY'
import collections, json, os, sys
with open(sys.argv[1]) as f:
    report = json.load(f)
findings = [v for r in report.get('Results', []) for v in r.get('Vulnerabilities') or []]
blocking = [v for v in findings if v['Severity'] == 'CRITICAL' and v.get('FixedVersion')]
counts = collections.Counter(v['Severity'] for v in findings)
lines = ['### Image vulnerability scan', '', f"Image: `{report['ArtifactName']}`", '',
         'Package/CVE findings: ' + ', '.join(f'{k}: {counts[k]}' for k in ['CRITICAL','HIGH','MEDIUM','LOW','UNKNOWN']),
         f'Fixable critical findings (promotion gate): {len(blocking)}', '',
         'High and unfixed findings remain a tracked remediation backlog; passing this gate does not mean vulnerability-free.', '',
         '| Severity | CVE | Package | Installed | Fixed |', '|---|---|---|---|---|']
for v in findings:
    if v['Severity'] in ['CRITICAL', 'HIGH']:
        fields = [v['Severity'], v['VulnerabilityID'], v['PkgName'], v['InstalledVersion'], v.get('FixedVersion') or 'Not available']
        lines.append('| ' + ' | '.join(str(x).replace('|', '\\|').replace('\n', ' ') for x in fields) + ' |')
summary = '\n'.join(lines) + '\n'
print(summary)
if os.environ.get('GITHUB_STEP_SUMMARY'):
    with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as f:
        f.write(summary)
if blocking:
    sys.exit('Promotion blocked: fixable CRITICAL vulnerabilities remain')
PY
