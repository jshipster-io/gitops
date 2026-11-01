# Pod Security Admission

Namespace policy is pinned to Kubernetes `v1.35`. `pod-security/profiles.yaml`
records each namespace's enforcement level and compatibility reason. Warning and
audit modes use Restricted, including namespaces with documented exceptions.
AKS-managed `kube-system` is deliberately outside this GitOps policy; its CNI and
CSI workloads require privileged host access.

The rollout first published audit/warning labels with privileged enforcement,
validated running pods and live controller/CronJob templates, then advanced to the
compatible enforcement levels. Labels do not restart or evict existing pods.
Enforcement protects newly created pods, including controller replacements.

- Restricted: argocd, cert-manager, ingress-nginx, mashov-mcp, webtop-mcp, tivtaam-mcp,
  multi-whatsapp (including workers and migration/monitor jobs), hasadnaa, drc,
  trips, external-dns and jshipster (including all notification CronJobs), plus
  postgres and pg-backups (including recovery and TLS reload jobs). The
  isolated azure-operators namespace also has Restricted labels but deliberately
  denies every pod through its separate admission policy.
- Baseline: remaining legacy application namespaces. Existing
  images/init scripts and jobs are not assumed to support forced non-root startup.
  Baseline rejects privileged containers, host namespace sharing and hostPath,
  while Restricted audit/warnings expose the remaining migration work.
- Privileged exceptions: tailscale (privileged subnet router), cyberghost-egress
  (VPN network capabilities), loki (Alloy host log mounts). These are namespace-wide
  PSA exceptions, not per-pod exemptions; restrict workload creation there through
  RBAC. Existing NetworkPolicies and application authentication remain necessary.

Existing Namespace resources retain their current application ownership. The
`pod-security` Application manages only previously unowned Namespace manifests,
using server-side apply. Every managed Namespace has `Prune=false,Delete=false`:
removing a policy Application must not delete workloads or namespaces.

## Automatic delivery checks

The existing `gitops-validation` check builds `tools/pod-security`, pinned to the
upstream Kubernetes `pod-security-admission` v0.35.0 evaluator. All active rendered
Kustomize workload templates, CronJobs and WhatsApp worker Helm renders are checked
against their configured target enforcement level, including init and ephemeral
containers. Namespace labels/version pins and deletion safeguards are checked too.
No production credentials, API access or human approval are required in CI.
External/operator-generated workloads and separate Helm releases also need live
server dry-run checks; they are not all rendered by the GitOps validator.

```sh
(cd tools/pod-security && go build -o /tmp/psa-check .)
PATH="/tmp:$PATH" python3 scripts/test-pod-security.py
PATH="/tmp:$PATH" python3 scripts/validate-gitops.py
KUBECONFIG="$HOME/.kube/prod-aks-entra" python3 scripts/verify-pod-security.py
```

The last command reads current policy labels, submits live controller/job templates
with server-side dry-run, and verifies compliant pods are accepted and privileged
pods rejected in protected namespaces (also root rejection under Restricted).
It never creates a pod. Runtime endpoint/MCP/database/SSH checks remain separate.
Do not execute notification or backup jobs merely to test their admission.

For a new app, select Restricted from the start, add its namespace/profile and
protected Namespace manifest, and make every generated template compliant. Avoid
multiple Applications owning the same Namespace. Resource-only NetworkPolicy
namespaces still need a single explicit namespace policy owner.

For a legacy migration, fix one workload at a time, validate its real startup and
access, check all scheduled/init/operator templates, then promote the namespace to
Restricted. Do not switch all legacy images to an arbitrary UID or strip capabilities
from the VPN/bastion/database entrypoint without testing their requirements.
PSA does not require a read-only root filesystem or disable service-account tokens;
those remain separate workload-hardening tasks where not already configured.

If admission blocks an existing replacement, repair the workload or revert only
that namespace's level through `main` and the automatic production gate. Preserve
audit/warning labels and other namespaces' enforcement. A policy change that passes
CI is not proof of live application availability.

Reference: [Kubernetes namespace policy staging](https://kubernetes.io/docs/tasks/configure-pod-container/enforce-standards-namespace-labels/).

## Stateless runtime hardening (2026-11-01)

Eight Deployments and eight notification CronJobs have explicit non-root users,
RuntimeDefault seccomp, no privilege escalation, all capabilities dropped and
read-only root filesystems. Their writable temporary/cache/PID directories use
size-limited emptyDir volumes. `workloads.yaml` records the exact runtime identities
and Kubernetes token exceptions; CI rejects regressions even in a namespace still
at Baseline. Run `scripts/test-workload-hardening.py` and the full validator.

The Deployment scope is Hasadnaa, Trainings, Trips, Blutag App, Blutag Website,
External DNS, the Argo cloudflared tunnel and Slack Notifications. Existing image
users are preserved: Hasadnaa 1000, Trainings/cloudflared 65532, External DNS 65534,
Nginx 101, and the other listed Go runtimes 1001. Nginx starts directly and gets
separate writable cache/PID volumes; it does not need a writable configuration
or root startup scripts. Port 80 remains usable with the verified container
network setting, without adding a bind capability.

External DNS retains its Kubernetes token to watch resources. The notification
Deployment and uptime-check CronJob retain their scoped ConfigMap access for
outage/recovery state. Other listed workloads disable automatic API tokens;
separate Azure federation projections and GCP credential mounts are preserved.

The notification source image now runs from /app as UID/GID 1001. Its legacy
/root/slack-notifications path remains an executable compatibility link during
image/manifest promotion; current scheduled templates use /app/slack-notifications.
Source CI checks the published image as non-root with a read-only filesystem and
no network before promotion. Tests must not send reports, notifications or emails.

Deploy hardened templates first, verify replacements and access, then promote
namespace enforcement. Hasadnaa, drc, trips, external-dns and jshipster completed
this staged sequence. Blutag App/Website and cloudflared have per-workload guards;
the shared blutag namespace retains Baseline until its other workloads
are migrated. Argo CD completed its separate bootstrap migration below. Persistent FindMy/Pointer workers, the
third-party anisette cache and root-dependent bastion are separate
compatibility work; do not infer they were migrated by this stateless stage.

```sh
KUBECONFIG="$HOME/.kube/prod-aks-entra" python3 scripts/verify-workload-hardening.py
KUBECONFIG="$HOME/.kube/prod-aks-entra" python3 scripts/verify-pod-security.py
```

Live checks include replacement readiness, positive/negative PSA dry-runs, public
readiness routes, Hasadnaa synthetic PDF rendering, notification ConfigMap read
success and secret-read denial, and private SSH/owner API access from both Macs.
The runtime verifier never starts scheduled jobs. Shell `test -w` alone is not
proof of a writable filesystem: validate mount flags and an owned disposable write
attempt when testing read-only enforcement, and remove temporary probe files.

## Database and backup runtime hardening

The shared PostgreSQL images retain their verified UID/GID/fsGroup 999. Both the
active PostgreSQL 18 StatefulSet and the retained, zero-replica PostgreSQL 17
StatefulSet have read-only root filesystems, RuntimeDefault seccomp, no privilege
escalation, dropped capabilities and no automatic API token. Data stays on the
original PVC; only sockets/PID files (`/var/run/postgresql`, 16Mi) and temporary
files (`/tmp`, 128Mi) use bounded emptyDir volumes. Preserve TLS mounts, image
digests, PGDATA, service selection and `OnRootMismatch` group handling. CI also
pins the active/offline replica counts and both PVC retention settings to Retain.
Never start the retained PostgreSQL 17 database as a rollback after new writes.

All ten application backup templates and the cluster recovery job use UID/GID
1001, read-only roots and bounded temporary storage. The six legacy application
backups now explicitly mount `/tmp`; Azure CLI uses `HOME=/tmp` and its existing
`AZURE_CONFIG_DIR=/tmp/azure`. Their upload container reads the dump volume
read-only. Keep workload identity, backup schedules, compression/archive names,
container paths, retention and database credentials unchanged. The TLS reload job
keeps its existing UID 999. All fourteen database/backup templates are guarded in
`pod-security/workloads.yaml`, including init containers.

Before a database runtime change, inspect current process/data ownership, recent
backup success, PVC identity and reclaim/retention policy. Rehearse exact pinned
images on disposable storage, including TLS, pgvector, dump/restore and restart.
For this singleton primary a rolling update includes a brief restart/client
reconnect; do not promise zero downtime. Keep a recovery point before restarting
and distinguish a crash-consistent disk snapshot from a tested logical restore.

```sh
python3 scripts/test-database-hardening.py
KUBECONFIG="$HOME/.kube/prod-aks-entra" python3 scripts/verify-database-runtime.py --run
KUBECONFIG="$HOME/.kube/prod-aks-entra" python3 scripts/verify-backup-runtime.py --run
```

The first live probe mounts no production data and binds its synthetic database to
loopback. The second reads schema only through the six changed backup templates
and uploads/downloads/deletes uniquely named synthetic blobs under
`hardening-probes/`; it never uploads database dumps or overwrites backup archives.
Both require explicit `--run`, use deadlines and remove their Jobs. These are
opt-in operational probes, not production-credential dependencies for CI. CI tests
their isolation and runs the normal credential-free manifest/security gate.

Publish runtime contexts first while existing admission remains in place. Verify
ready replacement pods, unchanged database/access catalogs and PVCs, TLS, real
application readiness and owner access. Then advance postgres and pg-backups to
Restricted only after all their controller and scheduled templates pass live
admission checks. A synthetic backup probe proves runtime/identity/I/O behavior;
it does not claim that the next scheduled full backup has already run. Remove only
temporary probe artifacts/recovery snapshots created for this rollout, preserving
normal backups and previous recovery points. If the replacement fails, revert the
runtime change through automatic GitOps validation and reuse the current data PVC.

## Argo CD / KSOPS bootstrap

Argo CD remains a separately Helm-managed release, pinned by `make argocd-upgrade`.
The automatic gate now renders its pinned chart as well as GitOps Applications,
checks all chart workload templates against the namespace PSA profile, and enforces
the bootstrap contract in `scripts/argocd_bootstrap.py`. A credential-free Docker
check proves the exact installer image can install with the same non-root user,
read-only root, capability drops, memory limit and bounded temporary volume.

The distroless KSOPS image uses UID/GID 65532; preserve that identity separately
from Argo CD's UID 999. It installs only KSOPS into a 64Mi emptyDir and never mounts
the production age key. Its root is read-only, privilege escalation is disabled,
capabilities are dropped and seccomp is RuntimeDefault. The repo-server mounts the
installed plugin read-only, retains its existing read-only age-key path, and no
longer mounts a Kubernetes API token. Preserve Argo CD's bundled Kustomize and
`--enable-alpha-plugins --enable-exec`; do not install a shell into the distroless
image or expose decryption keys to CI.

For an authorized upgrade, run the normal gate and the opt-in rehearsal:

```sh
python3 scripts/test-argocd-bootstrap.py
KUBECONFIG="$HOME/.kube/prod-aks-entra" python3 scripts/verify-ksops-bootstrap.py --run
```

The rehearsal creates only a disposable age key, synthetic ciphertext, a temporary
Secret and an isolated Job. It checks both successful rendering and missing-key
rejection, then removes its resources. Existing production secret rendering must
also be verified after the real rollout, using hard refreshes and secret integrity
checks without printing rendered Secrets. Preserve the installed chart, live Helm
values and prior release for recovery. Upgrade only after automatic CI passes;
Helm-managed changes do not deploy merely because GitOps production advanced.
Stage runtime settings before changing argocd admission to Restricted, and verify
all controller/init/hook templates plus UI, deployment and private owner access.
Keep a Helm recovery path even if Argo CD is later made self-managing.

The Helm Redis initialization hook needs its existing scoped secret RBAC and API
connectivity. `redis-secret-init-to-api` permits only its pod selector to the API
Service and observed endpoint addresses on TCP 443; it adds no general internet
or application access. `make argocd-upgrade` checks these against live EndpointSlices
before running hooks. If AKS addressing changes, update the narrow policy through
GitOps first. Preserve the existing Redis secret rather than generating a new one.

On a full two-node pool, a surge replica may remain Pending even after the hook
passes. Check scheduling and autoscaler bounds rather than treating desired
Deployment fields as a completed rollout. The repo-server uses maxSurge 0/maxUnavailable 1 to fit
within the existing budget; singleton replacements briefly pause manifest rendering. Verify the new pod itself and repeat hard refreshes only after
rollout convergence. `verify-pod-security.py --namespace argocd` scopes live
admission checks to this change; omitting the flag checks every managed namespace.
