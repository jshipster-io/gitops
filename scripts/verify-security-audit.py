#!/usr/bin/env python3
"""Read back security logging controls and metadata-only ingestion evidence.

Default mode is read-only. --create-canary creates and deletes a synthetic
ConfigMap and an empty unbound Role, then exits; it grants no access, restarts no
workloads and sends no business notifications. Its audit event can fire the
configured owner security alert. --canary NAME verifies its ingested metadata.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import uuid

ROOT = Path(__file__).resolve().parents[1]
SUB = json.loads((ROOT / 'azure-auth/resources.json').read_text())['subscription']
RG = f'/subscriptions/{SUB}/resourceGroups/prod-rg'
WORKSPACE = RG + '/providers/Microsoft.OperationalInsights/workspaces/jshipster-security-audit'
ACTION = RG + '/providers/Microsoft.Insights/actionGroups/jshipster-security-owner'
DCR = RG + '/providers/Microsoft.Insights/dataCollectionRules/jshipster-security-redaction'
AKS = RG + '/providers/Microsoft.ContainerService/managedClusters/prod-aks'


def run(command, **kwargs):
    result = subprocess.run(command, capture_output=True, text=True, timeout=120, **kwargs)
    if result.returncode:
        raise RuntimeError('Command failed: ' + ' '.join(command[:3]) + '; inspect authentication/resource access without printing credentials')
    return result.stdout


def arm(resource, version):
    return json.loads(run(['az', 'rest', '--method', 'get', '--url', resource + '?api-version=' + version, '--subscription', SUB, '-o', 'json']))


def query(workspace_id, kql):
    data = json.loads(run(['az', 'rest', '--method', 'post', '--url', f'https://api.loganalytics.azure.com/v1/workspaces/{workspace_id}/query', '--resource', 'https://api.loganalytics.io/', '--body', json.dumps({'query': kql}), '-o', 'json']))
    assert 'error' not in data, 'Audit query failed or returned partial results'
    table = data['tables'][0]
    return [dict(zip([c['name'] for c in table['columns']], row)) for row in table['rows']]


def create_canary(kubeconfig):
    kube = ['kubectl', '--kubeconfig', kubeconfig, '--context', 'jshipster', '-n', 'default']
    name = 'security-audit-canary-' + uuid.uuid4().hex[:12]
    objects = [
        {'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': name, 'namespace': 'default'}, 'data': {'synthetic': 'NOT_A_REAL_SECRET_' + uuid.uuid4().hex}},
        {'apiVersion': 'rbac.authorization.k8s.io/v1', 'kind': 'Role', 'metadata': {'name': name, 'namespace': 'default'}, 'rules': []},
    ]
    created = []
    try:
        for obj in objects:
            created.append(obj['kind'].lower())
            run(kube + ['create', '-f', '-'], input=json.dumps(obj))
    finally:
        failures = []
        for kind in reversed(created):
            try:
                run(kube + ['delete', kind, name, '--wait=true', '--ignore-not-found=true'])
            except RuntimeError:
                failures.append(kind)
        if failures:
            raise RuntimeError('Canary cleanup required: ' + name + ' ' + ','.join(failures))
    print('Canary created and removed:', name)
    print('After ingestion, run this verifier with --canary ' + name)


def verify_config():
    workspace = arm(WORKSPACE, '2022-10-01')['properties']
    assert workspace['retentionInDays'] == 30
    assert workspace['workspaceCapping']['dailyQuotaGb'] == 0.1
    assert workspace['features']['disableLocalAuth'] is True
    assert workspace['features']['enableLogAccessUsingOnlyResourcePermissions'] is False
    assert workspace['defaultDataCollectionRuleResourceId'].lower() == DCR.lower()
    table = arm(WORKSPACE + '/tables/AKSAuditAdmin', '2022-10-01')['properties']
    assert table['plan'] == 'Analytics' and table['retentionInDays'] == 30 and table['totalRetentionInDays'] == 30
    dcr = arm(DCR, '2023-03-11')
    assert dcr['kind'] == 'WorkspaceTransforms'
    flows = dcr['properties']['dataFlows']
    assert len(flows) == 1 and flows[0]['streams'] == ['Microsoft-Table-AKSAuditAdmin']
    transform = flows[0]['transformKql']
    for clause in ['RequestObject = parse_json("null")', 'ResponseObject = parse_json("null")', 'RequestUri = tostring(split(RequestUri, "?")[0])', 'ResponseStatus = pack("code"', 'Annotations = pack("authorization.k8s.io/decision"', 'User = pack("username"']:
        assert clause in transform, 'Missing metadata-redaction safeguard'
    diag = arm(AKS + '/providers/Microsoft.Insights/diagnosticSettings/security-admin-metadata', '2021-05-01-preview')['properties']
    assert diag['workspaceId'].lower() == WORKSPACE.lower() and diag['logAnalyticsDestinationType'] == 'Dedicated'
    assert [x['category'] for x in diag['logs'] if x.get('enabled')] == ['kube-audit-admin']
    assert not any(x.get('enabled') for x in diag.get('metrics', []))
    group = arm(ACTION, '2021-09-01')['properties']
    assert group['enabled'] and group['emailReceivers']
    assert all(x['useCommonAlertSchema'] and x.get('status', 'Enabled') == 'Enabled' for x in group['emailReceivers'])
    print('PASS retention, quota, Entra-only workspace access, metadata redaction and owner alert destination')
    for name in ['sensitive-operations', 'repeated-denials', 'collection-health']:
        alert = arm(RG + '/providers/Microsoft.Insights/scheduledQueryRules/security-' + name, '2023-12-01')['properties']
        assert alert['enabled'] and alert['evaluationFrequency'] == 'PT15M' and alert['autoMitigate']
        assert not alert.get('skipQueryValidation', False)
        assert [s.lower() for s in alert['scopes']] == [WORKSPACE.lower()]
        assert [s.lower() for s in alert['actions']['actionGroups']] == [ACTION.lower()]
        assert not any(c.get('dimensions') for c in alert['criteria']['allOf'])
    for name in ['azure-privilege-change', 'audit-control-change', 'aks-admin-credential', 'aks-control-change', 'aks-delete']:
        alert = arm(RG + '/providers/Microsoft.Insights/activityLogAlerts/security-' + name, '2020-10-01')['properties']
        assert alert['enabled'] and alert['actions']['actionGroups'][0]['actionGroupId'].lower() == ACTION.lower()
    budget = arm(RG + '/providers/Microsoft.Consumption/budgets/security-audit-monthly', '2024-08-01')['properties']
    assert budget['amount'] == 15 and budget['timeGrain'] == 'Monthly' and len(budget['notifications']) == 4
    print('PASS three stateful 15-minute log alerts, five activity alerts and $15 monthly budget notifications')
    return workspace['customerId']


def verify_events(workspace_id, canary):
    row = query(workspace_id, '''AKSAuditAdmin
| where TimeGenerated > ago(24h)
| summarize Records=count(), LastAudit=max(TimeGenerated), BillableBytes=sumif(_BilledSize,_IsBillable == "true"), Bodies=countif(isnotnull(RequestObject) or isnotnull(ResponseObject)), QueryStrings=countif(RequestUri contains "?"), StatusMessages=countif(isnotnull(ResponseStatus.message)), UserExtras=countif(isnotnull(User.extra)), ExtraAnnotations=countif(array_length(bag_keys(Annotations)) > 1)
''')[0]
    assert row['Records'] > 0, 'No audit events have arrived yet'
    assert all(row[k] == 0 for k in ['Bodies', 'QueryStrings', 'StatusMessages', 'UserExtras', 'ExtraAnnotations']), 'Unexpected sensitive audit fields remain; inspect without printing their contents'
    fresh = query(workspace_id, 'AKSAuditAdmin | where TimeGenerated > ago(1h) | summarize Records=count()')[0]['Records']
    assert fresh > 0, 'No audit events within the last hour'
    print('PASS live metadata-only audit ingestion:', json.dumps({k: row[k] for k in ['Records', 'LastAudit', 'BillableBytes']}))
    if canary:
        assert re.fullmatch(r'security-audit-canary-[0-9a-f]{12}', canary), 'Invalid canary name'
        rows = query(workspace_id, f'''AKSAuditAdmin
| where TimeGenerated > ago(24h) and tostring(ObjectRef.name) == "{canary}"
| summarize Events=dcount(AuditId) by Verb, Resource=tostring(ObjectRef.resource)
''')
        observed = {(r['Verb'], r['Resource']) for r in rows}
        expected = {('create', 'configmaps'), ('delete', 'configmaps'), ('create', 'roles'), ('delete', 'roles')}
        assert expected <= observed, 'Synthetic create/delete audit metadata has not fully arrived'
        print('PASS synthetic ConfigMap and empty Role create/delete metadata; canary objects removed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--create-canary', action='store_true')
    parser.add_argument('--kubeconfig')
    parser.add_argument('--canary')
    args = parser.parse_args()
    if args.create_canary:
        assert args.kubeconfig, 'Canary creation requires an explicit owner kubeconfig'
        create_canary(args.kubeconfig)
        return
    verify_events(verify_config(), args.canary)


if __name__ == '__main__':
    main()
