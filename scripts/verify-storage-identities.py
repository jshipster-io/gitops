#!/usr/bin/env python3
"""Verify explicit storage identities with synthetic blobs; never dump credentials or app data."""
import argparse
import base64
import json
from pathlib import Path
import subprocess
import urllib.error
import urllib.parse
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / 'azure-auth/resources.json').read_text())
ACCOUNT = 'jshipsterprod410479'
BASE = 'https://' + ACCOUNT + '.blob.core.windows.net/'
CONSUMERS = [
    ('hasadnaa', 'hasadnaa', 'hasadnaa-documents', True),
    ('loki', 'loki', 'loki-logs', True),
    ('pg-backups', 'pg-backups', 'pg-backups', True),
    ('postgres', 'postgres-backup-recovery', 'pg-backups', True),
    ('jshipster', 'azure-backup-reporter', 'pg-backups', False),
    ('jshipster', 'uptime-check', 'pg-backups', False),
]
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs): return None
HTTP = urllib.request.build_opener(NoRedirect())

def claims(token):
    part = token.split('.')[1]
    return json.loads(base64.urlsafe_b64decode(part + '=' * (-len(part) % 4)))

def az(*args):
    return json.loads(subprocess.check_output(['az', *args, '--subscription', CONFIG['subscription'], '-o', 'json']))

def blob(token, method, path, body=None):
    req = urllib.request.Request(BASE + path, method=method, data=body,
        headers={'Authorization': 'Bearer ' + token, 'x-ms-version': '2023-11-03', 'x-ms-blob-type': 'BlockBlob'})
    try:
        with HTTP.open(req, timeout=30) as response: return response.status, response.read()
    except urllib.error.HTTPError as error: return error.code, b''

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kubeconfig', required=True)
    parser.add_argument('--allow-legacy-grant', action='store_true', help='Pre-retirement baseline only; never use for a passing post-cutover audit')
    args = parser.parse_args()
    kube = ['kubectl', '--kubeconfig', args.kubeconfig, '--context', 'jshipster']
    aks = az('aks', 'show', '-g', 'prod-rg', '-n', 'prod-aks')
    node = aks['identityProfile']['kubeletidentity']['objectId']
    roles = [r for r in az('role', 'assignment', 'list', '--all') if r['principalId'] == node]
    acr = '/subscriptions/' + CONFIG['subscription'] + '/resourceGroups/prod-rg/providers/Microsoft.ContainerRegistry/registries/prodacr1234'
    allowed = [('AcrPull', acr.lower())]
    if args.allow_legacy_grant:
        allowed.append(('Storage Blob Data Contributor', ('/subscriptions/' + CONFIG['subscription'] + '/resourceGroups/prod-rg/providers/Microsoft.Storage/storageAccounts/' + ACCOUNT).lower()))
    actual = sorted((r['roleDefinitionName'], r['scope'].lower()) for r in roles)
    assert actual == sorted(allowed), 'Unexpected kubelet role grants; review Azure RBAC'
    print('PASS kubelet role inventory:', 'PRE-RETIREMENT baseline' if args.allow_legacy_grant else 'registry-scoped AcrPull only', flush=True)
    for ns, sa, container, writer in CONSUMERS:
        account = json.loads(subprocess.check_output(kube + ['-n', ns, 'get', 'serviceaccount', sa, '-o', 'json']))
        annotations = account['metadata']['annotations']
        result = subprocess.run(kube + ['-n', ns, 'create', 'token', sa, '--audience=api://AzureADTokenExchange', '--duration=10m'], capture_output=True, text=True)
        assert result.returncode == 0, f'{ns}/{sa}: TokenRequest failed'
        assertion = result.stdout.strip()
        assert claims(assertion)['sub'] == f'system:serviceaccount:{ns}:{sa}'
        form = urllib.parse.urlencode({'client_id': annotations['azure.workload.identity/client-id'],
            'scope': 'https://storage.azure.com/.default', 'grant_type': 'client_credentials',
            'client_assertion': assertion, 'client_assertion_type': 'urn:ietf:params:oauth:client-assertion-type:jwt-bearer'}).encode()
        endpoint = 'https://login.microsoftonline.com/' + annotations['azure.workload.identity/tenant-id'] + '/oauth2/v2.0/token'
        with HTTP.open(urllib.request.Request(endpoint, data=form), timeout=30) as response:
            token = json.load(response)['access_token']
        assert claims(token)['oid'] != node, 'Consumer unexpectedly uses the kubelet principal'
        status, _ = blob(token, 'GET', container + '?restype=container')
        assert status == 200, f'{ns}/{sa}: own container metadata HTTP {status}'
        path = container + '/_identity-verification/kubelet-retirement-' + str(uuid.uuid4())
        data = b'synthetic workload identity verification'
        status, _ = blob(token, 'PUT', path, data)
        if status == 201:
            try:
                code, content = blob(token, 'GET', path)
                assert code == 200 and content == data, 'Synthetic blob readback failed'
            finally:
                code, _ = blob(token, 'DELETE', path)
                assert code == 202, 'Synthetic blob cleanup failed: ' + path
        assert status == (201 if writer else 403), f'{ns}/{sa}: unexpected write permissions HTTP {status}'
        other = 'loki-logs' if container != 'loki-logs' else 'pg-backups'
        code, _ = blob(token, 'GET', other + '?restype=container')
        assert code == 403, f'{ns}/{sa}: unexpected access to unrelated container'
        print('PASS', ns + '/' + sa, 'write/read/delete' if writer else 'read/write-denied', 'and unrelated-container denial', flush=True)

if __name__ == '__main__': main()
