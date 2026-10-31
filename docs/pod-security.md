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
  multi-whatsapp (including workers and migration/monitor jobs).
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
