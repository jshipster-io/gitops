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
outputs are removed. Named owner data roles enable interactive OpenAI, Speech
and OCR v3.1 metadata access; OCR v4 delegated-user access remains unresolved
(see below). CI identities do not receive those roles.

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

### Final access verification (2026-10-31)

- All 31 Argo applications were Healthy/Synced; Hasadnaa and Blutag public health
  endpoints returned HTTP 200. Terraform and GitOps hosted validation passed.
- Both Macs can read Terraform state through Entra with Shared Key disabled.
  The final targeted Terraform plan reported no changes.
- Loki's service-account federation uploaded/read/deleted synthetic content in
  its own container and was denied access to the PostgreSQL backup container.
- Owner Entra access passed OpenAI embeddings, Speech voice metadata and Document
  Intelligence v3.1 model metadata. Document Intelligence v4 model metadata
  returned HTTP 401 with the same delegated token. No active deployment consumes
  that OCR endpoint, but full owner v4 access is **not** verified/preserved.

Run `python3 scripts/verify-azure-key-auth.py --check-owner-ai` to include these
operator checks. It deliberately exits nonzero while v4 access remains broken;
it does not substitute v3.1 and report v4 success. The default audit checks the
six authentication controls and Entra state access, not all operator APIs.

Automatic approval review rejected a proposed new operator managed identity,
Kubernetes federation and OCR data role because a service account in the default
namespace could be acquired by other workloads. The command did not execute;
no operator identity/federation was created. An approved, appropriately isolated
access design and successful v4 verification remain necessary before claiming
full operator access. Keys remain disabled. CI has no human approval gate.
