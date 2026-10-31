"""Fail closed if GitOps weakens the reviewed, owner-only OCR token broker."""
NS = 'azure-operators'
OWNER = '6544d2d9-52ad-4005-bd9a-6bd856b53900'
SA = 'docintel-operator'

def validate(docs):
    objects = {(d['kind'], d['metadata']['name']): d for d in docs
               if d.get('metadata', {}).get('namespace') == NS or
               d.get('metadata', {}).get('name', '').startswith('azure-operators')}
    def get(kind, name):
        assert (kind, name) in objects, f'Missing operator isolation: {kind}/{name}'
        return objects[kind, name]
    get('Namespace', NS)
    assert get('ServiceAccount', SA).get('automountServiceAccountToken') is False
    quota = get('ResourceQuota', 'no-workloads-or-secrets')['spec']['hard']
    assert quota.get('pods') == '0' and quota.get('secrets') == '0'
    policy = get('NetworkPolicy', 'deny-all')['spec']
    assert policy == {'podSelector': {}, 'policyTypes': ['Ingress', 'Egress'], 'ingress': [], 'egress': []}
    for d in docs:
        if d.get('metadata', {}).get('namespace') != NS:
            continue
        assert d['kind'] not in ('Pod', 'Deployment', 'StatefulSet', 'DaemonSet', 'Job', 'CronJob', 'Secret')
        if d['kind'] == 'RoleBinding':
            assert d['subjects'] == [{'kind': 'User', 'apiGroup': 'rbac.authorization.k8s.io', 'name': OWNER}]
    role = get('Role', 'request-docintel-token')
    assert role['rules'] == [{'apiGroups': [''], 'resources': ['serviceaccounts/token'], 'resourceNames': [SA], 'verbs': ['create']}]
    binding = get('RoleBinding', 'owner-docintel-token')
    assert binding['roleRef'] == {'kind': 'Role', 'apiGroup': 'rbac.authorization.k8s.io', 'name': 'request-docintel-token'}
    expected = {
        'owner-token-only': (['serviceaccounts/token'], ['CREATE'], [
            f"request.userInfo.username == '{OWNER}' && request.name == '{SA}'",
            "object.spec.audiences == ['api://AzureADTokenExchange'] && has(object.spec.expirationSeconds) && object.spec.expirationSeconds == 600"]),
        'no-pods-or-secrets': (['pods', 'secrets'], ['CREATE', 'UPDATE'], ['false']),
    }
    for suffix, (resources, operations, expressions) in expected.items():
        name = NS + '-' + suffix
        spec = get('ValidatingAdmissionPolicy', name)['spec']
        assert spec['failurePolicy'] == 'Fail'
        assert spec['matchConstraints'] == {'resourceRules': [{'apiGroups': [''], 'apiVersions': ['v1'], 'operations': operations, 'resources': resources}]}
        assert spec['matchConditions'] == [{'name': 'isolated-namespace', 'expression': "request.namespace == 'azure-operators'"}]
        assert [v['expression'] for v in spec['validations']] == expressions
        assert get('ValidatingAdmissionPolicyBinding', name)['spec'] == {'policyName': name, 'validationActions': ['Deny']}
    print('Validated isolated owner-only OCR federation controls')
