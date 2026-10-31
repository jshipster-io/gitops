# Security audit logging

The shared pipeline is managed by the sibling Terraform repository:
`security_audit.tf`, `security-audit/*.kql`, `SECURITY_AUDIT.md` and
`tests/security_audit.tftest.hcl`. No application manifest, rollout, image,
network policy or access grant is changed by this feature.

## Contract

- `jshipster-security-audit` / `AKSAuditAdmin`: 30-day retention, including total
  retention, immediate 30-day purge, Analytics tier and 0.1 GB/day quota safeguard.
- Export only `kube-audit-admin`, once, with a resource-specific destination.
- Attach and propagate the workspace transformation **before** export. Store
  metadata only: no request/response bodies, URL parameters, status messages,
  webhook patch payloads or user extra fields. Failed administrative requests
  survive filtering; successful routine lease/event/status traffic does not.
- Query through Entra with explicit workspace/subscription permissions. Shared
  key and resource-only workspace access are disabled. Apps/CI receive no new
  logging privileges, credentials or agents.
- Three stateful log alerts run every 15 minutes, without per-actor/dimension
  billing expansion: sensitive recorded operations, five administrative denials
  per actor in 30 minutes, and collection health/quota warnings.
- Five native Activity Log alerts cover Azure authorization changes, audit-control
  changes, and AKS admin credentials/control changes/deletion. Native Activity Log
  keeps its independent 90-day retention; no duplicate paid export is added.
- Notify the existing budget email recipient using common alert schema. The $15
  monthly resource-filtered budget warns at actual 50/80/100% and forecast 100%.
  No human approval step is added to deployment or alert handling.

Coverage is deliberately limited: administrative logs omit GET/list, so they are
not a complete record of secret reads, sign-ins or GET-based WebSocket interactive
access. Intended privileged owner/Argo changes can alert. Correlate with authorized
changes rather than excluding whole identities from security monitoring.

Daily quotas can overshoot and stop collection until the next reset; budgets only
notify, and filtering can incur transformation-processing charges. The 80 MB
rolling-day warning is approximate, not the Azure quota-reset accounting clock.
Do not automatically raise limits or weaken filters. Investigate volume, native
Activity Log and collection health before deciding how to restore coverage.

## Verification

```sh
python3 scripts/test-security-audit.py
python3 scripts/verify-security-audit.py
python3 scripts/verify-security-audit.py --create-canary --kubeconfig <explicit-owner-config>
python3 scripts/verify-security-audit.py --canary <returned-name>
```

The default verifier is read-only. Explicit canary mode creates/deletes a fake-data
ConfigMap and an empty, unbound Role in `default`; it grants no access and runs no
business or backup jobs. The Role event can fire the intended owner security alert.
Allow ingestion time, then verify both resources' create/delete events. The query
returns only metadata counts and rejects non-redacted fields or stale ingestion.

For KQL changes, run the Terraform repository's seven synthetic positive/negative
fixtures in Azure's real query engine:

```sh
python3 scripts/security-audit-query-tests.py --workspace-id <workspace-guid>
```

Credential-free GitOps CI tests verifier safety, then automatically promotes the
validated commit to protected `production`. Terraform CI validates formatting,
configuration and the bounded logging/alert mock plan. No Azure credential or
human approval is required in either validation workflow.

Separately verify an actual fired alert and Azure action-group delivery status.
Configuration and fixture results alone do not prove live alert delivery; Azure
send success does not prove inbox receipt. Recheck all Argo applications, public
health endpoints, owner Entra API access and Tailscale SSH on both Macs.

## First rollout

Provision workspace, built-in table retention, DCR and the narrow workspace link
first. Allow the documented transformation propagation interval (up to 60 minutes)
before enabling production diagnostics. Confirm real redacted ingestion before
enabling scheduled log alerts, avoiding an initial empty-workspace gap alarm.
Review a logging-resource-only Terraform plan; preserve unrelated changes.
Never enable raw audit export simply to initialize a table or troubleshoot a rule.

The [workspace](https://portal.azure.com/#resource/subscriptions/b76ecd16-669b-4ca9-b797-b7786eb1b334/resourceGroups/prod-rg/providers/Microsoft.OperationalInsights/workspaces/jshipster-security-audit/overview)
is owner-accessible through Entra. See Terraform `SECURITY_AUDIT.md` for the full
rule inventory and Microsoft documentation on costs, propagation and coverage.
