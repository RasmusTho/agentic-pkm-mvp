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
- create a BuilderOps-only Compose project with its own API, outbox worker, migration gate,
  PostgreSQL service/database/role/volume/secrets, and immutable release pin;
- provide independent deploy/rollback receipts and a host probe;
- implement `/healthz`, `/readyz`, and secret-safe status/metrics for database/schema, outbox age and
  dead letters, lease conflicts, auth failures, rate limits/credential state, and executor heartbeat;
- provide scheduled encrypted backup outside the database volume, retention, documented restore,
  and an automated restore drill into a disposable database; and
- prove Product Compose and Product credentials/config are not dependencies.

## Concretely

The slice adds a BuilderOps-only Compose invocation and service entrypoint such that an operator can
deploy a pinned image, wait for migrations, call authenticated `/healthz` and `/readyz`, inspect
secret-safe status, take a backup, restore it into an isolated project, and roll back without
running a `pkm-*` Compose command.

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
- Database and merge credentials are never returned to API clients or stored in repo config.
- `/healthz` is process liveness; `/readyz` fails on unavailable DB, wrong schema/epoch, or an
  authority-threatening outbox condition.
- A persistent volume is not accepted as backup.
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
  image SHA, schema version, and authority epoch.
  Verify: `tests/ops/test_builderops_deploy_contract.py::test_deploy_and_rollback_receipts_bind_pin_schema_and_epoch`.
- [ ] A scheduled encrypted backup can be restored into a disposable database and pass schema,
  count, integrity, and readiness checks.
  Verify: `tests/ops/test_builderops_backup_restore.py::test_backup_restore_drill_reaches_ready_with_matching_integrity`.

## Out of Scope

- final production cutover;
- migration of legacy stores;
- Product route removal; and
- source-repository extraction.

## How to Verify (Pre-Merge)

- render/validate Compose config under the dedicated project name;
- run auth-negative and credential-redaction tests;
- execute backup plus disposable restore in an isolated test project; and
- run `ruff check app tests` plus focused ops tests.

## Related Docs

- `docs/adr/ADR-0062-builderops-ecosystem-wide-enabling-system.md`
- `docs/BUILDEROPS_CONTROL_PLANE/README.md`
- `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md`

## Related GitHub Issues

- [#3790](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3790), blocked on BCP-01.
