# PostgreSQL 18 recovery and acceptance

The upgrade uses PostgreSQL 18.6 and pgvector 0.8.7 on a separate retained PVC.
The original PostgreSQL 17.11 StatefulSet is retained at zero replicas. Never
start it as a writer after PostgreSQL 18 has accepted production writes.

## Recovery material

- Original PVC: `postgres-data-shared-postgres-0` (16 GiB; PV reclaim policy Retain).
- Target PVC: `postgres-data-shared-postgres-18-0` (16 GiB; PV reclaim policy Retain).
- Full initial snapshot: `prod-rg/pg17-preupgrade-20261031-initial`.
- Private storage: `jshipsterprod410479`, container `pg-backups`, prefix
  `upgrade/20261031T1335Z/`. Archives are age-encrypted to the existing owner key.
- Each recovery set contains custom-format database dumps, globals including
  password verifiers, encrypted configuration/credential material, and SHA-256
  manifests. Restore the globals before database objects, retaining owners and ACLs.
- Upgrade archives are excluded from the daily 10-day deletion policy. Keep the
  original disk, snapshots, and upgrade archives at least through 2026-11-30;
  deletion requires a separate cleanup decision. Test disks are not production.

The 2026-09-01 recovery references in README are historical evidence, not proof
that those old objects still exist. Use freshly verified recovery artifacts.

## Cutover procedure

1. Record GitOps revisions, replicas, CronJob suspension, network policies,
   credentials/TLS references, database inventory and storage IDs. Pause relevant
   Argo reconciliation before modifying maintenance state.
2. Stop every database writer and scheduler, fence client ingress, and terminate
   remaining sessions. Temporarily allow a maintenance connection to `template0`
   to capture its contents as well as `template1`; restore its original connection
   flag before snapshotting and before reopening the target.
3. Take fresh custom-format dumps and globals, capture read-only comparison
   evidence, then cleanly stop PostgreSQL 17. Take a full final disk snapshot.
   Verify uploaded/downloaded archive hashes and snapshot completion.
4. Restore into a clean PostgreSQL 18 data directory on the new PVC. Do not reuse
   a PostgreSQL 17 data directory. Preserve the rehearsal copy separately until
   acceptance. Skip only the already-created `CREATE ROLE postgres` statement;
   retain its ALTER ROLE statement and all password verifiers.
5. Restore ordinary databases with `pg_restore --create --exit-on-error`. Recreate
   `postgres` while connected to `template1`, so its database ACLs are restored.
   Restore template contents into initialized PostgreSQL 18 templates and verify
   their ownership, ACLs, locale, settings and original connection flags.
6. Compare frozen-source and target evidence. Test every known credential through
   TLS verify-full, verify authorization denials, extensions, persistence and
   application readiness. Unexpected restore errors or data differences block cutover.
7. Apply the reviewed service/network-policy/manifests, route the unchanged service
   hostname to `shared-postgres-18`, and resume writers gradually. Reconcile the
   final GitOps revision before restoring automatic reconciliation.
8. Require 24 hours of healthy operation and a complete scheduled backup cycle.
   Keep recovery points after acceptance; acceptance does not authorize deletion.

## Data and access verification

`scripts/verify-postgres-upgrade.py capture` runs the read-only SQL inventory on
each connectable database. Evidence includes table-content fingerprints and exact
counts, sequences, large objects, columns/defaults, constraints, indexes, functions,
triggers, RLS policies, ownership, ACLs, role memberships, settings and password
verifier fingerprints. It emits no password or verifier values.

```sh
python3 scripts/verify-postgres-upgrade.py capture \
  --kubeconfig "$KUBECONFIG" --context jshipster \
  --pod shared-postgres-0 --output /protected/source.json
python3 scripts/verify-postgres-upgrade.py capture \
  --kubeconfig "$KUBECONFIG" --context jshipster \
  --pod shared-postgres-18-0 --output /protected/target.json
python3 scripts/verify-postgres-upgrade.py compare /protected/source.json /protected/target.json
```

Keep writers stopped for an exact comparison. PostgreSQL 18 NOT NULL catalog
representation is normalized through column flags. Only pgvector 0.8.6/0.8.7 is
an allowed extension-version difference. Rebuilt approximate vector indexes may
have different physical layouts; test vector dimensions and query behavior.

## Ongoing backup recovery

Daily backups cover every retained application database, including `anpr` and
`mashov_mcp`. PostgreSQL clients are pinned to 18.6. Owner/ACL information is retained.
`pg-backup-cluster-recovery` additionally protects globals, database settings,
`postgres`/`template1` contents, live TLS/CA files and database credentials in an
age-encrypted SOPS binary envelope. Its plaintext staging uses memory-backed storage.
Recovery bundles expire after 35 days; daily data backups retain their 10-day policy.

Routine dumps do not include CREATE DATABASE. Recreate the database with the
owner/encoding/locale and database ACL/settings from the matching recovery bundle,
then restore its SQL as an administrator. Never restore over a live database to
test a backup. Verify by downloading and restoring to an isolated database and
comparing data and grants. Use the owner recovery key to decrypt the SOPS envelope;
do not print decrypted material or put it in Git.

Bootstrap is no longer an automatic PostSync resource: it rewrites role passwords
and grants and must not run over a restored cluster. Retain it only as manual
bootstrap scaffolding. TLS reload continues to use its existing restricted role.

## Rollback boundary

Before writes resume, return the service selector to the unchanged PostgreSQL 17
server, restore its policy/replica state, and verify clients before resuming them.
After writes resume, stop writers and preserve PostgreSQL 18 first. A selector
reversal to the stale 17 copy would discard committed writes; use forward repair
or an independently validated reverse migration instead.

Snapshot restores must use unique disk names in the AKS node resource group.
An initial rehearsal with identically named disks in two resource groups hit a
stale attachment/I/O failure; the uniquely named restore booted successfully and
passed `pg_amcheck --all --install-missing --heapallindexed`.

The backup uploader uses the existing container-scoped `pg-backups` Azure
workload identity. The recovery job uses a separate Kubernetes service account
in `postgres`, with an exact federated subject managed in
`terraform/postgres_backup_identity.tf`. It does not use a storage account key.
The archive includes raw PostgreSQL configuration, effective settings and HBA
rules, globals, system-database dumps, and dereferenced TLS/credential files.

Rehearsal on 2026-10-31 verified the clean PostgreSQL 17 disk-snapshot restore,
all ten downloaded application-backup restores with data/catalog comparisons,
and an actual globals restore from the encrypted recovery archive. All 23
credential references passed TLS hostname validation; denied cross-database
access and restricted TLS reload were also tested. Final frozen-source
comparison and the 24-hour production observation remain cutover gates.
