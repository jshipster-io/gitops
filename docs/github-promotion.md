# GitHub App promotion

The 2026-10-31 migration replaces the shared `GITOPS_PAT` in all 18 image-publishing repositories with short-lived installation tokens. Azure publishing continues to use OIDC independently.

## Credential boundaries

| App | Installation | Repository access | Permissions | Signing-key storage |
| --- | --- | --- | --- | --- |
| jshipster-gitops-promotion (5556540) | 177250155 | gitops only | Contents write, Metadata read | Organization `GITOPS_APP_PRIVATE_KEY`, selected 18 consumers |
| jshipster-private-dependency (5556586) | 177252558 | FindMy.py only | Contents read, Metadata read | `blutag-findmy` repository `FINDMY_APP_PRIVATE_KEY` |

Client IDs are public Actions variables, respectively `GITOPS_APP_CLIENT_ID` (selected organization consumers) and `FINDMY_APP_CLIENT_ID` (Blutag FindMy only). The installation and consumer contract is in `github-promotion/consumers.json`.

Each trusted main job mints its own token with the SHA-pinned official `actions/create-github-app-token` action. It explicitly selects owner, repository and Contents permission. Tokens expire after one hour and the action revokes them when the job ends. Revocation log messages are checked by the audit script; a successful cleanup step alone can hide a revocation warning. No PAT fallback is configured.

The App signing keys remain long-lived roots of trust. They are limited to these installations, stored as scoped Actions secrets and never committed, passed in command arguments, or baked into images. The Apps have no Actions-secrets, administration, workflow-editing, status or checks-write permissions. Private Apps can be installed only within this organization. As usual, public repositories remain publicly readable.

## Automatic deployment gate

Service CI publishes its image and updates GitOps intake `main`. Promotion jobs run only on main, exclude pull requests, and have ambient `contents: read`; the App token supplies the separate GitOps write permission. Legacy standalone pushes now retry bounded rebase conflicts. Missing credentials fail promotion rather than silently skipping it.

The existing GitOps workflow validates schemas, Pod Security, network policy and workload identity without deployment credentials. Its dependent main-only promotion job uses the built-in `GITHUB_TOKEN`, checks freshness and fast-forward ancestry, and advances `production`. No human reviewer or environment approval is required.

Production still requires `gitops-validation` from GitHub Actions App 15368, including for administrators. Force pushes and branch deletion remain forbidden. The service App cannot edit the gate workflow or forge the required check. Contents permission itself is repository-wide, not branch- or path-scoped; do not claim otherwise. GitHub does not accept its built-in Actions integration as an installed-App push-allowlist member. An empty allowlist would block the working production job; retain the required-check gate.

## Private dependency builds

FindMy uses the separate read-only App. A real `git ls-remote` check verifies access independently of Docker cache. Source checkout does not persist its token, preventing duplicate Authorization headers. Docker receives the dependency token through a required BuildKit secret and uses process-environment Git headers; credentials never enter Git URLs or cache configuration. The builder does not leave a `.gitconfig` credential file.

## Read-only automatic audit

Run from this repository with the owner's authenticated `gh` CLI and PyYAML:

```sh
python3 scripts/verify-github-promotion.py --check-runs
```

The script checks exact installation repositories and permissions, selected consumer grants, workflow token scope and main/PR guards, production protection and automatic-gate settings, successful current-main CI, actual token minting and revocation logs, and the uncached dependency read. It retrieves no secret values and does not change cloud or repository state.

For a new service, add its repository/workflow to the consumer contract, add selected access to the App client-ID variable and signing-key secret, and follow the workspace scaffold skill. Preserve existing grants; do not grant the App access to the application repository or grant it workflow/admin permissions.

## Migration evidence

All 18 source CI runs below passed with executed App mint, promotion and cleanup steps. Diagnostic tokens confirmed the exact permissions, one-hour expiry, denied access to unrelated private repositories and Actions secrets, and were immediately revoked. The Webtop canary also triggered a successful automatic GitOps gate and production promotion (run 41216184403).

| Repository | Verified migration run |
| --- | --- |
| ANPR-Shikmim | [41216754181](https://github.com/jshipster-io/ANPR-Shikmim/actions/runs/41216754181) |
| blutag-app | [41216738867](https://github.com/jshipster-io/blutag-app/actions/runs/41216738867) |
| blutag-findmy | [41217049737](https://github.com/jshipster-io/blutag-findmy/actions/runs/41217049737) |
| blutag-pointer-push | [41216741623](https://github.com/jshipster-io/blutag-pointer-push/actions/runs/41216741623) |
| blutag-website | [41216739788](https://github.com/jshipster-io/blutag-website/actions/runs/41216739788) |
| dirtbike-specialist | [41216750432](https://github.com/jshipster-io/dirtbike-specialist/actions/runs/41216750432) |
| drc | [41216739250](https://github.com/jshipster-io/drc/actions/runs/41216739250) |
| gen-rag | [41216751828](https://github.com/jshipster-io/gen-rag/actions/runs/41216751828) |
| hasadnaa | [41216749997](https://github.com/jshipster-io/hasadnaa/actions/runs/41216749997) |
| ids | [41216744895](https://github.com/jshipster-io/ids/actions/runs/41216744895) |
| johnson | [41216754052](https://github.com/jshipster-io/johnson/actions/runs/41216754052) |
| mashov-mcp | [41216747720](https://github.com/jshipster-io/mashov-mcp/actions/runs/41216747720) |
| multi-whatsapp | [41216745447](https://github.com/jshipster-io/multi-whatsapp/actions/runs/41216745447) |
| padel-booking | [41216743010](https://github.com/jshipster-io/padel-booking/actions/runs/41216743010) |
| slack-notifications | [41216748023](https://github.com/jshipster-io/slack-notifications/actions/runs/41216748023) |
| tivtaam-mcp | [41216744939](https://github.com/jshipster-io/tivtaam-mcp/actions/runs/41216744939) |
| trips | [41216750175](https://github.com/jshipster-io/trips/actions/runs/41216750175) |
| webtop-mcp | [41215975838](https://github.com/jshipster-io/webtop-mcp/actions/runs/41215975838) |

The independent PostgreSQL maintenance may hold Argo reconciliation and application writers. Preserve that hold; successful CI and production-branch promotion do not prove that a held workload has reconciled. Existing owner CLI and Argo repository credentials are separate from this migration.

## Legacy credential retirement

The guarded retirement run [41217768930](https://github.com/jshipster-io/webtop-mcp/actions/runs/41217768930) checked all 18 successful migration runs and verified that the legacy token was distinct from owner CLI and Argo repository credentials. GitHub accepted revocation of that exact credential, and an authenticated read with it then returned HTTP 401. The obsolete organization secret and one-time retirement workflow were removed afterward. This is credential invalidation evidence, not merely deletion of a secret reference.

Unrelated owner, Argo CD, upstream-sync and downstream-dispatch credentials were preserved. No workload, network policy, database maintenance hold or deployment approval requirement was changed by this migration.
