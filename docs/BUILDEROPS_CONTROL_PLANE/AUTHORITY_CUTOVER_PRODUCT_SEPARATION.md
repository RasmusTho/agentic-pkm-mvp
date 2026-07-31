---
name: Authority Cutover And Product Separation
description: Perform the one-way cutover, remove Product ownership, and retire legacy authorities.
task_id: BCP-06
github_issue: 3793
source_anchor: docs/BUILDEROPS_CONTROL_PLANE/README.md :: Cross-task invariants / partial-failure safety
parent_capability: BuilderOps independent control plane
prerequisites: [BCP-03, BCP-04, BCP-05]
depends_on: [LEGACY_AUTHORITY_MIGRATION.md, API_ONLY_CLIENT_CUTOVER.md, DEMERZEL_REVIEW_MERGE_ORCHESTRATION.md]
can_parallelize_with: []
---

# Authority Cutover And Product Separation

## Purpose

BCP-01 through BCP-05 establish the new authority, deployment, migration, clients, and privileged
executor without yet declaring them production-authoritative. This task owns the controlled freeze,
import, cutover, Product route/process removal, legacy retirement, and end-to-end proof.

## What This Task Does

- schedule/record the authority cutover window and preconditions;
- freeze every inventoried legacy writer, take a pre-import PostgreSQL backup, hash sources, run final
  import/reconciliation, and activate a new PostgreSQL authority epoch;
- switch MacBook clients and Demerzel executor configuration to the authoritative API;
- remove BuilderOps/Signboard ownership from Product FastAPI, Product startup/bootstrap, Product
  Compose mounts/env/secrets/health, and Product deployment paths;
- disable/remove production SQLite/JSONL/JSON authority construction and SSH direct-store paths;
- run health/readiness, API/executor end-to-end, crash recovery, a full-backup + archived-WAL
  restore-from-backup drill with Demerzel's host secret store unavailable (ADR-0062 A1), and
  Product-independence acceptance;
- archive legacy sources read-only with inventory hashes and retention; and
- define rollback before activation as prior image + pre-import backup, and recovery after activation
  as a compatible image or full-backup + archived-WAL restore to the latest archived point, followed
  by a mandatory GitHub reconciliation of external effects and a new lease/fencing epoch before the
  executor resumes (ADR-0062 A1); never rewind state that survived or reactivate SQLite.

## Concretely

The operator runs one fail-closed cutover command/plan: preflight inventory and restore proof, freeze,
backup, final import, authority-epoch activation, client/executor switch, Product route/startup
removal, end-to-end proof, and archive receipt. Any failed gate stops before authority activation or
leaves the PostgreSQL epoch authoritative for forward repair. Once a client can receive an accepted
response, snapshot rewind of surviving state is forbidden; recovery restores the latest archived
point, reconciles external effects against GitHub, and activates a new fencing epoch before writes
resume (ADR-0062 A1: the tail since the last archived point is an accepted loss window).

## Why This Matters

This is where independently correct slices can still produce dual authority or an outage. A single
cutover owner and invariant→producers gate prevents partial migration, legacy re-creation, and a
rollback that silently resurrects SQLite.

## Source Anchors

- `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md :: Deploy procedure`
- `docs/builderops/BUILDEROPS_VAULT_BOUNDARY.md :: Scope`
- `docs/AGENT_ISSUE_DISPATCHER.md :: Dev/prod startup bootstrap`

## SBS Impact

Boundary work between Builder System and Product Runtime. Direction is Product Runtime → independent
Builder System for BuilderOps process/data/routes; Product behavior and subsystem allocation remain
unchanged.

## Constraints

- Cutover is fail-closed on missing inventory, authority-bearing ambiguity that is neither evidence-
  resolved nor protected by duplicate-preventing non-authoritative tombstone semantics, failed
  restore drill, unhealthy schema/outbox, client fallback, executor failure, or remaining Product
  ownership. Plain quarantine is allowed only for evidence that cannot authorize, suppress, or replay
  an effect.
- Invariant → producers: every producer/initializer/client of legacy state is migrated or disabled in
  the same change, with a fail-loud preflight.
- No dual-write/dual-authority window is permitted.
- Pre-activation rollback may restore the pre-import backup. Post-activation recovery is
  forward-only: restore the latest archived point, reconcile unknown external effects against
  GitHub, and start a new fencing epoch before reopening writes (ADR-0062 A1). A missing/failed
  restore drill or missing independently recoverable key/KMS custody blocks cutover; archiving lag
  is an alert condition, not an acknowledgement gate.
- Product Runtime behavior unrelated to BuilderOps remains unchanged and independently verifiable.
- Archived sources are immutable evidence, not rollback authority.
- Owner docs are not rewritten as shipped until this task's receipts exist; BCP-07 owns writeback.

## Acceptance Criteria

- [ ] Final inventory/import reconciliation covers the producer-derived expected host/worktree/
  container/automation universe, accounts for all legacy state, records a new authority epoch, and
  proves no coverage gap or live legacy lease entered production authority. Every authority-bearing
  conflict/provenance ambiguity is evidence-resolved or duplicate-preventing tombstoned; plain
  quarantine contains evidence-only material.
  Verify: cutover receipt containing BCP-03 inventory/import/reconciliation hashes.
- [ ] MacBook client plus Demerzel executor complete a record→lease→attempt→outbox→GitHub readback→
  receipt flow against one PostgreSQL epoch after restart, and the flow proceeds normally while the
  `pkm-*` stacks are stopped/restarted and while backup archiving is stalled (which raises a loud
  alert; ADR-0062 A1/A2).
  Verify: `tests/builderops/control_plane/test_end_to_end_api_flow.py::test_remote_client_and_executor_share_one_authority_epoch` plus
  `tests/ops/test_builderops_failure_domain.py::test_builder_plane_survives_product_stack_lifecycle_and_alerts_on_stalled_archiving` and the Demerzel runtime receipt.
- [ ] Cutover consumes the BCP-05 proof that a protected-base or delivery-manifest change after final
  validation invalidates the GitHub conditional/merge-group fence and performs no merge.
  Verify: `tests/dispatcher/test_verification_merge.py::test_merge_rejects_base_or_manifest_change_after_final_validation` plus the BCP-05 runtime receipt.
- [ ] Product FastAPI has no BuilderOps/Signboard route, Product startup/Compose has no BuilderOps
  process/data/secret/health ownership, and Product reaches readiness while BuilderOps is stopped.
  Verify: `tests/architecture/test_builderops_product_separation.py::test_product_runtime_has_no_builderops_ownership`.
- [ ] Production commands cannot create/open BuilderOps or dispatcher SQLite/JSONL/JSON authority and
  fail closed if the API is unavailable.
  Verify: `tests/architecture/test_builderops_store_boundary.py::test_cutover_leaves_no_legacy_authority_producer`.
- [ ] With Demerzel's host secret store unavailable, independently recoverable key/KMS custody
  decrypts the post-import full backup plus archived WAL and restores a disposable database to the
  latest archived point with matching epoch/counts/hashes and passing `/readyz` plus outbox/lease
  integrity checks.
  Verify: restore-from-backup receipt bound to the authoritative full backup, WAL lineage, and
  independent key-custody recovery proof.
- [ ] Recovery rehearsal proves pre-activation backup rollback is unavailable after activation and
  that compatible-image or restore-from-backup recovery reaches the latest archived point, performs
  GitHub reconciliation, and activates a new fencing epoch before writes reopen, with no SQLite
  activation path and no rewind of surviving state.
  Verify: `tests/ops/test_builderops_cutover.py::test_post_activation_recovery_cannot_rewind_surviving_state`.
- [ ] Legacy stores are archived read-only with hashes/retention and #3686/PR #3695 are reconciled as
  superseded-target evidence.
  Verify: archive/reconciliation receipt plus GitHub lifecycle receipt.

## Out of Scope

- rewriting owner docs before proof;
- deleting retained evidence before retention expiry;
- Product feature changes; and
- source-repository extraction.

## How to Verify (Pre-Merge)

- execute a documented test-channel rehearsal before authoritative cutover;
- run the fail-loud producer inventory and focused full BuilderOps/dispatcher/API tests;
- run `ruff check app tests` and any harness self-verification required by invariant→producers;
- stop each Product/BuilderOps side independently and prove readiness semantics; and
- attach cutover, restore-without-Demerzel-host-secrets, independent key-custody recovery,
  no-authority-rewind recovery rehearsal, and GitHub readback receipts to the parent.

## Related Docs

- `docs/adr/ADR-0062-builderops-ecosystem-wide-enabling-system.md`
- `docs/BUILDEROPS_CONTROL_PLANE/README.md`
- `docs/audits/BUILDEROPS_CONTROL_PLANE_2026-07-15.md`

## Related GitHub Issues

- [#3793](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3793), blocked on BCP-03,
  BCP-04, and BCP-05.
- Owns final reconciliation of issue #3686 / PR #3695 after cutover evidence exists.
