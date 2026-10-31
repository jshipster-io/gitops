# Azure key-authentication retirement

## Resource and consumer inventory — 2026-10-31

| Resource | Consumers and disposition |
| --- | --- |
| `jshipsterprod410479` | Active: Hasadnaa documents/user-delegation SAS, Loki, PostgreSQL backups/recovery and backup reporting. All use workload identity. Shared Key is disabled; OAuth is the portal default. |
| `tfstateaks1c9c999c` | Owner Terraform on both Macs. Backend uses Entra, with the existing owner Blob Data Contributor assignment. Shared Key is disabled. |
| `jshipster-openai` | Active: Blutag workload identity. IDS, dirtbike-specialist and gen-rag are inactive in AKS and must migrate their legacy clients before reactivation. Local authentication is disabled. |
| `jshipster-docintel`, `jshipster-speech` | Legacy dirtbike/gen-rag consumers are inactive. Local authentication is disabled. |
| `jshipster-communication` | Active: Blutag workload identity. Legacy IDS is inactive. Local authentication is disabled; linked email domains are preserved. |

Neither storage account has file shares, queues or tables. The historical Mac
`padel-backups` SAS uploader is not installed in the current LaunchAgents,
LaunchDaemons or crontab inventory. ANPR and Padel applications are retired in the
active GitOps application list. Historical backup objects are preserved. All 18
publishing repositories have no repository-level Azure/ACS/storage credential
secrets. CI continues using the existing per-repository OIDC identities.

Before cutover, storage metrics showed the earlier account-key activity falling
to zero in the latest complete hourly window after the workload-identity rollout.
Metrics alone do not identify every historical or dormant consumer. Legacy source
code, ignored local configuration and historical encrypted backups can still hold
obsolete credentials; they are not a reason to re-enable account keys. Reactivating
a retired service requires migrating its client and verifying its scoped identity.

## Configuration and automatic validation

Terraform owns the production storage and three Cognitive Services settings.
AzureRM does not expose the ACS setting, so an `azapi_update_resource` patches only
`properties.disableLocalAuth`; it does not replace linked domains. The state
account is maintained by `setup-backend.sh`, which disables Shared Key and uses
`--auth-mode login` for container access. Both the Terraform backend and AzureRM
provider explicitly select Entra storage authentication. Key/connection-string
outputs are removed. Named owner data roles preserve interactive OpenAI, OCR and
Speech access; CI identities do not receive those roles.

Terraform CI runs mocked plans asserting the resource settings plus checks for
identity-only backend/provider/bootstrap configuration and absent key exports.
It requires no cloud credentials or human approval. GitOps validation rejects
retired Azure key variables in active containers/init containers/ConfigMaps and
checks encrypted Secret field names across every active application, including
applications without a pre-existing workload-identity profile. An old application
cannot be re-enabled with its legacy key references through the normal gate.

Read-only live audit (no keys retrieved):

```sh
python3 scripts/verify-azure-key-auth.py
```

The resource contract is `azure-auth/resources.json`. Also verify actual service
operations; a successful settings audit is not proof of data-plane propagation.
For a fresh Terraform checkout use `terraform init -reconfigure`; do not supply
an access key or SAS backend override. Existing operator data-plane roles remain
necessary even when the operator has management-plane Owner rights.

## Verification and limits

The original keys passed baseline requests before cutover. After cutover:

- Both storage accounts reject Shared Key requests with
  `KeyBasedAuthenticationNotPermitted`.
- ACS rejects a correctly signed key-auth request with HTTP 401. An empty request
  payload contains no sender, recipients or content and cannot send email.
- All three Cognitive Services accounts report `disableLocalAuth=true` and reject
  normal key retrieval explicitly because local authentication is disabled.
- Blutag's actual workload identity passes an OpenAI synthetic embedding request
  and ACS authentication without sending email.
- Hasadnaa's application storage code uploads a disposable object, signs a
  user-delegation SAS, reads matching content and deletes the object.
- The live backup CronJob template uploads/downloads/verifies/deletes synthetic
  content using workload identity, without dumping or reading application data.

Exact post-change Cognitive Services old-key data-plane probes remain unverified:
Azure stopped returning their keys, and automatic approval review rejected
recovering the pre-change values from the temporary Terraform plan. No alternate
credential source was used. Azure documents a possible gateway propagation delay;
control-plane success and blocked key retrieval are not an exact old-key rejection
measurement. Do not describe that test as passed.

No email/Slack notification was sent, no service image was manually changed, and
no unrelated database-maintenance or network-policy setting was modified.

References: [Storage Shared Key retirement](https://learn.microsoft.com/en-us/azure/storage/common/shared-key-authorization-prevent),
[AI local authentication and propagation](https://learn.microsoft.com/en-us/azure/ai-services/disable-local-auth),
[ACS authentication property](https://learn.microsoft.com/en-us/azure/templates/microsoft.communication/2025-05-01/communicationservices).
