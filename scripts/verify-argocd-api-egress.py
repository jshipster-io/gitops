#!/usr/bin/env python3
"""Fail before Helm hooks if the narrow API allowance no longer matches AKS."""
import ipaddress
import json
import os
import subprocess
assert os.environ.get('KUBECONFIG'), 'Set an explicit owner KUBECONFIG'
k=['kubectl','--context','jshipster','--request-timeout=30s']
def get(*args):return json.loads(subprocess.check_output(k+list(args)+['-o','json']))
p=get('get','networkpolicy','redis-secret-init-to-api','-n','argocd')['spec']
assert p['podSelector']=={'matchLabels':{'app.kubernetes.io/name':'argocd-redis-secret-init'}}
assert p['policyTypes']==['Egress'] and len(p['egress'])==1
rule=p['egress'][0];assert rule['ports']==[{'port':443,'protocol':'TCP'}]
ranges=[ipaddress.ip_network(x['ipBlock']['cidr']) for x in rule['to']]
assert all(n.prefixlen==n.max_prefixlen for n in ranges), 'Keep API destinations individually scoped'
service=get('get','service','kubernetes','-n','default')
slices=get('get','endpointslices','-n','default','-l','kubernetes.io/service-name=kubernetes')['items']
addresses={a for s in slices for e in s['endpoints'] for a in e['addresses']}
assert addresses, 'No Kubernetes API EndpointSlice addresses found'
addresses.update(service['spec'].get('clusterIPs',[service['spec']['clusterIP']]))
assert all(any(ipaddress.ip_address(a) in n for n in ranges) for a in addresses), 'AKS API addresses changed; update the scoped GitOps policy before Helm upgrade'
print('PASS live Helm-hook API allowance matches Service and EndpointSlice addresses')
