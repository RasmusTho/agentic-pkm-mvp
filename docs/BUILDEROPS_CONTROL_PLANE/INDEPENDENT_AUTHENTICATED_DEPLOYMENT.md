---
name: Independent Authenticated Deployment
description: Deploy BuilderOps as its own authenticated Demerzel service and operations lifecycle.
task_id: BCP-02
github_issue: 3790
source_anchor: docs/BUILDEROPS_CONTROL_PLANE/README.md :: Target boundary
parent_capability: BuilderOps independent control plane
prerequisites: [BCP-01]
depends_on: [POSTGRES_TRANSACTION_KERNEL.md]
can_parallelize_with: [BCP-03]
---

# Independent Authenticated Deployment

## Implementation Status

Implemented by #3790 at the repo/deployment-contract level: the independent FastAPI factory,
scoped/revocable credential verifier, durable-payload secret guard, PostgreSQL migration gate,
API/worker/DB Compose project, separate Docker-engine preflight, immutable image pins,
authenticated probes, Tailscale Serve TLS termination, secret-safe live status/metrics,
failure-safe deploy/rollback receipts, a dedicated PostgreSQL 16 + WAL-G image, WAL-G backup/WAL
archive wrappers, structural recovery-target validation, and an image-level encrypted restore
gate are present. The gate performs a real full backup, archived-WAL recovery into a disposable
PostgreSQL instance, restored-data/integrity checks, and negative credential scans without using
Demerzel host secrets. Restore activation increments the database-owned authority epoch, invalidates
leases, marks claimed effects unknown, and keeps the executor fenced until reconciliation.

No production authority or client cutover is claimed here. The committed zero digests are deliberate
non-runnable placeholders; an operator-provided release pin, second Demerzel engine, off-host target,
independent recovery custody, successful live restore receipt, and BCP-03/04/05/06 gates are still
required before activation.

## Local control-plane durability posture

The governed local `builderops-control-plane` Compose deployment is rebuildable Builder System
operational state, not an independent durable knowledge or delivery authority. Its PostgreSQL
configuration sets `archive_mode = off` with an empty `archive_command`; the local Compose project
does not bind WAL archive credentials, a recovery-egress network, or a backup service. The retained
WAL-G/archive and restore tooling belongs to the future independently authenticated deployment path
and is not enabled by this local posture.

The database health check fails loudly when archive settings drift, `pg_wal` exceeds its bounded
local threshold, or the data volume reaches its bounded usage threshold. The existing host probe
inspects that database health and sends its normal outage notification, while installation unloads
the obsolete scheduled-backup agent. This containment prevents local WAL retention from exhausting
shared disk; it does not provide, imply, or verify off-host backup, PITR, or restore capability.

## Purpose

BuilderOps currently rides inside Product FastAPI/startup and has no service-specific authentication,
Compose project, release pin, database/volume, migrations, health, backup, or restore lifecycle.
Demerzel already has Docker/PostgreSQL/Tailscale capability that can be reused without sharing
Product ownership.

## What This Task Does

- create a separate BuilderOps FastAPI/service entrypoint over the BCP-01 store port;
- require encrypted tailnet transport and revocable, scoped client credentials; distinguish normal,
  privileged executor, and operator scopes;
- terminate tailnet-only HTTPS with Tailscale Serve and verify that Funnel/public exposure is not
  enabled before a deployment is accepted;
- keep raw client/database/GitHub/model credentials in host secret stores only; persist only secret
  references, non-secret fingerprints, bounded token lengths, scopes, and rotation generations;
- create a BuilderOps-only Compose project with its own API, outbox worker, migration gate,
  PostgreSQL service/database/role/volume/secrets, and immutable release pin;
- keep API, migration, and worker services on an internal-only network while granting outbound
  recovery-target access only to the PostgreSQL WAL archiver and scheduled backup service;
- provide independent deploy/rollback receipts that bind both the control-plane and
  PostgreSQL/WAL-G image digests, plus a host probe with separate least-privilege readiness and
  status credentials;
- implement `/healthz`, `/readyz`, and secret-safe status/metrics for database/schema, outbox age and
  dead letters, lease conflicts, auth failures, rate limits/credential state, and executor heartbeat;
- provide scheduled encrypted full backups plus WAL archiving on an operator-chosen cadence to an
  independent recovery target outside Demerzel's primary host and storage failure domains,
  independently recoverable key custody or KMS authorization outside those failure domains,
  retention, documented point-in-time restore, and an automated restore-from-backup drill with
  Demerzel's host secret store unavailable (ADR-0062 A1: recovery durability is asynchronous and
  never gates acknowledgement);
- build the control-plane and PostgreSQL/WAL-G images in CI and run the encrypted full-backup plus
  archived-WAL restore gate against those exact candidate images before publication, with no
  post-gate rebuild;
- deliver the fail-closed separate-engine preflight and deployment tooling for the BuilderOps-only
  project on Demerzel, outside the `pkm-*` container-VM failure domain; live host activation and
  Product-load/BuilderOps-readiness proof remain an operator-gated successor (ADR-0062 A2);
- wire BuilderOps `/healthz` into the operator alerting path so control-plane outages are observed
  rather than discovered (ADR-0062 A2); and
- prove Product Compose and Product credentials/config are not dependencies.

## Concretely

The slice adds a BuilderOps-only Compose invocation and service entrypoint such that an operator can
deploy a pinned pair of restore-proved images, wait for migrations, call authenticated `/healthz`
and `/readyz`, inspect secret-safe status, take a full backup, independently recover its decryption
capability, restore it plus archived WAL to the latest archived point in an isolated project while
Demerzel's host secret store is unavailable, and change to compatible BuilderOps images without
rewinding authoritative data or running a `pkm-*` Compose command. This repository slice proves the
deployment and failure-domain contracts; it does not claim the later live two-engine/load receipt.

## Why This Matters

PostgreSQL alone does not create an independent control plane. Without a separate lifecycle and
trust unit, Product deployment would still own BuilderOps availability, credentials, and recovery.

## Source Anchors

- `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md :: Environment matrix`
- `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md :: Deploy procedure`
- `docs/SECURITY.md :: API keys & endpoints`

## SBS Impact

Builder System deployment work with a boundary impact: it establishes the enabling system's own
trust/lifecycle unit and forbids Product Runtime ownership. It does not create a Product subsystem.

## Constraints

- BuilderOps Compose project/database/volume/role/secrets/pin/migrations remain distinct from
  `pkm-dev`, `pkm-test`, and `pkm-prod`.
- Only recovery producers (PostgreSQL WAL archiving and the backup job) receive recovery-target
  egress; API, migration, and worker services remain internal-only.
- Tailnet membership alone is not authentication; no anonymous mutation or Product API key reuse.
- Raw client, database, GitHub, merge, model/session, and recovery-decryption credentials are never
  returned to clients or persisted in repo config, PostgreSQL, outbox payloads, receipts, artifacts,
  logs/metrics, WAL, or BuilderOps backups/restores. Durable records carry non-secret references and
  scope metadata only. Recovery key/KMS custody must remain usable after total loss of Demerzel's host
  secret store and primary storage.
- `/healthz` is process liveness; `/readyz` fails on unavailable DB, wrong schema/epoch, an
  authority-threatening outbox condition, or a recovery target co-resident with Demerzel's primary
  host/storage failure domain (structural misconfiguration stays fail-closed; ADR-0062 A1). Stalled
  or lagging backup/WAL archiving surfaces as a loud status/alert condition, not an acknowledgement
  gate.
- Acknowledgement, replay, dependent transitions, outbox claims, and external effects require the
  local PostgreSQL commit only (ADR-0062 A1).
- A persistent volume or snapshot alone is not accepted as recoverability. Full backup + archived
  WAL must restore to the latest archived point; backup/restore negative scans must also prove the
  credential exclusion boundary.
- A candidate image is not publishable unless the image-level restore gate proves the real WAL-G,
  PostgreSQL, migration, recovery-fence, and credential-exclusion paths together.
- The BuilderOps-only Compose project and database run on a separate VM/container engine from the
  `pkm-*` stacks; no Product lifecycle event can stop, restart, or resource-starve the builder plane
  (ADR-0062 A2). A native host service is outside this task's selected deployment contract.
- Do not cut production clients or expose the service as authority until BCP-03/04/05 gates pass.
- PostgreSQL's custom `config_file` bypasses the official image's default `listen_addresses='*'`
  handling, so `config/builderops/postgresql.conf` must set `listen_addresses = '*'` explicitly or
  `migrate`/`api`/`worker` cannot connect at all. This is bounded by the `builderops-internal`
  network's `internal: true` declaration, not host exposure; do not "harden" it back to a narrower
  value without re-verifying the network is still internal-only, and do not publish a host port or
  attach `db` to a non-internal network.

## Acceptance Criteria

- [ ] An authenticated client can exercise health and one idempotent record/lease flow through the
  independent service, while missing/invalid/insufficient credentials fail closed.
  Verify: `tests/builderops/control_plane/test_service_auth.py::test_scoped_api_auth_fails_closed`.
- [ ] BuilderOps Compose uses a distinct project, PostgreSQL service/database/role/volume/secrets,
  migrations, API/worker, and release pin without importing Product Compose lifecycle.
  Verify: `tests/ops/test_builderops_compose_contract.py::test_builderops_compose_is_lifecycle_isolated`.
- [ ] Repository lifecycle commands keep Product and BuilderOps projects independent: neither
  start/stop path imports or attempts to start the other. Live two-engine lifecycle/load proof on
  Demerzel remains an operator-gated successor receipt.
  Verify: `tests/ops/test_builderops_lifecycle_isolation.py::test_product_and_builderops_start_stop_independently`.
- [ ] Readiness/status reports database/schema/authority epoch, outbox/dead-letter, lease, auth,
  rate-limit, and executor-heartbeat state without exposing secrets.
  Verify: `tests/builderops/control_plane/test_service_health.py::test_readiness_and_status_cover_required_dependencies_without_secrets`.
- [ ] Deploy accepts only a GitHub-attested main-workflow receipt binding one source SHA to both the
  restore-proved `linux/amd64` control-plane and PostgreSQL/WAL-G digests. Rollback uses the prior
  trusted dual pin; deployment receipts identify both digests, schema version, and authority epoch
  without restoring an older authoritative snapshot.
  Verify: `tests/ops/test_builderops_deploy_contract.py::test_deploy_and_rollback_receipts_bind_pin_schema_and_epoch`.
- [ ] Repository preflight and Compose contracts require a BuilderOps-only project, database, and
  separate container-engine identity from the `pkm-*` stacks. A co-resident recovery target fails
  `/readyz`, while a stalled backup/WAL-archiving pipeline raises a loud alert/status condition
  without blocking acknowledgement. Live Product load-cycle survival is deferred to the same
  operator-gated two-engine receipt.
  Verify: `tests/ops/test_builderops_failure_domain.py::test_builder_plane_survives_product_stack_lifecycle_and_alerts_on_stalled_archiving`.
- [ ] With Demerzel's host secret store unavailable, independently recoverable key/KMS custody can
  decrypt an encrypted full backup plus archived WAL and restore a disposable database to the latest
  archived point with passing schema, count, integrity, outbox/lease, and readiness checks.
  Verify: `tests/ops/test_builderops_backup_restore.py::test_restore_from_backup_without_demerzel_secret_store`.
- [ ] Negative scans of PostgreSQL, outbox payloads, receipts, artifacts, logs/metrics, WAL,
  encrypted backup bytes, and a restored database find no raw client/database/GitHub/model/
  recovery-decryption credential; only non-secret reference/fingerprint/token-length/scope/rotation
  metadata is durable.
  Verify: `tests/security/test_builderops_secret_persistence.py::test_raw_credentials_never_enter_durable_state_or_restored_backup`.

## Out of Scope

- final production cutover;
- migration of legacy stores;
- Product route removal; and
- source-repository extraction.

## How to Verify (Pre-Merge)

- render/validate Compose config under the dedicated project name;
- run auth-negative, credential-redaction, durable-state, WAL, and restored-backup secret scans;
- validate the repository lifecycle/failure-domain contracts and stall WAL archiving to prove loud
  alerting; the later operator-gated host receipt owns Product load-cycle survival. Execute full
  backup + archived-WAL restore to the latest archived point in an isolated test project with
  Demerzel's host secret store unavailable; and
- run `ruff check app tests` plus focused ops tests.

## Related Docs

- `docs/adr/ADR-0062-builderops-ecosystem-wide-enabling-system.md`
- `docs/BUILDEROPS_CONTROL_PLANE/README.md`
- `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md`

## Related GitHub Issues

- [#3790](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3790), blocked on BCP-01.
