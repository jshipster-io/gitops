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

- Restricted: cert-manager, ingress-nginx, mashov-mcp, webtop-mcp, tivtaam-mcp,
  multi-whatsapp (including workers and migration/monitor jobs), hasadnaa, drc,
  trips, external-dns and jshipster (including all notification CronJobs). The
  isolated azure-operators namespace also has Restricted labels but deliberately
  denies every pod through its separate admission policy.
- Baseline: ordinary legacy application, backup and database namespaces. Existing
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
the shared blutag and argocd namespaces retain Baseline until their other workloads
are migrated. Database/backup templates, persistent FindMy/Pointer workers, the
third-party anisette cache and root-dependent bastion/KSOPS bootstrap are separate
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
