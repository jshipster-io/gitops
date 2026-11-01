# Argo CD self-management and Helm recovery

`apps/argocd.yaml` adopts the existing `argocd` release using the same pinned
chart and release name. A second source reads values only from the validated
`production` branch. Normal changes follow main → automatic CI → production →
Argo sync, with no human approval or Kubernetes deployment credentials in CI.
The initial migration observes the live comparison before enabling automatic sync.

The shared `argocd-ksops-values.yaml` is used by both Argo and external Helm.
`argocd/self-management-values.yaml` prevents normal reconciliation from creating
credentials or rerunning bootstrap hooks. Existing `sops-age`, repository, Redis,
admin and tunnel secrets stay outside this Application. Redis authentication
remains required. The Namespace keeps its single owner in `pod-security`.
Application name and Helm release name both remain `argocd`, preserving selectors.

The Application has no cascading-delete finalizer and is protected from parent
pruning/deletion. Argo CRDs have Prune=false/Delete=false. CI rejects missing core
controllers, unsafe ownership, plaintext/generated secrets, bootstrap hooks and
unvalidated Git sources. Controller resources otherwise use automated prune and
self-heal; an empty render is forbidden. Both recovery and self-managed Helm
renders pass the same security and schema checks.

## Recovery without a working Argo API

Keep the existing Helm release/history. Never run `helm uninstall`, delete Argo
CRDs or namespaces, or recreate credentials as part of an ownership migration.
The Helm release records the last bootstrap/recovery operation, not subsequent
GitOps reconciliations. It is not evidence of the currently deployed Git revision.

Use a clean checkout of a known-good validated commit and the trusted owner
KUBECONFIG. Preserve the existing age key and other external credentials. The
following commands use Kubernetes and Helm directly, not Argo's HTTP API:

```sh
export KUBECONFIG="$HOME/.kube/prod-aks-entra"
python3 scripts/argocd_recovery.py plan
python3 scripts/argocd_recovery.py recover --run --state-file /tmp/argocd-recovery-state.json
# Repair and validate Git desired state before restoring reconciliation.
python3 scripts/argocd_recovery.py resume --run --state-file /tmp/argocd-recovery-state.json
```

Choose a new state filename for each recovery. The owner-only file records the
exact original automation policies and Application UIDs, never secret values.
Recovery pauses the parent `apps` Application first, then `argocd`, and requests
termination of their active sync operations before Helm. Other service Applications
remain independent. On success or failure it leaves these two Apps paused so a
broken Git revision cannot immediately undo recovery. Resume checks their UIDs and
restores the child policy before the parent's original policy. A missing/changed
Application requires inspection rather than blindly restoring an old snapshot.

`make argocd-upgrade` refuses to run against active self-management. When safely
paused, it verifies the narrow hook/API network allowance, uses an isolated Helm
cache and the pinned chart/base values, and rolls back a failed Helm upgrade.
The Redis bootstrap hook reads the existing secret; it must not rotate it.
Repo-server's zero-surge strategy fits the bounded two-node pool but briefly pauses
rendering during a replacement. Running application traffic is independent.

After adoption or recovery, verify the actual repo-server runtime, unchanged
protected secret fingerprints, fresh production secret rendering, all Application
sync/health states, Restricted admission, authenticated Argo access, application
readiness and private access from both Macs. Never print decrypted manifests.
A recovery drill should exercise pause → Helm → resume without inducing a failure
or deleting existing secrets. Remove only its temporary state file after success.
