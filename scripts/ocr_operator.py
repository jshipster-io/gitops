#!/usr/bin/env python3
"""Use short-lived owner-only AKS federation for OCR v4; never print credentials."""
import argparse
import base64
import json
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
ENDPOINT = 'https://jshipster-docintel.cognitiveservices.azure.com'

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

HTTP = urllib.request.build_opener(NoRedirect())

def token(kubeconfig, context='jshipster'):
    config = json.loads((ROOT / 'azure-auth/resources.json').read_text())['ocr_operator']
    cmd = ['kubectl', '--kubeconfig', str(kubeconfig), '--context', context, '-n', 'azure-operators',
           'create', 'token', 'docintel-operator', '--audience=api://AzureADTokenExchange', '--duration=10m']
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError('Operator TokenRequest denied or unavailable; check owner Entra login and the explicit kubeconfig.')
    assertion = result.stdout.strip()
    claims = json.loads(base64.urlsafe_b64decode(assertion.split('.')[1] + '=='))
    if claims['sub'] != 'system:serviceaccount:azure-operators:docintel-operator' or claims['exp'] - claims['iat'] != 600:
        raise RuntimeError('Unexpected operator token subject or lifetime')
    data = urllib.parse.urlencode({
        'client_id': config['client_id'], 'scope': 'https://cognitiveservices.azure.com/.default',
        'grant_type': 'client_credentials', 'client_assertion': assertion,
        'client_assertion_type': 'urn:ietf:params:oauth:client-assertion-type:jwt-bearer',
    }).encode()
    url = 'https://login.microsoftonline.com/' + config['tenant_id'] + '/oauth2/v2.0/token'
    try:
        with HTTP.open(urllib.request.Request(url, data=data), timeout=30) as response:
            return json.load(response)['access_token']
    except urllib.error.HTTPError as error:
        raise RuntimeError(f'Azure operator token exchange rejected: HTTP {error.code}') from None

def request(bearer, path, data=None, content_type='application/json'):
    # Never attach this token to a service-supplied arbitrary URL.
    if not path.startswith('/') or path.startswith('//'):
        raise ValueError('Expected an OCR-relative API path')
    req = urllib.request.Request(ENDPOINT + path, data=data,
        headers={'Authorization': 'Bearer ' + bearer, 'Content-Type': content_type})
    try:
        with HTTP.open(req, timeout=40) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as error:
        raise RuntimeError(f'OCR request rejected: HTTP {error.code}') from None

def synthetic_pdf():
    text = b'BT /F1 24 Tf 50 150 Td (Azure identity verification) Tj ET'
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>', b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
        b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 400 200] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
        b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
        b'<< /Length ' + str(len(text)).encode() + b' >>\nstream\n' + text + b'\nendstream']
    data = b'%PDF-1.4\n'; offsets = [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(len(data)); data += f'{number} 0 obj\n'.encode() + obj + b'\nendobj\n'
    xref = len(data)
    data += b'xref\n0 6\n0000000000 65535 f \n'
    data += b''.join(f'{offset:010d} 00000 n \n'.encode() for offset in offsets[1:])
    return data + f'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode()

def verify(bearer, analyze=False):
    status, _, _ = request(bearer, '/documentintelligence/documentModels?api-version=2024-11-30')
    assert status == 200
    print('PASS OCR v4 model metadata through isolated operator identity')
    # A positive OCR request with this same token distinguishes missing OpenAI
    # permission from an expired/invalid credential or an unavailable service.
    req = urllib.request.Request(
        'https://jshipster-openai.openai.azure.com/openai/deployments/text-embedding-3-small/embeddings?api-version=2024-02-01',
        data=b'{"input":"synthetic operator scope check"}',
        headers={'Authorization': 'Bearer ' + bearer, 'Content-Type': 'application/json'})
    try:
        with HTTP.open(req, timeout=30) as response:
            denied_status = response.status
            denied_code = None
    except urllib.error.HTTPError as error:
        denied_status = error.code
        denied_code = json.loads(error.read()).get('error', {}).get('code')
    if denied_status not in (401, 403) or denied_code != 'PermissionDenied':
        raise RuntimeError(f'Expected unrelated OpenAI permission denial, got HTTP {denied_status}')
    print('PASS OCR operator denied unrelated OpenAI access: HTTP', denied_status)
    if not analyze:
        return
    status, headers, _ = request(bearer,
        '/documentintelligence/documentModels/prebuilt-read:analyze?api-version=2024-11-30',
        synthetic_pdf(), 'application/pdf')
    assert status == 202
    location = next(v for k, v in headers.items() if k.lower() == 'operation-location')
    assert location.startswith(ENDPOINT + '/documentintelligence/'), 'Unexpected result origin'
    path = location[len(ENDPOINT):]
    for attempt in range(20):
        _, _, body = request(bearer, path)
        result = json.loads(body)
        if result['status'] == 'succeeded':
            assert 'Azure identity verification' in result['analyzeResult']['content']
            print('PASS OCR v4 recognized the synthetic page through isolated operator identity')
            return
        if result['status'] in ('failed', 'canceled'):
            raise RuntimeError('Synthetic OCR operation failed')
        time.sleep(2)
    raise RuntimeError('Synthetic OCR verification timed out')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kubeconfig', required=True)
    parser.add_argument('--context', default='jshipster')
    parser.add_argument('--analyze-synthetic', action='store_true', help='Also recognize one generated test page; no user documents are read')
    args = parser.parse_args()
    try:
        verify(token(args.kubeconfig, args.context), args.analyze_synthetic)
    except RuntimeError as error:
        raise SystemExit(str(error))
