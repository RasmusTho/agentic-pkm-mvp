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
- provide scheduled encrypted full backups plus continuous WAL durability to an independent
  recovery target that survives loss of Demerzel's primary host and storage failure domains,
  independently recoverable key custody or KMS authorization outside those failure domains,
  retention, acknowledged-LSN tracking, documented point-in-time restore, and an automated
  restore-through-watermark drill with Demerzel's host secret store unavailable; and
- prove Product Compose and Product credentials/config are not dependencies.

## Concretely

The slice adds a BuilderOps-only Compose invocation and service entrypoint such that an operator can
deploy a pinned image, wait for migrations, call authenticated `/healthz` and `/readyz`, inspect
secret-safe status, prove synchronous recovery durability before mutation acknowledgement/replay or
external-effect eligibility, take a full backup, independently recover its decryption capability,
restore it plus WAL through the highest acknowledged LSN into an isolated project while Demerzel's
host secret store is unavailable, and
change to a compatible BuilderOps image without rewinding authoritative data or running a `pkm-*`
Compose command.

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
  authority-threatening outbox condition, a recovery target co-resident with Demerzel or sharing
  its primary storage failure domain, or inability to keep the commit/recovery LSN synchronously
  durable in the independent recovery target.
- Recovery eligibility is server-enforced: API success/replay and dependent transitions wait for the
  originating LSN, outbox claim waits for the intent LSN, and the external call waits for the fenced
  claim/pre-effect attempt LSN. No client or executor assertion can bypass either watermark.
- A persistent volume or snapshot alone is not accepted as recoverability. Full backup + continuous
  WAL must restore through the highest acknowledged LSN/receipt sequence; backup/restore negative
  scans must also prove the credential exclusion boundary.
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
- [ ] Authority-bearing API responses are withheld until the transaction's recovery LSN is
  synchronously durable outside Demerzel's primary host/storage failure domain; readiness rejects a
  co-resident/shared-storage target and fails closed when the durability guarantee or lag bound is
  unavailable.
  Verify: `tests/builderops/control_plane/test_recovery_durability.py::test_authority_ack_requires_separate_failure_domain_and_recovery_lsn`.
- [ ] Stalling the independent recovery watermark after local intent and claim commits withholds API
  success/replay and every dependent transition, keeps the outbox intent ineligible, and leaves
  GitHub untouched until both the intent and fenced pre-effect attempt LSNs are durable.
  Verify: `tests/builderops/control_plane/test_recovery_durability.py::test_external_effect_waits_for_intent_and_claim_recovery_lsn`.
- [ ] With Demerzel's host secret store unavailable, independently recoverable key/KMS custody can
  decrypt an encrypted full backup plus continuous WAL and restore a disposable database through the
  highest acknowledged LSN/receipt sequence with passing schema, count, integrity, outbox/lease, and
  readiness checks.
  Verify: `tests/ops/test_builderops_backup_restore.py::test_restore_through_watermark_without_demerzel_secret_store`.
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
- interrupt recovery durability to prove acknowledgement/replay, dependent transitions, and GitHub
  effects fail closed through both intent and pre-effect attempt watermarks, then execute full backup
  + WAL restore through the acknowledged watermark in an isolated test project with Demerzel's host
  secret store unavailable; and
- run `ruff check app tests` plus focused ops tests.

## Related Docs

- `docs/adr/ADR-0062-builderops-ecosystem-wide-enabling-system.md`
- `docs/BUILDEROPS_CONTROL_PLANE/README.md`
- `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md`

## Related GitHub Issues

- [#3790](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3790), blocked on BCP-01.
