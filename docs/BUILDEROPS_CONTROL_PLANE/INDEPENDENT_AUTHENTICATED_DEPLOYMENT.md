---
name: Independent Authenticated Deployment
description: Deploy BuilderOps as its own authenticated Demerzel service and operations lifecycle.
task_id: BCP-02
source_anchor: docs/BUILDEROPS_CONTROL_PLANE/README.md :: Target boundary
parent_capability: BuilderOps independent control plane
prerequisites: [BCP-01]
depends_on: [POSTGRES_TRANSACTION_KERNEL.md]
can_parallelize_with: [BCP-03]
---

# Independent Authenticated Deployment

## Purpose

BuilderOps currently rides inside Product FastAPI/startup and has no service-specific authentication,
Compose project, release pin, database/volume, migrations, health, backup, or restore lifecycle.
Demerzel already has Docker/PostgreSQL/Tailscale capability that can be reused without sharing
Product ownership.

## What This Task Does

- create a separate BuilderOps FastAPI/service entrypoint over the BCP-01 store port;
- require encrypted tailnet transport and revocable, scoped client credentials; distinguish normal,
  privileged executor, and operator scopes;
- keep raw client/database/GitHub/model credentials in host secret stores only; persist only secret
  references, non-secret fingerprints, scopes, and rotation generations;
- create a BuilderOps-only Compose project with its own API, outbox worker, migration gate,
  PostgreSQL service/database/role/volume/secrets, and immutable release pin;
- provide independent deploy/rollback receipts and a host probe;
- implement `/healthz`, `/readyz`, and secret-safe status/metrics for database/schema, outbox age and
  dead letters, lease conflicts, auth failures, rate limits/credential state, and executor heartbeat;
- provide scheduled encrypted full backups plus WAL archiving on an operator-chosen cadence to an
  independent recovery target outside Demerzel's primary host and storage failure domains,
  independently recoverable key custody or KMS authorization outside those failure domains,
  retention, documented point-in-time restore, and an automated restore-from-backup drill with
  Demerzel's host secret store unavailable (ADR-0062 A1: recovery durability is asynchronous and
  never gates acknowledgement);
- run the BuilderOps-only Compose project and database on a separate VM/container engine on
  Demerzel, outside the `pkm-*` container-VM failure domain, so Product deploys, restarts, resource
  pressure, and container-VM lifecycle events cannot stop the builder plane (ADR-0062 A2);
- wire BuilderOps `/healthz` into the operator alerting path so control-plane outages are observed
  rather than discovered (ADR-0062 A2); and
- prove Product Compose and Product credentials/config are not dependencies.

## Concretely

The slice adds a BuilderOps-only Compose invocation and service entrypoint such that an operator can
deploy a pinned image, wait for migrations, call authenticated `/healthz` and `/readyz`, inspect
secret-safe status, take a full backup, independently recover its decryption capability, restore it
plus archived WAL to the latest archived point in an isolated project while Demerzel's host secret
store is unavailable, and change to a compatible BuilderOps image without rewinding authoritative
data or running a `pkm-*` Compose command — while the `pkm-*` stacks stay stopped, restarted, or
under load without affecting any of it.

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
- The BuilderOps-only Compose project and database run on a separate VM/container engine from the
  `pkm-*` stacks; no Product lifecycle event can stop, restart, or resource-starve the builder plane
  (ADR-0062 A2). A native host service is outside this task's selected deployment contract.
- Do not cut production clients or expose the service as authority until BCP-03/04/05 gates pass.

## Acceptance Criteria

- [ ] An authenticated client can exercise health and one idempotent record/lease flow through the
  independent service, while missing/invalid/insufficient credentials fail closed.
  Verify: `tests/builderops/control_plane/test_service_auth.py::test_scoped_api_auth_fails_closed`.
- [ ] BuilderOps Compose uses a distinct project, PostgreSQL service/database/role/volume/secrets,
  migrations, API/worker, and release pin without importing Product Compose lifecycle.
  Verify: `tests/ops/test_builderops_compose_contract.py::test_builderops_compose_is_lifecycle_isolated`.
- [ ] Product services can remain stopped while BuilderOps reaches ready, and BuilderOps can remain
  stopped while Product reaches its own readiness without attempting to start it.
  Verify: `tests/ops/test_builderops_lifecycle_isolation.py::test_product_and_builderops_start_stop_independently`.
- [ ] Readiness/status reports database/schema/authority epoch, outbox/dead-letter, lease, auth,
  rate-limit, and executor-heartbeat state without exposing secrets.
  Verify: `tests/builderops/control_plane/test_service_health.py::test_readiness_and_status_cover_required_dependencies_without_secrets`.
- [ ] Deploy and rollback use a BuilderOps-specific immutable pin and emit receipts that identify
  image SHA, schema version, and authority epoch without restoring an older authoritative snapshot.
  Verify: `tests/ops/test_builderops_deploy_contract.py::test_deploy_and_rollback_receipts_bind_pin_schema_and_epoch`.
- [ ] The BuilderOps-only Compose project and database run on a separate VM/container engine from
  the `pkm-*` stacks, and
  stopping, restarting, or load-cycling the Product stacks leaves BuilderOps ready and mutating
  normally; a co-resident recovery target fails `/readyz`, while a stalled backup/WAL-archiving
  pipeline raises a loud alert/status condition without blocking acknowledgement.
  Verify: `tests/ops/test_builderops_failure_domain.py::test_builder_plane_survives_product_stack_lifecycle_and_alerts_on_stalled_archiving`.
- [ ] With Demerzel's host secret store unavailable, independently recoverable key/KMS custody can
  decrypt an encrypted full backup plus archived WAL and restore a disposable database to the latest
  archived point with passing schema, count, integrity, outbox/lease, and readiness checks.
  Verify: `tests/ops/test_builderops_backup_restore.py::test_restore_from_backup_without_demerzel_secret_store`.
- [ ] Negative scans of PostgreSQL, outbox payloads, receipts, artifacts, logs/metrics, WAL,
  encrypted backup bytes, and a restored database find no raw client/database/GitHub/model/
  recovery-decryption credential; only non-secret reference/fingerprint/scope/rotation metadata is
  durable.
  Verify: `tests/security/test_builderops_secret_persistence.py::test_raw_credentials_never_enter_durable_state_or_restored_backup`.

## Out of Scope

- final production cutover;
- migration of legacy stores;
- Product route removal; and
- source-repository extraction.

## How to Verify (Pre-Merge)

- render/validate Compose config under the dedicated project name;
- run auth-negative, credential-redaction, durable-state, WAL, and restored-backup secret scans;
- stop/restart the Product stacks and stall WAL archiving to prove builder-plane independence and
  loud alerting, then execute full backup + archived-WAL restore to the latest archived point in an
  isolated test project with Demerzel's host secret store unavailable; and
- run `ruff check app tests` plus focused ops tests.

## Related Docs

- `docs/adr/ADR-0062-builderops-ecosystem-wide-enabling-system.md`
- `docs/BUILDEROPS_CONTROL_PLANE/README.md`
- `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md`

## Related GitHub Issues

- [#3790](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3790), blocked on BCP-01.
