---
name: Bind Background Lifecycles
description: Supervise watcher worker and settings lifecycles per explicit binding generation
task_id: MVR-06
source_anchor: "docs/SETTINGS_SPINE/REBIND_ON_VAULT_SELECTION.md :: What This Task Does"
parent_capability: Multi-vault runtime selection
prerequisites: [MVR-02, MVR-03, SETTINGS-05]
depends_on: [RESOLVE_INSTANCE_DEFAULT_VAULT.md, VERSION_ACTIVE_CONTEXT_SELECTION.md]
can_parallelize_with: [Group Vault Bindings By Dimension, Route Requests Through Active Context]
---

# Bind Background Lifecycles

## Purpose

Watcher, worker, and settings lifecycles still rely on process/env binding. #3163 owns the
single-watcher live rebind and must be reused, while multi-binding lifecycle ownership and
cross-process truth belong here.

## What This Task Does

- Reuse #3163's selection-event/settings-reload mechanism; do not duplicate it.
- Add a durable, mechanical instance-local `background_vault_binding_ids` intent set. Request or
  session selection never auto-enrols a member. Each unique binding is re-resolved and
  re-authorized at lifecycle start; a missing/unauthorized member remains explicitly failed.
- Persist an intent mode that distinguishes `compatibility_default` from `explicit`. A missing
  legacy field is initialized exactly once as compatibility mode; any governed add/remove command
  transitions to explicit mode. `explicit` with an empty binding list is durable and means idle—it
  must never re-enrol the default after restart. This state mutates through MVR-01's locked,
  revision-checked atomic registry transaction.
- Add governed production add/remove/list operations for that set through the existing
  Companion state-change authentication boundary and a headless CLI using the same service.
  Mutations validate registry membership and authorization, are idempotent by binding ID, record
  redacted receipts, and publish the versioned lifecycle/reload event. Tests must use these
  production producers rather than seeding the store.
- Introduce a lifecycle supervisor that treats the durable set only as intent. At start/rebind it
  derives one immutable full `ActiveContextSet` per lifecycle binding, including context ID,
  generation, stable binding, server-derived instance-background principal, operational scope,
  topology posture, and `background_intent` or `compatibility_default` provenance. Watcher, worker,
  settings, queues, health, and receipts propagate that context rather than a rival
  binding-plus-generation model. For migrated one-vault installs with no explicit set, the instance
  default/legacy bootstrap yields exactly one compatibility context; no request/session state
  participates.
- Define start/rebind/drain/stop behavior for zero/one/many bindings, including clean in-flight
  completion and loud partial failure.
- Propagate the complete background `ActiveContextSet` identity, including binding and generation,
  into health, receipts, settings reload, and work queues.
- Make cross-process consumers receive/re-resolve versioned binding state rather than sharing an
  untracked env snapshot.

## Concretely

With A and B explicitly enrolled for background work, the supervisor exposes separately healthy watcher/worker/settings bindings.
Switching A drains its current tick, reloads through #3163, and starts its next generation. If B
fails, B is visibly failed while A continues; no work is redirected. A and B are enrolled and
inspected through the production API/CLI service before the supervisor starts.

## Why This Matters

Request isolation cannot protect background ingest or queues that still watch one frozen env path.
Mixed bindings would silently index or mutate the wrong vault while health remained misleading.

## Source Anchors

- `docs/SETTINGS_SPINE/REBIND_ON_VAULT_SELECTION.md`
- `docs/architecture/SBS_TRANSITION_DEBT.md :: D13 / D14`
- `app/watcher/config.py :: ingest binding`
- `app/workers/outbox_worker.py :: vault binding`
- `docs/MULTI_VAULT_RUNTIME/README.md :: Reconciliation — do not duplicate`

## SBS Impact

- Primary subsystem: WSP
- Secondary subsystem(s): OEF, EBF, PDM, GOV, SFC
- Write class: existing mechanical/derived background writes only
- Authority impact: lifecycle creation requires authorized bindings; no authority expansion
- Persistence impact: durable instance-local background-binding intent; lifecycle state/receipts are operational
- Derived/rebuildable impact: worker/watch instances and health projections are rebuildable
- Human knowledge impact: background writes preserve target vault attribution
- Memory impact: background indexing never mixes vault contexts
- Retrieval/context impact: indexes/queues carry the full ActiveContextSet identity and binding provenance
- Sync/deployment impact: replaces frozen env snapshot with explicit cross-process binding truth
- External boundary impact: env remains bootstrap adapter only
- New or changed contract: per-binding lifecycle supervision through ActiveContextSet and truthful state transitions
- Owner-doc impact: will-update-in-PR at `docs/ENVIRONMENTS.md` and watcher/settings owner docs
- Transition debt impact: reduces D13/D14; residual adapters remain for task 07
- Fitness rule impact: strengthens lifecycle isolation and truthful health

## Constraints

- #3163 must be merged and its single-binding production event path reused.
- Registry membership and request/session activity are not background intent. The durable set is
  deduplicated by `vault_binding_id`; every member is re-authorized after restart and generation
  change.
- Compatibility-uninitialized and explicit-empty are different states. Removing the last explicit
  member survives restart as zero bindings and cannot reactivate the compatibility default.
- In-flight work completes against its captured binding; new work starts on the new generation.
- One failed binding does not masquerade as healthy or silently redirect to another.
- Never log or expose host paths, secrets, or binding payloads beyond the repository's redaction
  contract in receipts.

## Acceptance Criteria

- [ ] The production supervisor runs independent watcher/worker lifecycles for two bindings and
  attributes ingest, queues, settings, health, and receipts to the correct immutable
  ActiveContextSet/vault/generation.
  - Verify: `tests/integration/test_multi_vault_background_lifecycle.py::test_two_bindings_run_isolated_lifecycles`
- [ ] Request/session selection does not alter durable background intent; after restart the
  supervisor reconstructs exactly the explicitly enrolled, deduplicated, re-authorized set.
  - Verify: `tests/runtime/test_background_binding_handoff.py::test_restart_uses_only_durable_authorized_binding_set`
- [ ] Governed production API and CLI add/remove/list operations are the tested producers of
  background intent, reject unknown/unauthorized bindings, and publish one versioned event.
  - Verify: `tests/api/test_background_binding_admin.py::test_production_enrollment_commands_drive_lifecycle_intent`
- [ ] Removing the final explicit member persists explicit-empty intent; restart and list remain
  empty/idle and never re-enrol the instance default.
  - Verify: `tests/runtime/test_background_binding_handoff.py::test_remove_last_then_restart_preserves_explicit_empty_intent`
- [ ] Rebind drains in-flight work on the old generation and routes later work to the new one using
  #3163's production event/reload path.
  - Verify: `tests/integration/test_multi_vault_background_lifecycle.py::test_rebind_reuses_settings_spine_and_is_generation_clean`
- [ ] Zero bindings idle truthfully; one binding preserves current behavior; a failed member is
  loud and cannot redirect or mark the whole set healthy.
  - Verify: `tests/integration/test_multi_vault_background_lifecycle.py::test_zero_one_many_and_partial_failure_are_truthful`
- [ ] Cross-process worker startup consumes explicit versioned binding state, not an untracked
  process-global/env snapshot, and resolves it into the full background ActiveContextSet before
  work starts.
  - Verify: `tests/runtime/test_background_binding_handoff.py::test_worker_handoff_is_versioned_and_explicit`
- [ ] Production watcher/worker/settings callers consume ActiveContextSet outside named bootstrap
  adapters; no parallel lifecycle context type remains.
  - Verify: `tests/architecture/test_multi_vault_context_boundaries.py::test_background_consumers_use_lifecycle_seam`

## Out of Scope

- Reimplementing #3163, UI, scheduling policy/resource quotas, distributed orchestration, or
  changing ADR-0055 multi-writer semantics.

## How to Verify (Pre-Merge)

- `pytest -q tests/integration/test_multi_vault_background_lifecycle.py tests/runtime/test_background_binding_handoff.py tests/api/test_background_binding_admin.py tests/architecture/test_multi_vault_context_boundaries.py`
- `RUN_INTEGRATED_RUNTIME_UAT=1 pytest -q tests/integration -k "watcher or settings or multi_vault"`
- `ruff check app tests`

## Restart / Durability Posture

Lifecycle instances are rebuildable. On restart the supervisor reconstructs them from explicit
intent (including durable explicit-empty), or from the one-vault default only while the migrated
intent mode remains `compatibility_default`, and records fresh generations. It re-authorizes every
member; request/session selections are ignored. In-flight ephemeral work is retried only under its
existing idempotency contract, never silently rebound.

## Related Docs

- `docs/MULTI_VAULT_RUNTIME/README.md`
- `docs/SETTINGS_SPINE/REBIND_ON_VAULT_SELECTION.md`
- `docs/ENVIRONMENTS.md`

## Related GitHub Issues

Create one child under #2143 only after #3163 and MVR-02/03 merge. Use Sol/xhigh because watcher
concurrency, cross-process binding, and settings reload have high blast radius. Do not recreate
#3163 or its Settings Spine parent #3156.
