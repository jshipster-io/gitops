# Azure federation

Implemented on 2026-10-31. Terraform owns identities, federation and Azure role assignments in `terraform/federated_access.tf`. Application CI owns image promotion; Argo CD deploys only the automatically validated `production` branch.

## GitHub Actions

All 18 image-publishing repositories use separate managed identities and SHA-pinned `azure/login`, followed by `az acr login`. Only trusted main-branch publishing jobs receive `id-token: write`; pull requests do not receive Azure publishing access. No human approval environment is required.

The exact GitHub subject includes immutable organization and repository IDs:

```
repo:jshipster-io@350481394/<repository>@<repository-id>:ref:refs/heads/main
```

Do not substitute the older name-only subject. Public organization variables `AZURE_TENANT_ID` and `AZURE_SUBSCRIPTION_ID` have selected-repository grants; each repository has its own `AZURE_CLIENT_ID` variable. ACR permissions are registry-scoped `AcrPush`, not repository-level ABAC permissions. The current registry permission mode preserves the AKS kubelet's existing pull access.

ACR admin authentication is disabled. The organization secrets `ACR_USERNAME` and `ACR_PASSWORD` were deleted after every publishing workflow successfully executed its Azure login and registry login steps. No repository-level copies were found in these repositories.

Migrated repositories: ANPR-Shikmim, blutag-app, blutag-findmy, blutag-pointer-push, blutag-website, dirtbike-specialist, drc, gen-rag, hasadnaa, ids, johnson, mashov-mcp, multi-whatsapp, padel-booking, slack-notifications, tivtaam-mcp, trips and webtop-mcp. IDS remains intentionally offline; publishing a new image does not authorize starting it.

## AKS permissions

The AKS OIDC issuer trusts exact namespace/service-account subjects, with audience `api://AzureADTokenExchange`. Service accounts carry the identity annotation; pod templates carry `azure.workload.identity/use: "true"`. Kubernetes API token mounting remains disabled unless the workload separately needs it.

| Identity | Permissions |
| --- | --- |
| hasadnaa | Blob Data Contributor on hasadnaa-documents; Storage Blob Delegator on the storage account for user-delegation SAS |
| loki | Blob Data Contributor on loki-logs |
| pg-backups | Blob Data Contributor on pg-backups |
| azure-billing | Cost Management Reader on the subscription |
| backup-report | Blob Data Reader on pg-backups |
| slack-notifications | Cost Management Reader plus Blob Data Reader on pg-backups |
| blutag-openai | Cognitive Services OpenAI User on its OpenAI account; custom email-sending role on its ACS resource |
| postgres-backup-reader | Reserved Blob Data Reader identity for pg-backups; not an active workload in this migration |

The ACS custom role includes the resource read and send-required write actions, excluding key retrieval, deletion and permission management. The PostgreSQL upgrade separately owns its recovery-writer federation in `postgres_backup_identity.tf`.

Hasadnaa uses user-delegation SAS instead of storage-key signatures. Blutag uses Entra bearer tokens for OpenAI and ACS. Slack billing and backup reporting use token credentials. Loki uses federated token authentication. In the Go applications, a projected workload token selects explicit workload identity credentials; authentication errors do not fall back to a legacy key. Local development compatibility remains available outside workload identity.

## Automatic validation

`workload-identity/profiles.yaml` records 14 workload bindings from this migration. `scripts/workload_identity.py` verifies the rendered service accounts, identity annotations, pod labels, forbidden credential environment variables and encrypted-secret key names. Regression tests run in the existing credential-free GitOps gate, alongside schema, Pod Security and network-policy validation. Promotion remains automatic.

Terraform CI initializes with `-backend=false -lockfile=readonly`, validates configuration and checks federation formatting. It has no Azure administration credentials or production-state access. The committed provider lock file contains official Linux and Mac checksums.

The eight migrated backup uploaders pin Azure CLI 2.91.0 by digest. Its RPM packaging requires `python3.12` and `PYTHONPATH=/usr/lib64/az/lib/python3.12/site-packages`. The mounted helper calls the CLI library inside the process, keeping the federated JWT out of OS arguments. Storage commands use `AZURE_STORAGE_AUTH_MODE=login`. The GitOps contract rejects a regression to an unverified image, interpreter or account-key login.

## Verification and retirement

- All 18 publishing workflows passed, including executed Azure OIDC and ACR login steps.
- Hasadnaa's actual application storage implementation uploaded a synthetic blob, issued a user-delegation download URL, verified its contents and deleted it.
- Blutag's actual OpenAI implementation completed a request. ACS authorization was accepted for a recipient-free invalid request; no email was sent.
- The billing and Slack identities read cost data. Backup-report and Slack identities read backup metadata and were denied writes. Loki's identity passed a scoped synthetic blob write/read/delete check.
- The committed backup uploader completed a synthetic upload/download/content check and deleted the test blob, without database access. Loki readiness and a historical log query also passed.
- SSH over Tailscale worked from both Macs; public SSH port 22 remained closed.
- The legacy slack-billing-reporter application password and its Cost Management Reader assignment were revoked after replacement reads passed.

The separate PostgreSQL upgrade can intentionally suspend Argo reconciliation and database writers. Preserve that hold. Do not report all applications healthy from stale Argo status during maintenance, or restart workloads to complete identity checks. Verify the backup upload/download path with synthetic content while the database is fenced, then verify the reconciled scheduled template after maintenance.

## Remaining credentials

The separate [GitHub App migration](github-promotion.md) replaced and revoked the cross-repository promotion PAT. Azure federation does not replace the SOPS age key, application/database credentials or third-party API tokens. Storage shared-key access and OpenAI/ACS keys were not disabled account-wide because offline or external consumers require a separate inventory. Their keys were removed from the migrated active workloads' encrypted secrets. Do not rotate or revoke shared credentials without verifying every remaining consumer.

For new services, follow the workspace `.agents/skills/scaffold-go-app/SKILL.md` and its platform reference. Add identity profiles only when the application actually calls Azure APIs; ordinary private MCP services do not need a runtime Azure identity.
