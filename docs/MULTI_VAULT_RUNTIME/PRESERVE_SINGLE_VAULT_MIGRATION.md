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
  channel scripts for global `VAULT_ROOT`, `WATCHER_VAULT_PATH`, `VaultManager.active_context`,
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
- Secondary subsystem(s): EBF, HIX, OEF, SFC, PDM
- Write class: none new; compatibility migration over existing writes
- Authority impact: no change
- Persistence impact: validates migrated registry/settings producers and rollback-read compatibility
- Derived/rebuildable impact: validates caches/indexes rebuild per binding
- Human knowledge impact: no data move or attribution loss
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

## Acceptance Criteria

- [ ] The architecture inventory finds no unapproved production global vault resolution outside
  named bootstrap/compatibility adapters.
  - Verify: `tests/architecture/test_multi_vault_context_boundaries.py::test_production_consumers_use_context_seam`
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
  prove the exact pre-run non-fixture test-channel baseline; incomplete teardown returns FAIL.
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
- [ ] Any retained compatibility adapter is named in transition debt with owner, removal condition,
  and production guard; otherwise the old app-local import path is removed.
  - Verify: doc writeback at `docs/architecture/SBS_TRANSITION_DEBT.md :: multi-vault runtime selection`

## Out of Scope

- New UX, data consolidation between content vaults, multi-writer policy, or broad env renaming.

## How to Verify (Pre-Merge)

- `pytest -q tests/ops/test_multi_vault_test_channel_smoke.py::test_smoke_harness_is_production_path_and_redacted`
- `pytest -q tests/ops/test_multi_vault_test_channel_smoke.py::test_smoke_rejects_non_test_manifest_roots_before_registration`
- `pytest -q tests/ops/test_multi_vault_test_channel_smoke.py::test_smoke_restores_prior_test_state_on_success_and_failure`
- `pytest -q tests/architecture/test_multi_vault_context_boundaries.py tests/integration/test_single_vault_compatibility.py tests/instance/test_vault_registry_migration.py tests/runtime/test_multi_vault_channel_bootstrap.py`
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

Create one child under #2143 after MVR-04/05/06. Terra/high can execute the explicit inventory and
compatibility ledger; escalate to Sol/high for schema rollback or producer/preflight ambiguity.
Apply the invariant→producers and no-silent-fallback learnings from #1991/#2003/#2311.
