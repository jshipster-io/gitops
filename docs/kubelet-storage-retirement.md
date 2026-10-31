# Kubelet storage grant retirement

The kubelet previously held `Storage Blob Data Contributor` on the entire
`jshipsterprod410479` account. Terraform removes only
`azurerm_role_assignment.aks_storage_blob_data_contributor`. The kubelet keeps
`AcrPull` on `prodacr1234`; control-plane, CSI and application roles are unchanged.

## Consumer inventory

The live inventory covered pods, all CronJob templates, service-account identity
annotations, active GitOps manifests, application credential selection and PVs.
All PVs use `disk.csi.azure.com`; none mounts Azure Blob or Azure Files. The new
PostgreSQL monitor/watchdog inspects Kubernetes job/service status and is not an
additional blob client. Retired application manifests are not active consumers.

| Active path | Service account | Required access |
| --- | --- | --- |
| Hasadnaa documents and signed downloads | `hasadnaa/hasadnaa` | Write its container; account-scoped Blob Delegator for user-delegation SAS |
| Loki object storage | `loki/loki` | Write `loki-logs`; `use_federated_token: true` |
| Ten application backup schedules | `pg-backups/pg-backups` | Write `pg-backups` |
| Cluster recovery archive | `postgres/postgres-backup-recovery` | Same backup identity through its separate exact federation subject |
| Backup report | `jshipster/azure-backup-reporter` | Read `pg-backups` |
| Slack backup metadata | `jshipster/uptime-check` | Read `pg-backups`; separate billing permissions unchanged |

Application storage clients explicitly select workload credentials when a
projected token exists. Read-only reporting checks do not send Slack messages.
Historical objects and dormant external consumers cannot be attributed from
storage metrics alone; no blob diagnostic logs were available for historical
principal attribution. This inventory is not a claim to enumerate every old
external script. External callers cannot normally use the AKS kubelet identity.

## Repeatable validation

```sh
python3 scripts/verify-storage-identities.py --kubeconfig /Users/elad/.kube/prod-aks-entra
```

The audit requires the kubelet's only direct subscription-visible grant to be
registry-scoped `AcrPull`. It exchanges exact service-account tokens in memory,
checks their Azure principal differs from the kubelet, verifies container metadata,
and uses unique disposable blobs for write/read/delete checks. Readers must be
denied writes; every identity must be denied an unrelated container. No database
or existing blob contents are read. `--allow-legacy-grant` is explicitly a
pre-retirement baseline mode, never post-retirement evidence.

Terraform CI runs a credential-free guard and four regression tests: the approved
configuration passes, while a renamed node storage grant, ACR push privilege and
a broadened ACR scope fail. The only permitted Terraform kubelet identity reference
is the registry-scoped pull grant. Application storage belongs to workload
identities; never restore a broad node role to repair a missing application grant.

The dedicated identity tests are separate from actual kubelet revocation: role
assignment deletion can precede storage data-plane propagation. Verify denial
using the exact kubelet principal's IMDS token before claiming full retirement.

The repeatable IMDS probe is `tools/kubelet-storage-probe/main.go` (Go standard
library only; CI compiles it). Build for the node OS/architecture, temporarily run
it inside an authorized cluster diagnostic context with explicit `-client-id`
and `-object-id` from `az aks show`, then remove it. It validates the token principal
and expiry and requires HTTP 403 `AuthorizationPermissionMismatch` on the three
active containers. `-baseline` expects pre-retirement HTTP 200 instead. Neither
mode prints or persists a token; the probe does not read blob contents or write
storage objects. A failed IMDS request or expired token is not successful denial.

Azure documents [role propagation delay](https://learn.microsoft.com/en-us/azure/storage/blobs/authorize-access-azure-active-directory#role-assignment-propagation-delays-for-blob-data-access);
the kubelet's registry access must remain intact while waiting.
