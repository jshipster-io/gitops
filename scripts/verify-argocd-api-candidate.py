#!/usr/bin/env python3
"""Rehearse an Argo API candidate without selecting it for production traffic."""
import argparse
import base64
import copy
import json
import os
import re
import select
import subprocess
import urllib.error
import urllib.request
import uuid


def isolated_pod(deployment, services, image, name):
    template = copy.deepcopy(deployment['spec']['template'])
    labels = template['metadata']['labels']
    labels['app.kubernetes.io/instance'] = name
    # Keep the existing server network-policy selectors, but no Service selector.
    for service in services:
        selector = service['spec'].get('selector', {})
        assert not selector or not all(labels.get(k) == v for k, v in selector.items()), 'Canary would receive Service traffic'
    spec = template['spec']
    spec['restartPolicy'] = 'Never'
    spec['activeDeadlineSeconds'] = 300
    container = next(c for c in spec['containers'] if c['name'] == 'server')
    container['image'] = image
    # Use local HTTP through the owner's TLS-verified kubectl tunnel; no Service
    # selects this Pod. Kubernetes connection certificate checks remain enabled.
    container['args'].append('--insecure')
    return {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': name, 'namespace': 'argocd', 'labels': labels}, 'spec': spec}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--image', required=True)
    parser.add_argument('--expected-version', required=True)
    args = parser.parse_args()
    assert args.run and os.environ.get('KUBECONFIG'), 'Use --run and an explicit trusted owner KUBECONFIG'
    assert re.fullmatch(r'prodacr1234\.azurecr\.io/platform-argocd(?:\:[0-9a-f]{40})?@sha256:[0-9a-f]{64}', args.image)
    k = ['kubectl', '--context', 'jshipster', '--request-timeout=30s', '-n', 'argocd']
    def get(*resource):
        return json.loads(subprocess.check_output(k+['get', *resource, '-o', 'json']))
    name = 'argocd-api-canary-'+uuid.uuid4().hex[:8]
    pod = isolated_pod(get('deployment', 'argocd-server'), get('services')['items'], args.image, name)
    forward = None
    created = False
    try:
        subprocess.run(k+['create', '-f', '-'], input=json.dumps(pod), capture_output=True, text=True, check=True)
        created = True
        subprocess.run(k+['wait', '--for=condition=Ready', 'pod/'+name, '--timeout=180s'], capture_output=True, check=True)
        forward = subprocess.Popen(k+['port-forward', '--address=127.0.0.1', 'pod/'+name, ':8080'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        assert select.select([forward.stdout], [], [], 15)[0], 'Port-forward did not start'
        match = re.search(r'Forwarding from 127\.0\.0\.1:(\d+)', forward.stdout.readline())
        assert match, 'Port-forward failed'
        base = 'http://127.0.0.1:'+match[1]
        def request(path, data=None, token=None):
            headers = {'User-Agent': 'Mozilla/5.0'}
            if token:
                headers['Authorization'] = 'Bearer '+token
            if data is not None:
                headers['Content-Type'] = 'application/json'
                data = json.dumps(data).encode()
            with urllib.request.urlopen(urllib.request.Request(base+path, data=data, headers=headers), timeout=20) as r:
                return r.read()
        assert json.loads(request('/api/version'))['Version'] == args.expected_version, 'REST gateway version rejected or unexpected'
        secret = get('secret', 'argocd-initial-admin-secret')
        password = base64.b64decode(secret['data']['password']).decode()
        token = json.loads(request('/api/v1/session', {'username': 'admin', 'password': password}))['token']
        assert json.loads(request('/api/v1/applications/argocd', token=token))['metadata']['name'] == 'argocd'
        try:
            request('/api/v1/applications/argocd')
        except urllib.error.HTTPError as error:
            assert error.code in (401, 403), 'Unexpected unauthenticated response'
        else:
            raise AssertionError('Unauthenticated protected API access succeeded')
        html = request('/').decode()
        assets = re.findall(r'<script[^>]+src="([^"]+)"', html)
        assert assets and not assets[0].startswith(('http:', 'https:', '//'))
        assert request('/'+assets[0].lstrip('/')), 'UI asset missing'
        print('PASS isolated candidate REST version, authenticated API, unauthenticated denial and embedded UI')
    finally:
        try:
            if forward:
                forward.terminate()
                try:
                    forward.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    forward.kill()
                    forward.wait(timeout=10)
        finally:
            if created:
                subprocess.run(k+['delete', 'pod', name, '--ignore-not-found=true', '--wait=true'], capture_output=True, check=True)


if __name__ == '__main__':
    main()
