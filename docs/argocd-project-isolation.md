# Argo CD project boundaries

Each active Application has an explicit project in `argo-projects/registry.yaml`.
`platform-bootstrap` owns the Application/AppProject definitions and the existing
WhatsApp refresh RBAC. Other platform projects retain only their required resource
types and destinations. Ordinary app projects cannot target infrastructure namespaces
or administer cluster resources other than their own declared Namespace. Generated
WhatsApp workers use `app-multi-whatsapp-workers`; their project is never templated
from account input. No project tokens, new credentials or manual approval gates are
introduced. Normal delivery remains main → automatic validation → production.

The parent `apps` Application owns the project manifests at sync wave -10. They
have Prune=false/Delete=false and no cascading-delete finalizers. The root Application
itself remains externally bootstrapped from `apps/apps.yaml`; its one-time project
change must be verified directly, because that file is not in the root Kustomization.

## Enforcement and version limits

Argo enforces exact source repositories, destination clusters/namespaces, permitted
namespaced resource types and permitted cluster resource names. The installed
AppProject CRD supports `name` for cluster resources, but not namespaced rules.
Do not add unsupported fields or claim namespaced object-name enforcement by Argo.

Automatic CI additionally binds each Application to its expected source paths and
project, and checks every rendered resource's group/kind/name/namespace against
`resource-identities.yaml`. It covers hooks, pinned external charts, all generated
workers and encrypted Secret identities. Tailscale's DNS Service in kube-system and
the notification Secret in default remain explicit cross-namespace dependencies;
CI rejects other identities. These projects are privileged infrastructure boundaries,
not untrusted tenant sandboxes. Project policy does not restrict Kubernetes access
of running service accounts, nor replace Git write controls or admission policy.

KSOPS names are sometimes encrypted. `secret-identities.yaml` binds verified public
resource metadata to a fingerprint of the ciphertext identity fields. CI substitutes
only these metadata-only Secret stubs into its disposable Kustomize tree; it never
receives production keys or decrypted values. After creating, renaming, re-encrypting
or rekeying a KSOPS file, the authorized owner runs:

```sh
SOPS_AGE_KEY_FILE=/path/to/owner/keys.txt python3 scripts/record-secret-identities.py
```

`make sops-encrypt` and `make sops-edit` run this binding refresh automatically
after successful encryption/editing. Direct SOPS/rekey workflows run it explicitly.
It decrypts in memory and writes only public resource identities/fingerprints.
Never commit the key or decrypted output. Update the resource identity and project
contracts deliberately when adding resources; do not generate broad permissions
just to make a failing gate pass. Ordinary image-digest promotions require no new
permissions and keep using the existing automatic pipeline.

## Staged adoption and verification

1. Prepare projects while existing Applications remain on default. Validate all
   desired renders against their future projects and server-dry-run the policies.
2. Verify live dry-run denials, move the externally bootstrapped root, then migrate
   static Applications and the ApplicationSet template through automatic promotion.
3. Require every live/generated Application to use its intended project and become
   Synced/Healthy before making default deny all sources, destinations and resources.
4. Verify fresh rendering, access, preserved credentials/workloads and external Helm
   recovery with the deny-all default still in place.

The final gate requires the enforced phase; temporary migration phases are not a
standing bypass. `scripts/test-argocd-projects.py` tests negative permissions without
credentials. With a trusted owner KUBECONFIG, `scripts/verify-argocd-projects.py --run
--default-deny` creates temporary manual-only Applications and requests dry-run syncs
of harmless forbidden fixtures. It checks actual Argo rejection and removes its
Applications; no fixture workload, Secret, Namespace or RBAC resource is created.

## Recovery

Keep [external Helm recovery](argocd-self-management.md). AppProject restrictions do
not restrict the owner's direct Kubernetes/Helm access. Pause parent and self-management,
run pinned Helm, repair validated desired state, and restore exact automation policies.
Helm does not recreate projects or reopen default. Never recover by switching an
Application back to the locked default project.

If a broken project prevents reconciliation, keep automation paused and use a clean
known-good post-isolation checkout to restore project policies directly with the
trusted owner identity, independently of Argo's API:

```sh
kustomize build argo-projects | kubectl --context jshipster apply --server-side \
  --field-manager=argocd-project-recovery --force-conflicts -f -
```

Set the trusted KUBECONFIG explicitly. Verify policy and source validity before
resuming; restore only the intended policies, not broader permissions or old Secret
contents. Keep project names and Application UIDs stable during recovery.
