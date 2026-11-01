# jshipster GitOps

Kubernetes manifests for the `jshipster` Azure AKS cluster. Argo CD reconciles
the automatically validated `production` branch from this repository. Always select `--context jshipster`; set
`KUBECONFIG` explicitly when using a non-default credential file.

## Layout and ownership

- `apps/kustomization.yaml` is the authoritative list of active applications.
- `apps/apps.yaml` bootstraps the Argo CD app-of-apps.
- `argo-projects/` defines [restricted project boundaries](docs/argocd-project-isolation.md);
  each Application has an explicit project and `default` denies deployments.
- Service directories contain Kustomize resources and KSOPS secret generators.
- `multi-whatsapp/worker-chart` supplies dynamically generated account workloads.
- `apps/argocd.yaml` manages Argo CD itself using the pinned Helm chart,
  `argocd-ksops-values.yaml` and `argocd/self-management-values.yaml`.
  Keep external [Helm recovery](docs/argocd-self-management.md) and existing credentials.
- Commented-out applications and unreferenced manifests are retained recovery
  scaffolding, not proof that a workload is running. Check Kustomize references.

Application CI owns application image tags. Do not manually change those tags.
Infrastructure versions are pinned in their Kustomizations or Helm values.

## Secrets

Secrets are encrypted with SOPS and age, and decrypted by KSOPS in Argo CD's
repo-server. The local `keys.txt` is ignored by Git; never commit or print it.
Use `make sops-edit FILE=<service>/secrets.yaml` for secret changes. Do not commit
rendered manifests containing decrypted Secrets.

## Databases and backups

The active application databases share PostgreSQL in the `postgres` namespace.
Several legacy `*-postgres` Argo applications retain connection Secrets and do
not deploy database servers. See `shared-postgres/README.md` before changing
ownership or removing any database resources. Recovery artifacts and PVCs must
not be deleted as routine cleanup.

`pg-backups` manages scheduled backups. Successful Job status is necessary but
is not a substitute for verifying uploaded archives and testing restores.

## Validation and deployment

1. Review `git diff` and render changed Kustomizations. KSOPS-based directories
   require the configured plugin and age key; keep decrypted output private.
2. Use server-side dry runs for changed resources. Existing Job pod templates
   are immutable; admission Jobs use Argo hooks with recreation policies.
3. Push changes to `main`; automatic validation promotes passing commits to the
   protected `production` branch without human approval. See
   [deployment gate](docs/deployment-gate.md). Then check Argo sync, health, rollout status,
   restart counts, warning events, and the affected service endpoints.
4. Argo CD changes use the same automatic gate. For external recovery, follow
   [pause → Helm → resume](docs/argocd-self-management.md); direct Helm upgrades
   are blocked while parent or self-management reconciliation is active.

```sh
kubectl --context jshipster get applications -n argocd
kubectl --context jshipster get pods -A
kubectl --context jshipster top nodes
kubectl --context jshipster get events -A --field-selector=type=Warning
```

## Infrastructure maintenance

Traefik v3.7.16 replaces the retired Ingress NGINX controller. Its maintained
annotation compatibility provider preserves existing Ingress resources and
cert-manager HTTP-01 routing. Two replicas serve HTTP and HTTPS
through the original public Service/IP. Bastion SSH uses the existing Tailscale
subnet route; see [private SSH](jshipster-bastion/README.md).
See `ingress-controller/README.md` for
security settings, retained compatibility names, and migration checks.

Argo CD v3.5.6 retains the upstream nil-list guard for the controller pager
panic observed on v3.2.0. Resource requests and limits for Argo CD and Tailscale
are version-controlled. Tailscale Connector resources select the explicit
`jshipster-resources` ProxyClass.

AKS version upgrades and node-pool capacity changes require authenticated Azure
management-plane access and belong in the infrastructure repository. Kubernetes
API access alone does not verify AKS LTS enrollment or Azure billing resources.

Verified infrastructure versions (2026-10-29): Cloudflared 2026.10.5, cert-manager
1.20.5 (the latest compatible minor for Kubernetes 1.32), ExternalDNS 0.24.0,
Loki 3.7.9, Alloy 1.21.3, Tailscale operator 1.104.2 with proxies 1.104.4,
and KSOPS 4.5.1. PostgreSQL remains 17.11 with pgvector 0.8.6, pinned to the
verified running image digest; major database upgrades require a separate
data migration. See `loki/README.md` for the scheduled index-format transition.
