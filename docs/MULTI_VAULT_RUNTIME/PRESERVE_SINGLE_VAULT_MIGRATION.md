---
name: Preserve Single Vault Migration
description: Remove unapproved global assumptions while proving no-vault and one-vault compatibility
task_id: MVR-07
source_anchor: "docs/CONCEPTS/VAULT_TOPOLOGY_CONTRACT.md :: Topology rules"
parent_capability: Multi-vault runtime selection
prerequisites: [MVR-04, MVR-05, MVR-06]
depends_on: [GROUP_VAULT_BINDINGS_BY_DIMENSION.md, ROUTE_REQUESTS_THROUGH_ACTIVE_CONTEXT.md, BIND_BACKGROUND_LIFECYCLES.md]
can_parallelize_with: []
---

# Preserve Single Vault Migration

## Purpose

Multi-vault is incomplete if existing callers still rely on hidden process-global resolution or
if one-vault/no-vault installations regress. This slice removes bounded adapters only after every
producer and consumer has a replacement and proves reversibility to the single-vault floor.

## What This Task Does

- Inventory HTTP, CLI, agent, MCP, watcher, worker, settings, health, startup, compose, tests, and
  channel scripts for global `VAULT_ROOT`, `WATCHER_VAULT_PATH`, `VaultManager.context` and its
  backing `_context`,
  `last_active_vault_ref`, and old `app.vault.app_local` assumptions.
- Classify each use as explicit bootstrap adapter, request context, lifecycle binding, or invalid
  global access; migrate or remove invalid accesses.
- Remove the old package re-export only if production and external compatibility policy permit;
  otherwise record one named removal issue/deadline rather than hiding debt.
- Prove no-vault and one-vault startup, picker, restart, watcher-idle, requests, CLI, agents, MCP,
  receipts, and promotion-channel behavior.
- Add the deterministic `scripts/multi_vault_test_channel_smoke.py` harness consumed by MVR-08; it
  accepts only an explicit redacted fixture manifest and exercises production APIs without logging
  paths, names, tokens, or content.
- Before registering either fixture, canonicalize every manifest root and prove it is a distinct
  descendant of the configured test-sandbox root. Reject overlap with the prod/dev/native vault
  roots known to channel preflight, overlap between fixture roots, an unresolvable root, or any
  symlink/path escape before the first registration or write. Each manifest root must also be
  absent before the invocation. The harness atomically creates it itself and writes a private
  ownership marker containing the current invocation nonce before any fixture content. A
  pre-existing directory/file, raced creation, missing/mismatched marker, or marker symlink fails
  closed; caller-supplied sandbox descendants are never adopted. Checking only the singular
  `TEST_VAULT_ROOT` is insufficient.
- Run each smoke invocation in a unique disposable fixture namespace and record the pre-run test
  registry/default/dimension/background-intent/projection plus host-ledger baseline. A failure-safe
  teardown always drains fixture lifecycles, removes fixture projections through their production
  cleanup contract, removes dimensions/default/registrations, releases fixture ownership leases,
  deletes a sandbox root only when its canonical identity and private ownership marker still match
  this invocation, and proves the non-fixture baseline is restored.
  Cleanup runs after both PASS and injected failure; a cleanup error makes the smoke receipt FAIL and
  blocks later deployment/parent closure. No prior test-channel registration or operator state may be
  overwritten as a shortcut.
- Run the journey against a freshly created, invocation-owned disposable instance-state/DB/runtime
  namespace under the promoted test image/checkout, never against the test channel's standing
  instance-state namespace. Preflight proves the disposable namespace is empty, binds background
  intent directly into explicit mode through production bootstrap, and records its ownership marker
  before fixture enrollment. Teardown destroys only that marked namespace after all production
  drains/removals complete. The standing channel's compatibility/explicit mode, members, default,
  revisions, projections, and operator state remain byte-for-byte unchanged; if isolation cannot be
  established, fail before the first governed mutation.
- Provide the governed topology-reduction path required by topology rule 6. The operator chooses one
  explicit target binding; the reducer fences new effects, drains every source binding, and creates a
  deterministic collision-safe reduction manifest before any source is deactivated. Every source is
  represented under an unambiguous source namespace in the target (or an equivalently human-openable
  attached package), preserving original `vault_binding_id`, vault-relative path, artifact identity,
  source provenance, receipt/outbox lineage, settings scope, and content checksums. It never silently
  merges or overwrites conflicting paths or identities.
- Authorize reduction through GOV as an explicit multi-binding content-migration intent. Before any
  copy, GOV independently authorizes read/export on every source, governed HKA creation on the target,
  and later source retirement; the reducer mints binding/revision/purpose-bound write tokens for each
  target artifact and records source/target attribution in every receipt. A deny, stale revision, or
  authority change fails before the affected write and cannot be converted into partial success.
- Commit the reduction manifest, copied content, lineage map, and complete projection rebuild as one
  recoverable transition. Failure before commit leaves the original topology authoritative; recovery
  after commit rolls forward until the single target exposes all material and derived projections are
  healthy. Only then may source registrations be deactivated. The manifest supports lossless
  re-expansion/reattachment to the original binding boundaries, so receipts and provenance continue to
  name their original sources even while the runtime operates with one active content vault.
- Retire sources only through a batch coordinator over MVR-06B's authoritative removal journal. It
  acquires the existing host-global ownership fence/ownership-ledger lock first, then the target and
  every source mutation gate plus exclusive binding-effect lease in one canonical binding-ID order.
  The target participates in fencing/proof but is never included in the retirement tombstone set. The
  coordinator closes new MVR-06D queue claims and runs its authoritative recovery for every
  source-bound queued, claimed, dispatched, and `effect_pending` row. An effect that completed before
  its receipt is reconstructed and receipted under the original source binding before the final
  target rescan; every row must reach one proven terminal outcome. Missing or ambiguous effect/receipt
  evidence blocks the batch before publish and leaves every source active—reduction never relabels,
  drops, or quarantines unsettled work to manufacture completion. The coordinator then completes
  every final scan/buffer drain, stages every
  dimension/default/background-intent repair and immutable tombstone, and proves the target
  package/rebuild before publishing anything. It then takes
  the instance/channel registry's existing exclusive sidecar lock and uses that store's normal
  revision/CAS + fsync + atomic-replace transaction as the one durable commit point for all source
  tombstones, repaired references, target selectability, ownership-release intents, and the complete
  reduction receipt. The target's exclusive lease remains held through its final content/checksum and
  projection proof plus that publish, so a concurrent target write or rebuild cannot stale or be
  overwritten by the accepted manifest. While the ownership-ledger lock remains held, ownership
  release executes only from that committed journal; crash recovery reacquires the same locks in the
  same order. No
  cross-channel registry lock or authority is introduced. The coordinator never directly deletes
  a registration or bypasses MVR-06B lineage rules. A crash after preparing any strict subset leaves
  every source active and the target incomplete/unselectable; a crash after the single commit rolls
  forward all ownership releases. Governed abort before commit removes copied artifacts and restores
  ordinary source effects only after revalidation.

## Concretely

An existing one-vault installation upgrades without changing its journey, and a no-vault instance
still boots idle. The inventory reports only named bootstrap adapters. A rollback reader can recover
the one binding and its provenance from the migrated store without touching content.

## Why This Matters

Removing a scalar assumption incompletely creates a split runtime; removing it too aggressively
can break startup or strand durable state. Both failures are latent outages rather than progress.

## Source Anchors

- `docs/CONCEPTS/VAULT_TOPOLOGY_CONTRACT.md :: Topology rules` (rule 6, reversibility to single vault)
- `docs/VAULT_OPTIONAL_RUNTIME/README.md :: Cross-Task Invariants`
- `docs/MULTI_VAULT_RUNTIME/README.md :: Cross-task invariants`
- `docs/architecture/SBS_TRANSITION_DEBT.md :: D1 / D13 / D14`

## SBS Impact

- Primary subsystem: WSP
- Secondary subsystem(s): GOV, HKA, EBF, HIX, OEF, SFC, PDM
- Write class: governed HKA content-copy/reduction writes plus mechanical migration metadata
- Authority impact: GOV independently authorizes every source export, target write, and source
  retirement; reduction cannot confer access or bypass MVR-06 removal authority
- Persistence impact: validates migrated registry/settings producers and rollback-read compatibility
- Derived/rebuildable impact: validates caches/indexes rebuild per binding
- Human knowledge impact: deterministic reduction may copy material into a human-openable target
  namespace but never semantically merges it; attribution and source identity remain lossless
- Memory impact: validates single-vault retrieval/memory parity
- Retrieval/context impact: removes unapproved scalar resolution after consumer migrations
- Sync/deployment impact: validates dev/test/prod bootstrap and promotion assumptions
- External boundary impact: keeps env/mount adapters explicit and narrow
- New or changed contract: migration completion/compatibility fitness contract
- Owner-doc impact: will-update-in-PR only for factual adapter/debt state
- Transition debt impact: closes or explicitly re-baselines D1/D13/D14 residues
- Fitness rule impact: adds full consumer inventory and no/one-vault compatibility guards

## Constraints

- Apply invariant→producers symmetrically: startup, migrations, fixtures, and preflights move in
  the same change as any fail-loud runtime precondition.
- Do not delete a compatibility path without evidence for its production/external callers.
- A rollback to one configured vault preserves meaning, attribution, receipts, and data. After the
  MVR-05 minimum-runtime floor is recorded, this means a rollback image that understands binding-
  keyed database/outbox state; scalar pre-MVR rollback remains fail-closed.
- Topology reduction is a governed, quiesced, collision-safe copy plus lineage transition. It cannot
  deactivate a source until checksums, provenance, receipts, projections, and reversible
  reattachment have all been verified.
- Every target artifact write uses a binding/revision/purpose-bound governed token. Every source
  deactivation composes MVR-06B removal/tombstone/reference repair through one all-source batch commit;
  direct registry deletion and partial per-source retirement are forbidden.

## Acceptance Criteria

- [ ] The architecture inventory finds no unapproved production global vault resolution outside
  named bootstrap/compatibility adapters, including direct or aliased reads of the real
  `VaultManager.context`/`_context` seam.
  - Verify: `tests/architecture/test_multi_vault_context_boundaries.py::test_production_consumers_use_context_seam`
  - Verify: `tests/architecture/test_multi_vault_context_boundaries.py::test_real_vault_manager_context_accessor_cannot_escape_inventory`
- [ ] The test-channel smoke harness exercises two bindings/sessions, one dimension read, one
  governed write, and background health through production entrypoints while emitting a redacted receipt.
  - Verify: `tests/ops/test_multi_vault_test_channel_smoke.py::test_smoke_harness_is_production_path_and_redacted`
- [ ] The smoke harness rejects either manifest binding when its canonical root is outside the
  declared test sandbox, overlaps a known prod/dev/native root, aliases the other fixture, or escapes
  through a symlink. It also rejects every pre-existing/raced root or missing/mismatched ownership
  marker, performs zero registrations/content writes on rejection, and never deletes a root it did
  not atomically create and mark for the current invocation.
  - Verify: `tests/ops/test_multi_vault_test_channel_smoke.py::test_smoke_rejects_non_test_manifest_roots_before_registration`
- [ ] Successful and failure-injected smoke runs drain and remove every fixture lifecycle,
  projection, dimension/default/registration, sandbox root, and host-global ownership lease, then
  delete only their marked disposable instance-state/DB/runtime namespace and prove the exact
  pre-run standing test-channel baseline, including compatibility/explicit intent mode, is unchanged;
  incomplete isolation or teardown returns FAIL.
  - Verify: `tests/ops/test_multi_vault_test_channel_smoke.py::test_smoke_restores_prior_test_state_on_success_and_failure`
- [ ] Existing no-vault and one-vault journeys preserve startup, picker, request, restart, watcher
  idle/bind, CLI/agent/MCP, retrieval, governed-write, and receipt behavior.
  - Verify: `tests/integration/test_single_vault_compatibility.py::test_existing_single_vault_journey_is_preserved`
- [ ] Registry/default/dimension migrations can read existing state and a documented rollback
  reader can recover the single-vault binding without content or provenance loss.
  - Verify: `tests/instance/test_vault_registry_migration.py::test_single_vault_rollback_reader_preserves_binding`
- [ ] Test and promotion channel bootstrap still provisions one deterministic vault and passes its
  fail-loud preflight.
  - Verify: `tests/runtime/test_multi_vault_channel_bootstrap.py::test_test_channel_keeps_deterministic_single_vault_preflight`
- [ ] Two distinct content vaults can be reduced to one explicitly selected target without losing
  content, meaning, original binding attribution, settings scope, receipt/outbox lineage, or human-
  readable provenance; conflicts remain namespaced rather than overwritten, and the manifest can
  reattach the material to its original source boundaries.
  - Verify: `tests/integration/test_multi_vault_single_topology_reduction.py::test_two_distinct_vaults_reduce_to_one_without_losing_content_provenance_or_receipts`
- [ ] A topology reduction failure is atomic and recoverable: pre-commit failure preserves the
  original active topology, post-commit recovery rolls forward and rebuilds every binding-keyed
  projection before healthy reads, and source registrations remain active until the complete
  reduction receipt is durable.
  - Verify: `tests/integration/test_multi_vault_single_topology_reduction.py::test_reduction_is_collision_safe_atomic_and_reversible`
- [ ] Reduction independently GOV-authorizes every source read/export, target governed HKA write,
  and source retirement; binding/revision/purpose-bound tokens and receipts preserve source/target
  attribution, while deny or authority-revision races fail before the affected artifact or retirement.
  - Verify: `tests/integration/test_multi_vault_single_topology_reduction.py::test_reduction_authorizes_each_source_target_write_and_retirement`
- [ ] Source deactivation runs only through the MVR-06B removal journal and atomically repairs
  dimension, default, background-intent, projection, ownership, and tombstone lineage references;
  injected failure cannot leave a directly deleted registration or a selectable incomplete target.
  - Verify: `tests/integration/test_multi_vault_single_topology_reduction.py::test_reduction_retires_sources_through_mvr06_removal_transaction`
- [ ] Multi-source retirement acquires host-global ownership-ledger fence → canonical exclusive
  target-and-source per-binding leases → instance-registry sidecar lock, keeps the target out of the
  tombstone set, and holds its lease through target proof and one durable registry batch commit. A
  crash after the first or any later per-source prepare leaves every source registration active and
  the target unselectable, while a
  crash after commit recovers all tombstones, repaired references, target selectability, ownership
  releases, and the complete receipt without a partially retired topology or lock-order inversion.
  - Verify: `tests/integration/test_multi_vault_single_topology_reduction.py::test_reduction_batch_retirement_has_one_atomic_commit_point`
- [ ] A target content write or projection rebuild racing reduction waits for the target's exclusive
  lease or completes before the reducer's final proof; the complete manifest/receipt always covers
  the exact published target revision and no accepted target mutation is overwritten.
  - Verify: `tests/integration/test_multi_vault_single_topology_reduction.py::test_reduction_fences_target_write_and_projection_races`
- [ ] Before target proof or retirement publish, reduction gates new source-bound claims and uses
  MVR-06D recovery to terminally reconcile and receipt every queued/claimed/dispatched/effect-pending
  row. A crash after effect but before receipt is recovered under the source binding and included by
  the final rescan; ambiguous evidence blocks with all sources active and no complete reduction receipt.
  - Verify: `tests/integration/test_multi_vault_single_topology_reduction.py::test_reduction_reconciles_effect_pending_before_retirement_commit`
- [ ] Any retained compatibility adapter is named in transition debt with owner, removal condition,
  and production guard; otherwise the old app-local import path is removed.
  - Verify: doc writeback at `docs/architecture/SBS_TRANSITION_DEBT.md :: multi-vault runtime selection`

## Out of Scope

- New UX, arbitrary/manual semantic merging between content vaults, multi-writer policy, or broad
  env renaming. The only content movement in scope is the deterministic governed topology-reduction
  package required to prove rule-6 reversibility.

## How to Verify (Pre-Merge)

- `pytest -q tests/ops/test_multi_vault_test_channel_smoke.py::test_smoke_harness_is_production_path_and_redacted`
- `pytest -q tests/ops/test_multi_vault_test_channel_smoke.py::test_smoke_rejects_non_test_manifest_roots_before_registration`
- `pytest -q tests/ops/test_multi_vault_test_channel_smoke.py::test_smoke_restores_prior_test_state_on_success_and_failure`
- `pytest -q tests/architecture/test_multi_vault_context_boundaries.py tests/integration/test_single_vault_compatibility.py tests/instance/test_vault_registry_migration.py tests/runtime/test_multi_vault_channel_bootstrap.py`
- `pytest -q tests/architecture/test_multi_vault_context_boundaries.py::test_real_vault_manager_context_accessor_cannot_escape_inventory`
- `pytest -q tests/integration/test_multi_vault_single_topology_reduction.py::test_two_distinct_vaults_reduce_to_one_without_losing_content_provenance_or_receipts tests/integration/test_multi_vault_single_topology_reduction.py::test_reduction_is_collision_safe_atomic_and_reversible`
- `pytest -q tests/integration/test_multi_vault_single_topology_reduction.py::test_reduction_authorizes_each_source_target_write_and_retirement tests/integration/test_multi_vault_single_topology_reduction.py::test_reduction_retires_sources_through_mvr06_removal_transaction`
- `pytest -q tests/integration/test_multi_vault_single_topology_reduction.py::test_reduction_batch_retirement_has_one_atomic_commit_point`
- `pytest -q tests/integration/test_multi_vault_single_topology_reduction.py::test_reduction_fences_target_write_and_projection_races`
- `pytest -q tests/integration/test_multi_vault_single_topology_reduction.py::test_reduction_reconciles_effect_pending_before_retirement_commit`
- `mypy app`
- `pytest -q -m "not pg"`
- `RUN_INTEGRATED_RUNTIME_UAT=1 pytest -q tests/uat/`
- `ruff check app tests`

## Restart / Durability Posture

Migrated registry/default/dimension state survives restart and remains readable by the documented
compatible rollback path. No-vault remains idle; one-vault restarts against the same explicit
identity. The durable MVR-05 floor prevents a scalar image from touching binding-keyed shared
database/outbox state. Any
retained adapter is durable transition debt with a removal condition, not hidden behavior.

## Related Docs

- `docs/MULTI_VAULT_RUNTIME/README.md`
- `docs/VAULT_OPTIONAL_RUNTIME/README.md`
- `docs/ENVIRONMENTS.md`

## Related GitHub Issues

Create one child under #2143 after MVR-04/05/06. Use Sol/xhigh for the governed topology reduction,
authority, data migration, and rollback design; mechanically isolated inventory/compatibility work
may de-escalate to Terra/high only after those contracts are frozen.
Apply the invariant→producers and no-silent-fallback learnings from #1991/#2003/#2311.
