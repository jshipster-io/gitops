# Image and GitHub Actions security audit — 2026-11-01

Scope: all 24 `jshipster-io` default branches and four additional owner repositories found in workspace remotes; Dockerfile stages and external `COPY --from` images; CI services and bootstrap image references; running AKS containers/init containers and CronJob templates. No scheduled business jobs, migrations or notification tasks were launched for this audit.

The source snapshot and exact revisions are in `repositories-2026-11-01.json`. Action pins, upstream release versions, actual JavaScript runtimes and nested action metadata are in `actions-2026-11-01.json`. Image findings are in `images-2026-11-01.json`. These inventories describe the **before** snapshot, not all subsequently patched revisions.

## Method and limitations

Trivy 0.76.1, official release checksum verified; vulnerability database updated 2026-11-01 19:08 UTC. Remote scans use linux/amd64, matching AKS. Images were inspected, not executed. Private ACR credentials stayed in memory. Published results use an explicit field allowlist; raw scanner reports containing image configuration were not committed or uploaded.

Counts below are package/CVE occurrences across scanner targets, **not unique CVEs or confirmed exploitable paths**. A supported/latest base can still contain findings. Library reachability, vendor status and operational exposure require separate triage. For example, Echo's proxy-route advisory requires the affected middleware path; its presence in a binary does not prove that route is exposed.

AKS cloud-node-manager reports an image **configuration** digest. Its scan uses the declared tag and verifies that the image configuration digest exactly matches the running container. The proof is recorded in `identity-map.json`; the original configuration digest cannot be fetched as a registry manifest.

Coverage gaps: the two hard-coded Johnson bootstrap tags (`main-4df7c44`)
are no longer available in ACR. The old `uv:0.5.14` binary-only image produced
no analyzable package results; it is **not certified clean** and was replaced in
the two consumers. All current running image identities in the initial AKS
snapshot were scanned, including the bastion after a longer bounded retry.

## Changes made

- Hasadnaa: Alpine 3.19 → 3.24.2; pgx → 5.9.0; Echo → 4.16.1; x/image → 0.45.0 and compatible transitive patches. Adopted Echo's supported request logger rather than suppressing lint.
- Blutag App: Go builder/CI → 1.27.3; pgx → 5.9.0; Echo → 4.16.1; Excelize → stable 2.11.0 and compatible transitive patches. Some Excelize findings need unreleased fixes and remain reported.
- Blutag FindMy / Pointer Push: Python 3.13.1 → 3.13.18 on the same Bookworm branch; uv builder/CI → 0.13.6; setup-uv → SHA-pinned 10.3.3. Runtime UIDs, persistent paths and probes retained.
- Those four app workflows: SHA-pinned Actions; checkout 7.0.1; exact built-digest scanning before their existing GitOps promotion job.
- Terraform: checkout Node 20 → pinned checkout 7.0.1 / Node 24. Fixed a pre-existing CI failure by obtaining signed Linux checksums for the existing AzureRM/Google provider versions; no Terraform apply or provider-version change.
- Scaffold skill: new services inherit the image scan contract and separate CI/promotion/Argo/live verification requirements.

## Delivery verification

The latest source CI runs for all five changed repositories passed, including
lint/tests, Azure OIDC login and the four exact-digest image gates. Initial
Terraform and Hasadnaa failures were diagnosed and corrected; historical failed
runs were not hidden or treated as successful. GitOps promotion and live image
identity are checked separately from source CI.

GitOps validation now uses a separate concurrency group per commit. This avoids
an out-of-order push event cancelling the current main commit's pending run.
The existing promotion check still refuses any SHA that is no longer main and
requires a fast-forward from production; no approval or validation is bypassed.

All four final scanned digests are running and ready; all 33 Argo applications
are Healthy/Synced. Five public readiness routes and both private Python health
endpoints returned 200; Tailscale SSH succeeded. Runtime security contexts and
persistent volume claim names match the before snapshot. Twenty-one current
check runs had no Node runtime deprecation annotations. See
`verification-2026-11-01.json` for exact commits, CI links and running digests.

| Updated runtime | Critical before → after | High before → after | Fixable critical after |
|---|---:|---:|---:|
| Hasadnaa | 3 → 0 | 10 → 0 | 0 |
| Blutag App | 3 → 0 | 20 → 9 | 0 |
| Blutag FindMy | 9 → 2 | 103 → 69 | 0 |
| Blutag Pointer Push | 9 → 2 | 103 → 69 | 0 |

The two remaining critical Python-image findings have no distro fix in the
scanner database. They remain visible for vendor/applicability triage and are
not silently suppressed. Residual HIGH findings are outside the initial gate.

## Automatic promotion gate

`scan-image.sh` installs a checksum-pinned scanner, obtains a current vulnerability database, scans the exact digest emitted by Buildx, and fails the publishing job for scanner errors or **fixable CRITICAL** findings. Promotion depends on that job succeeding. Existing running workloads remain unchanged when a candidate fails. A sanitized job summary lists critical/high findings; no human approval, new credential or secret access was added.

This first enforcement stage is enabled in the four updated applications, **not every repository**. HIGH and unfixed findings remain a backlog. Passing the gate does not mean vulnerability-free. The helper must remain in sync with the copies in those source repositories; changing this GitOps copy alone does not change their CI.

## Remaining work, in priority order

| Area | Finding | Next change |
|---|---|---|
| Trainings and Slack Notifications | Deployed images have fixable critical library findings; older Go builders | Update compiler/modules, run each service's tests and image gate before normal promotion |
| Blutag Website | Deployed image and current `nginx:alpine` both have a fixable critical finding | Use a tested patched Nginx/base combination; a rebuild of the unchanged floating tag alone is insufficient |
| Argo CD / KSOPS | Even the recently pinned images contain fixable critical findings in bundled components | Update or rebuild compatible upstream artifacts, validate secret rendering and Helm recovery before changing these control-plane images |
| Backup helpers and PostgreSQL image | SOPS, Azure CLI, PostgreSQL/pgvector images contain findings, including fixable critical ones | Patch compatible image components and use isolated backup/restore checks; do not run production backup/import jobs merely for scan validation |
| AKS-managed Azure File CSI | Fixable critical findings in Microsoft-managed image | Use a supported AKS/add-on image update; do not replace managed DaemonSet images manually |
| ANPR builder | Rust 1.88 / old Bookworm build packages have a large finding count | Update the builder and validate both normal and OCR builds; builder findings are not automatically runtime exposure |
| Dormant/other app builders | Go 1.25, Node 20, older Flyway and floating base references | Move to supported branches with compatible build tests; retain native-library requirements and actual runtime UIDs |
| Legacy OpenHaystack Actions | checkout/upload/download artifacts, create-release/upload-release-asset and xcode-select use Node 12; macos-11 and Xcode 12 assumptions are stale | Migrate the complete build/release workflow together and validate on a supported runner; not silently changed or executed during this audit |
| Other production Actions | Mostly already Node 24; newer major releases exist for setup-go/node/python, cache and artifacts | Review release changes and test per workflow; a newer version number alone is not evidence of a CVE |

The full action inventory includes the nested `upload-pages-artifact` upload helper and FindMy's local composite `setup-uv` action. Both nested JavaScript actions inspected use Node 24. The OpenHaystack local composite also fetches the old ESP-IDF `release/v4.3` branch.

## Verified upstream references

- [Alpine support branches](https://alpinelinux.org/releases/)
- [Python 3.13.18 security release](https://www.python.org/downloads/release/python-31318/)
- [pgx advisory and fixed version](https://github.com/advisories/GHSA-xgrm-4fwx-7qm8)
- [Echo upstream proxy advisory](https://github.com/labstack/echo/security/advisories/GHSA-cxf3-9h37-7rr8)
- [Checkout releases and compatibility changes](https://github.com/actions/checkout/releases)
- [uv releases](https://github.com/astral-sh/uv/releases)

## Initial image inventory

79 of 82 references have analyzable scanner results. Unverified references are explicitly listed, not counted as clean.

| Image | Use | Critical | High | Fixable critical |
|---|---|---:|---:|---:|
| `alpine:3.19` | base | 0 | 2 | 0 |
| `alpine:3.23` | base | 0 | 0 | 0 |
| `alpine:latest` | base | 0 | 0 | 0 |
| `debian:bookworm-slim` | base | 1 | 48 | 0 |
| `docker.io/cloudflare/cloudflared@1b1d34d0a9c0` | deployed | 0 | 1 | 0 |
| `docker.io/dadoum/anisette-v3-server@d551c75454bc` | deployed | 0 | 49 | 0 |
| `docker.io/grafana/alloy@8ab871206bd2` | deployed | 0 | 0 | 0 |
| `docker.io/grafana/loki@0db216b630ae` | deployed | 0 | 0 | 0 |
| `docker.io/library/traefik@1336e85aaed2` | deployed | 0 | 1 | 0 |
| `docker.io/pgvector/pgvector@c29f30688a9a` | deployed | 4 | 88 | 1 |
| `docker.io/tailscale/k8s-operator@9cddfcbe75a7` | deployed | 0 | 1 | 0 |
| `docker.io/tailscale/tailscale@ed6480b33c6e` | deployed | 0 | 0 | 0 |
| `docker.io/viaductoss/ksops@4def9fdd4e2f` | deployed | 3 | 124 | 3 |
| `ecr-public.aws.com/docker/library/redis@2cc044fc5a07` | deployed | 0 | 8 | 0 |
| `flyway/flyway:11.15.0` | base | 2 | 86 | 2 |
| `gcr.io/distroless/static-debian12:nonroot` | base | 0 | 0 | 0 |
| `ghcr.io/astral-sh/uv:0.5.14` | build-copy | unverified | — | — |
| `ghcr.io/dexidp/dex@65b72ca0f4b0` | deployed | 0 | 22 | 0 |
| `ghcr.io/getsops/sops:v3.11.0@6ce00ac946e1` | scheduled | 19 | 340 | 11 |
| `ghcr.io/qdm12/gluetun@fa19cc76b2af` | deployed | 0 | 37 | 0 |
| `golang:1.25-alpine` | base | 0 | 38 | 0 |
| `golang:1.25-bookworm` | base | 18 | 489 | 14 |
| `golang:1.25.6-bookworm` | base | 33 | 1065 | 29 |
| `golang:1.26-alpine` | base | 0 | 0 | 0 |
| `golang:1.27.3-alpine` | base | 0 | 0 | 0 |
| `golang:1.27.3-bookworm` | base | 4 | 270 | 0 |
| `golang:1.27.3-bookworm@972b4110ba0f` | base | 5 | 274 | 1 |
| `mcr.microsoft.com/azure-cli:2.91.0@933eb8dcb81a` | scheduled | 7 | 34 | 7 |
| `mcr.microsoft.com/containernetworking/cilium/cilium-distroless-init@a5a5ee8d7c06` | deployed | 0 | 22 | 0 |
| `mcr.microsoft.com/containernetworking/cilium/cilium-distroless@c203bbc1e2ff` | deployed | 0 | 43 | 0 |
| `mcr.microsoft.com/containernetworking/cilium/operator-generic@13daf6b903ee` | deployed | 0 | 16 | 0 |
| `mcr.microsoft.com/containernetworking/v2/azure-cns@39d3c756c705` | deployed | 0 | 0 | 0 |
| `mcr.microsoft.com/containernetworking/v2/azure-ipam@25b73a2aba04` | deployed | 0 | 0 | 0 |
| `mcr.microsoft.com/containernetworking/v2/azure-iptables-monitor@fef8a373b3b4` | deployed | 0 | 12 | 0 |
| `mcr.microsoft.com/containernetworking/v2/cilium-log-collector@1b63eb8eaad2` | deployed | 0 | 6 | 0 |
| `mcr.microsoft.com/oss/v2/azure/ip-masq-agent-v2@4ef37fcaa490` | deployed | 0 | 0 | 0 |
| `mcr.microsoft.com/oss/v2/azure/workload-identity/webhook@36a2dc63f6dc` | deployed | 0 | 0 | 0 |
| `mcr.microsoft.com/oss/v2/kubernetes-csi/azuredisk-csi@5cd74c0c833b` | deployed | 0 | 0 | 0 |
| `mcr.microsoft.com/oss/v2/kubernetes-csi/azurefile-csi@c8fc59bb7b0d` | deployed | 2 | 2 | 2 |
| `mcr.microsoft.com/oss/v2/kubernetes-csi/csi-node-driver-registrar@f958f91b4903` | deployed | 0 | 0 | 0 |
| `mcr.microsoft.com/oss/v2/kubernetes-csi/livenessprobe@f173bdb53b6c` | deployed | 0 | 0 | 0 |
| `mcr.microsoft.com/oss/v2/kubernetes/apiserver-network-proxy/agent@53442cdfcf41` | deployed | 0 | 0 | 0 |
| `mcr.microsoft.com/oss/v2/kubernetes/autoscaler/addon-resizer@254d2478387b` | deployed | 0 | 0 | 0 |
| `mcr.microsoft.com/oss/v2/kubernetes/autoscaler/cluster-proportional-autoscaler@d7f6f0f8d624` | deployed | 0 | 0 | 0 |
| `mcr.microsoft.com/oss/v2/kubernetes/azure-cloud-node-manager@af4ac15c1842` | deployed | 0 | 0 | 0 |
| `mcr.microsoft.com/oss/v2/kubernetes/coredns@242376d428dd` | deployed | 0 | 0 | 0 |
| `mcr.microsoft.com/oss/v2/kubernetes/metrics-server@df4dd6119bbe` | deployed | 0 | 0 | 0 |
| `nginx:alpine` | base | 1 | 2 | 1 |
| `node:20-alpine` | base | 1 | 25 | 1 |
| `oven/bun:1` | base | 0 | 45 | 0 |
| `oven/bun:1.3-alpine` | base | 0 | 4 | 0 |
| `pgvector/pgvector:0.8.7-pg18-bookworm@c29f30688a9a` | scheduled | 4 | 88 | 1 |
| `postgres:16-alpine` | ci-service | 1 | 25 | 1 |
| `postgres:17` | ci-service | 2 | 88 | 1 |
| `postgres:18.6-alpine@10a5c69a8303` | scheduled | 2 | 26 | 2 |
| `postgres:18.6-bookworm@afc7e2d44132` | base | 4 | 90 | 1 |
| `prodacr1234.azurecr.io/blutag-app@8dc2d7c96636` | deployed | 3 | 20 | 3 |
| `prodacr1234.azurecr.io/blutag-findmy@4750cf5a6f92` | deployed | 9 | 103 | 7 |
| `prodacr1234.azurecr.io/blutag-pointer-push@55a308d7ab43` | deployed | 9 | 103 | 7 |
| `prodacr1234.azurecr.io/blutag-website@608de4f38d4a` | deployed | 1 | 2 | 1 |
| `prodacr1234.azurecr.io/hasadnaa@991138405c7c` | deployed | 3 | 10 | 3 |
| `prodacr1234.azurecr.io/johnson-db-migrations:main-4df7c44` | ci-bootstrap-fallback | unverified | — | — |
| `prodacr1234.azurecr.io/johnson:main-4df7c44` | ci-bootstrap-fallback | unverified | — | — |
| `prodacr1234.azurecr.io/jshipster-bastion@aa2b460743ca` | deployed | 0 | 5 | 0 |
| `prodacr1234.azurecr.io/mashov-mcp@59aa3465b9d1` | deployed | 0 | 0 | 0 |
| `prodacr1234.azurecr.io/multi-whatsapp:main-958740b@b2ea2c5eea76` | scheduled | 1 | 48 | 0 |
| `prodacr1234.azurecr.io/multi-whatsapp@b2ea2c5eea76` | deployed | 1 | 48 | 0 |
| `prodacr1234.azurecr.io/slack-notifications:main-301add0` | scheduled | 2 | 32 | 2 |
| `prodacr1234.azurecr.io/slack-notifications@d14908af5815` | deployed | 2 | 32 | 2 |
| `prodacr1234.azurecr.io/tivtaam-mcp@129a7e8aacd0` | deployed | 0 | 0 | 0 |
| `prodacr1234.azurecr.io/trainings@a0341549f488` | deployed | 3 | 27 | 3 |
| `prodacr1234.azurecr.io/trips@898eba02edba` | deployed | 0 | 1 | 0 |
| `prodacr1234.azurecr.io/webtop-mcp@239d7891942f` | deployed | 0 | 0 | 0 |
| `python:3.11-slim` | base | 0 | 48 | 0 |
| `python:3.13.1-slim-bookworm` | base | 9 | 92 | 7 |
| `quay.io/argoproj/argocd@8e5cc5bb008d` | deployed | 2 | 122 | 2 |
| `quay.io/jetstack/cert-manager-cainjector@d08d2695ad37` | deployed | 0 | 0 | 0 |
| `quay.io/jetstack/cert-manager-controller@62df7490e10b` | deployed | 0 | 0 | 0 |
| `quay.io/jetstack/cert-manager-webhook@85367b4b5a66` | deployed | 0 | 0 | 0 |
| `registry.k8s.io/external-dns/external-dns@a80a146d2540` | deployed | 0 | 0 | 0 |
| `rust:1.88-bookworm` | base | 225 | 2159 | 205 |
| `ubuntu:22.04` | base | 0 | 0 | 0 |
