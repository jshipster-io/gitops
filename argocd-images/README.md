# Argo CD and KSOPS security rebuilds

The deployed pins live in `../argocd-ksops-values.yaml`. Keep Helm chart 10.11.6,
the existing self-management overlay, and the external Helm recovery procedure.
These are dependency rebuilds of Argo CD 3.5.6 and KSOPS 4.5.1, not a new release
or a change to ownership of bootstrap credentials.

`prepare.py` fetches immutable upstream commits and applies reviewed `go.mod` and
`go.sum` patches. Builders are digest-pinned. Go 1.27.3 replaces the vulnerable
embedded Go runtimes. The Argo binary retains its embedded UI, original entrypoint,
users, GPG/SSH tools and executable aliases. Kustomize 5.8.3, Git LFS 3.8.1 and
Helm 4.3.1 are rebuilt too. Dependency patches cover go-jose, compress, x/net and
their compatible dependencies; KSOPS and Helm also patch gRPC. Remove/rebase these
patches when upstream releases incorporate the fixes.

Argo's `common.version` linker value must be a bare release number (`3.5.6`):
`GetVersion` adds the `v` prefix and commit metadata itself. Put vendor information
in `common.extraBuildInfo`. A malformed value can leave rendering and the HTML UI
working while the REST gateway rejects API/login requests. CI checks the actual
linked version's SemVer, not merely the version command's exit status.

The Argo image upgrades installed Ubuntu packages and removes the unused Pebble
supervisor inherited from Ubuntu; Argo starts with `tini`. KSOPS contains only
the native installer/plugin on non-root distroless Debian 13. It does not ship a
second Kustomize or duplicate `kustomize-sops` executable.

## Automatic delivery

`.github/workflows/argocd-images.yaml` runs on image-input changes on main or a
manual workflow dispatch. No environment approval or production age key is used.

1. Build both linux/amd64 images with SBOM and provenance into ACR. The GitOps
   repository's immutable main-branch OIDC subject uses `prod-ci-gitops`, with
   registry-scoped AcrPush; no registry password or Azure client secret is stored.
2. Scan each exact digest using the checksum-pinned Trivy and a fresh database.
   Scanner errors and fixable **critical or high** findings block this control
   plane pipeline. Other application pipelines retain their existing default
   fixable-critical gate. Passing either gate does not mean vulnerability-free.
   Only sanitized summaries and seven-day digest receipts are published.
3. Install KSOPS as 65532 and render an age-encrypted synthetic Secret as 999.
   Test missing-key rejection, Helm rendering and bundled tool startup with no
   container network, no capabilities and read-only roots. These disposable keys
   have no relationship to production credentials.
4. Promote only the two validated image pins to main. Reject superseded build
   inputs, preserve unrelated app updates, and bound concurrent-push retries.
   Use the existing narrowly scoped GitOps App token, automatically revoked after
   the job, so the normal push event creates the required GitOps check. A
   GITHUB_TOKEN push followed by workflow dispatch failed the protected-branch
   handoff in rehearsal; do not bypass protection or introduce a PAT. The normal main → validated production → Argo
   path remains the only delivery path.

Main-branch GitOps validation uses short-lived OIDC/ACR authentication to pull the
private installer before its isolated runtime test. PR and branch validation
remain credential-free static checks; trusted main must pass the runtime gate
before promotion to production. Container tests receive no registry credentials.
Main also repeats the full paired rendering/version test for the desired pins,
so a values-only rollback cannot reintroduce a malformed binary unnoticed.

## Runtime and recovery verification

Preserve installer UID/GID 65532, repo-server UID 999, the 64Mi tools volume,
read-only plugin mount and existing age-key path. The installer never mounts the
age key. The repo-server continues using its own Kustomize and no service-account
token. The bounded pool retains its existing singleton repo-server update strategy.

For a changed runtime, run `scripts/verify-ksops-bootstrap.py --run` with an explicit
trusted owner KUBECONFIG. It creates and removes only a disposable fixture Secret
and Job. Use `scripts/verify-argocd-api-candidate.py --run --image <validated-digest>
--expected-version <version>` to rehearse REST version, authenticated login/read,
unauthenticated denial and embedded UI before accepting a candidate. It uses the
existing server identity in an isolated, five-minute-bounded Pod, refuses any
production Service selector match, and cleans up the Pod and local tunnel. This
owner-run check uses existing protected credentials only in memory, never in CI.
Check the intended running digests, fresh production rendering, all
Application sync/health, protected Secret identities/data fingerprints, UI and
private access separately. Do not print Secret contents or rendered manifests.

Use `scripts/argocd_recovery.py` from a known-good validated checkout for the
external Helm drill, then restore the saved automatic policies with `resume`.
Follow `../docs/argocd-self-management.md`; never run competing Helm reconciliation
or delete/recreate bootstrap credentials. A successful build or synthetic fixture
alone does not establish production readiness or successful Helm recovery.
When provenance changes an OCI index but the cached runtime reports an older index,
resolve both linux/amd64 manifests before comparing content identity.
