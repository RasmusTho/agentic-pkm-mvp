State: Current BuilderOps deployment contract. Amended by #5056: BuilderOps is rebuildable operational state; backup and restore are deferred and never admission gates.
Doc role: BCP-02 owner contract
Authority: Defines the independent BuilderOps Compose, image, secret, ingress, health, and rebuild boundary.

# Independent Authenticated Deployment

## Implementation Status

The repository contract provides a separate BuilderOps Compose project, immutable control-plane and
PostgreSQL image pins, an isolated Docker context/engine preflight, VM-local secret references,
migration-gated API and worker startup, loopback API exposure, private authenticated ingress,
authenticated probes, rebuild/rollback receipts, and a local disk/WAL guard. The deployment target
for the complete Dev System is TARS VM 102 (`builder-system`), with Dev UI as one read-only
component; this contract does not activate a live VM or make a backup/restore claim.

## Rebuildable VM deployment contract

BuilderOps operational state is rebuilt from repository source, exact attested images, pinned configuration, and secret custody. The deployed Compose and candidate image paths include no WAL-G, recovery target, recovery egress, archived-WAL pipeline, backup service, or restore command. A future backup capability requires a separate owner decision and bounded delivery; its absence cannot block deployment, migration, readiness, candidate attestation, rollout, or closure.

PostgreSQL has `archive_mode = off` and an empty `archive_command`. The local guard rejects archive drift, WAL growth, and disk pressure. It never deletes `pg_wal`, invokes `pg_resetwal`, or treats a reset/cleanup tool as a rebuild substitute.

For first database initialization only, deployment preflights the exact regular host source `${BUILDEROPS_SECRET_ROOT}/database-app-password` as root-owned mode `0400` or `0600`. The PostgreSQL image then reads only the fixed Compose secret path `/run/secrets/builderops_database_app_password` and copies that single app-role password into a `postgres`-owned tmpfs file. `init_roles.sh` reads and removes that staged file before the service starts. No other secret is staged or made readable to the init script, and neither the original secret nor its value enters an environment variable, image layer, durable file, log, or another service.

The first-init handoff is fail-closed across crashes: a pending marker is durable before `initdb`, while a ready marker is written only after the app-role transaction commits. A restarted new cluster with a pending marker but no ready marker refuses to start instead of serving incomplete authorization state; an explicit, separately authorized recovery or rebuild is required. Existing clusters that predate this marker have no pending marker and are not modified by this guard.

### Complete Dev System admission

BuilderOps deployment is admitted only as one part of the complete Dev System topology described in
[`README.md :: Complete Dev System VM-102 topology contract`](README.md). A Dev UI-only deployment,
the default Docker engine, or a healthy guest check cannot satisfy this boundary. The component
inventory must classify every known component as `VM-102 resident (target)`, `explicit external
dependency`, or `intentionally non-runtime`, and must leave unresolved identity, service, ingress,
health, lifecycle, migration, and rollback facts as explicit gaps.

The ordered schemas and bootstrap-without-baseline refusal are owned only by the
[VM-102 evidence and receipt contract](README.md#vm-102-evidence-and-receipt-contract). This BCP-02
contract consumes those receipts but does not redefine them. Locally, deployment still refuses
secret-bearing evidence, unqualified hosts, missing component gaps, and rollback without a
compatible runnable baseline; the repository-side candidate qualification remains insufficient for
live qualification.

## Purpose

Keep BuilderOps outside the `pkm-*` Product Runtime failure domain while preserving a truthful,
private, and rebuildable deployment path.

## Constraints

- Both source and image identities are immutable and attested; zero pins are not runnable.
- BuilderOps and Product use distinct Docker contexts and engine identities; no Product project, state, credential, vault, or network identity is admitted on the BuilderOps engine.
- The API publishes only to loopback. Tailscale Serve terminates tailnet-only HTTPS to that endpoint; Funnel is inactive and bearer authentication remains mandatory.
- Migrations, schema version, authority epoch/fencing, no dual writer, health/readiness, and rebuild receipts remain gates. A rollback selects compatible code/config/image and does not rewind data.
- This repository contract does not authorize live VM, Docker, secret, Tailscale, firewall, or PostgreSQL mutation.

## Acceptance Criteria

- [x] Compose has one internal BuilderOps network, loopback-only API exposure, no recovery secret or egress, and rebuildable local durability mode.
  Verify: `tests/ops/test_builderops_compose_contract.py::test_local_control_plane_disables_wal_archiving_without_recovery_egress`.
- [x] Candidate images and attestation bind immutable control-plane and PostgreSQL digests without a restore proof or backup gate.
  Verify: `tests/ops/test_builderops_compose_contract.py::test_rebuildable_candidate_path_has_no_backup_or_restore_gate`.
- [x] Deployment and rollback receipts bind pins, dedicated engine/project, authenticated loopback/Tailscale-Serve-without-Funnel ingress, migration completion, schema/epoch/fencing, no-dual-writer and external-effect-reconciliation requirements, and rollback-without-data-rewind. They contain no backup/restore acceptance field.
  Verify: `tests/ops/test_builderops_deploy_contract.py::test_deploy_and_rollback_receipts_bind_pin_schema_and_epoch`.
- [x] A non-rebuildable local durability setting fails before image pull or service activation.
  Verify: `tests/ops/test_builderops_deploy_contract.py::test_deploy_refuses_a_local_mode_that_would_require_recovery_egress`.

## Out of Scope

- Live rollout, data migration, authority cutover, or recovery operations.
- Backup/restore implementation or acceptance.

## How to Verify (Pre-Merge)

- Run the focused BuilderOps compose, deployment-contract, local-WAL-guard, and health tests.
- Run `ruff check app tests`, documentation validation, and the high-risk contract review gate.

## Related Docs

- `docs/BUILDEROPS_CONTROL_PLANE/README.md`
- `docs/BUILDEROPS_CONTROL_PLANE/AUTHORITY_CUTOVER_PRODUCT_SEPARATION.md`
- `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md`
