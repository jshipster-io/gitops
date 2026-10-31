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
and OCR v3.1 metadata access. OCR v4 uses the isolated operator federation
described below. CI identities do not receive those roles.

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

After explicit owner authorization, both protected pre-change keys for each of
OpenAI, Document Intelligence and Speech were used only in process memory for
negative requests. All six requests returned HTTP 403. The request targets matched
the pre-cutover API probes. No keys or response bodies were printed or written.
The earlier approval blocker is resolved; this is now a data-plane rejection
measurement, not merely a disabled-setting check.

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
- Owner Entra access passes OpenAI embeddings, Speech voice metadata and Document
  Intelligence v3.1 model metadata. The delegated user token still does not serve
  OCR v4; the new app-only operator identity passes v4 model metadata and correctly
  recognizes a generated synthetic PDF page. It is denied unrelated OpenAI access.
- Following the isolated operator deployment, all 32 Argo applications were
  Healthy/Synced. No existing service workload was replaced for this change.

## Isolated OCR v4 operator access

Terraform owns `jshipster-docintel-operator`, its sole federation subject
`system:serviceaccount:azure-operators:docintel-operator`, and the
`Cognitive Services User` role scoped only to `jshipster-docintel`.
It has no client secret/certificate and no CI role or grant.

GitOps owns a dedicated `azure-operators` namespace with Restricted PSA,
default-deny ingress/egress, zero pod/secret quota and explicit admission denial
of pods and secrets (including legacy service-account tokens). No workloads run
there. The service account disables automounting and has no Kubernetes role of
its own. A named-owner RoleBinding permits only that service account's TokenRequest.

Fail-closed admission additionally restricts TokenRequests to the owner's Entra
object ID, the exact service account, the Azure exchange audience and 600-second
lifetime. It uses the namespace name, not a removable label selector. The resulting
Azure access token has Azure's own expiry (not necessarily 600 seconds); the helper
keeps both tokens in memory, prints neither, and refuses HTTP redirects.
Cluster administrators who can modify these admission policies remain trusted.

The live tests deny an otherwise privileged Argo controller's token request,
owner requests with excessive lifetime/wrong audience, a pod using the account,
and a persistent token Secret. Pod/Secret tests use server dry-run only.
These policies do not change token issuance in other namespaces.

```sh
python3 scripts/verify-ocr-isolation.py --kubeconfig /Users/elad/.kube/prod-aks-entra
python3 scripts/ocr_operator.py --kubeconfig /Users/elad/.kube/prod-aks-entra --analyze-synthetic
python3 scripts/verify-azure-key-auth.py --check-owner-ai --kubeconfig /Users/elad/.kube/prod-aks-entra
```

The default auth audit remains read-only settings/state-metadata verification.
The owner audit verifies v4 using the isolated identity rather than substituting
v3.1 success. Application OCR clients must use their own scoped workload identity;
they must never reuse the operator identity. The helper's `token()` and `request()`
functions provide the owner CLI's in-memory v4 access path.

Eight GitOps regression tests reject weakened isolation, and the standard gate
checks the rendered controls. Terraform's mocked plan asserts the exact subject,
audience and OCR-only role scope. Both hosted pipelines remain automatic with no
human approval gate. The owner explicitly approved this isolated design after
the earlier default-namespace proposal was rejected; that rejected design was
never applied.

Admission behavior follows the [Kubernetes validating admission policy contract](https://kubernetes.io/docs/reference/access-authn-authz/validating-admission-policy/).
