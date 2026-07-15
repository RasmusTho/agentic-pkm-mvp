---
name: Bind Background Lifecycles
description: Supervise watcher worker and settings lifecycles per explicit binding generation
task_id: MVR-06
source_anchor: "docs/SETTINGS_SPINE/REBIND_ON_VAULT_SELECTION.md :: What This Task Does"
parent_capability: Multi-vault runtime selection
prerequisites: [MVR-02, MVR-03, MVR-04, MVR-05, SETTINGS-05]
depends_on: [RESOLVE_INSTANCE_DEFAULT_VAULT.md, VERSION_ACTIVE_CONTEXT_SELECTION.md, GROUP_VAULT_BINDINGS_BY_DIMENSION.md, ROUTE_REQUESTS_THROUGH_ACTIVE_CONTEXT.md]
can_parallelize_with: []
---

# Bind Background Lifecycles

## Purpose

Watcher, worker, and settings lifecycles still rely on process/env binding. #3163 owns the
single-watcher live rebind and must be reused, while multi-binding lifecycle ownership and
cross-process truth belong here.

## What This Task Does

- Reuse #3163's selection-event/settings-reload mechanism; do not duplicate it.
- At the MVR-06 migration boundary, read the live binding owned by MVR-05's named legacy-picker
  bridge, materialize that binding as durable `compatibility_binding_id` in compatibility mode,
  start the revision-reconciling supervisor, and disable the bridge in one fail-closed cutover. Roll back
  the cutover if either handoff step fails. Afterward, the supervisor—not the retired bridge—keeps
  consuming #3163's legacy choose/open picker event while mode remains `compatibility`, atomically
  updating `compatibility_binding_id` and rebind generation. Generic request/session selection never
  changes background intent. Once a governed add/remove command enters `explicit` mode, picker and
  default changes cannot alter the explicit set.
- Add a durable, mechanical instance-local `background_vault_binding_ids` intent set. Request or
  session selection never auto-enrols a member. Each unique binding is re-resolved and
  re-authorized at lifecycle start; a missing/unauthorized member remains explicitly failed.
- Persist an intent mode that distinguishes `compatibility` from `explicit`. A missing legacy field
  is initialized exactly once as compatibility mode: MVR-06 snapshots the live bridge binding when
  present, otherwise the current default/no-vault result, into nullable durable
  `compatibility_binding_id`. Restart reuses that exact binding and never re-derives another from
  unrecorded interaction history or default. While mode remains compatibility, a production legacy
  choose/open event or explicit MVR-02 default set/clear atomically replaces/clears this field and
  triggers rebind; the event provenance is stored with the revision. Any governed add/remove command
  transitions to explicit mode. `explicit` with an empty binding list is durable and means idle—it
  must never re-enrol the default after restart. This state mutates through MVR-01's locked,
  revision-checked atomic registry transaction.
- Add governed production add/remove/list operations for that set through the existing
  Companion state-change authentication boundary and a headless CLI using the same service.
  Add mutations validate current registry membership and content authority. Remove mutations
  require instance-administrative authority and the stored binding ID but remain idempotent when
  that registration is missing or no longer content-authorized, so failed stale intent can always
  be cleared safely. Both record redacted receipts and commit a durable change record/revision in
  the same fsync-backed registry transaction. A lifecycle event is only an idempotent wake-up hint for that revision, never the
  sole handoff. Tests must use these production producers rather than seeding the store.
- Introduce a lifecycle supervisor that treats the durable set only as intent. At start/rebind it
  derives one immutable full `ActiveContextSet` per lifecycle binding, including context ID,
  generation, stable binding, server-derived instance-background principal, operational scope,
  topology posture, and `background_intent`, `compatibility_handoff`, or `compatibility_default`
  provenance. Watcher, worker, settings, queues, health, and receipts propagate that context rather than a rival
  binding-plus-generation model. For migrated one-vault installs with no explicit set, the captured
  live bridge binding—or, absent that, the instance default/legacy bootstrap—yields exactly
  one durable compatibility context; no later request/session state participates.
- Subscribe the supervisor to MVR-02's versioned default-mutation event. While intent mode is
  `compatibility`, replacing or clearing the default atomically updates `compatibility_binding_id`,
  drains the current generation, and re-resolves the replacement binding or truthful no-vault
  state before later work is accepted.
  The same event cannot alter an `explicit` intent set. A default mutation may not leave a running
  compatibility lifecycle silently bound to the prior vault or rely on process restart.
- Before writing the first background-intent or compatibility-binding field, use the MVR-05 channel
  fence to atomically advance `minimum_runtime_schema=MVR-06`. A build below that floor cannot start
  watcher/worker/API against the registry; recovery preserves the complete lineage and uses an
  MVR-06-compatible roll-forward/rollback, never a projection that discards background intent.
- Reconcile durable registry revisions at supervisor startup and continuously while running, with
  idempotent event hints only accelerating that reconciliation. For every unseen revision, diff
  registration path/device/authority provenance, removal, default, and background intent. Drain,
  re-resolve, and re-authorize every affected lifecycle into a new ActiveContextSet generation
  before accepting later work; removal or failed authorization stops that binding loudly. This
  revision cursor makes a producer crash after the atomic commit but before event publication
  converge without leaving removed or relocated bindings active.
- Define start/rebind/drain/stop behavior for zero/one/many bindings, including clean in-flight
  completion and loud partial failure.
- Propagate the complete background `ActiveContextSet` identity, including binding and generation,
  into health, receipts, settings reload, and work queues.
- Make cross-process consumers receive/re-resolve versioned binding state rather than sharing an
  untracked env snapshot.
- Version queued work and outbox rows with an explicit routing class:
  `global` for handlers that touch no content vault, or `vault_bound` with binding/context identity.
  Global rows remain singleton work and require no invented vault. Vault-bound polling/ack ownership
  is binding-scoped. Before enabling more than one lifecycle, a fail-loud upgrade gate uses the
  versioned topic/handler routing registry to classify every undelivered legacy row: known global
  topics remain global; known vault-bound topics backfill only when producer evidence and the prior
  single-vault binding prove one target; unknown topics or ambiguous vault-bound rows quarantine for
  explicit recovery without dispatch or ack. A quarantined unsafe row makes the affected worker
  readiness degraded/blocked but a valid global row never blocks multi-binding startup merely for
  lacking a binding.
- Revalidate every not-yet-in-flight vault-bound row against the current stable binding, compatible
  registry revision, authorization verdict, routing class, and payload locator before dispatch.
  Captured request/background context and generation remain immutable producer provenance, but a
  routine supervisor restart or generation rotation alone does not invalidate the row. When the
  same binding remains authorized and any relative locator resolves safely under its current root,
  dispatch records a new consumer-context generation linked to the producer context. Removal, lost
  authority, binding-identity mismatch, or an incompatible absolute/stale locator atomically moves
  the row to durable quarantine without dispatch or acknowledgement. Authenticated administration
  can inspect and drop it, or reissue it only after the same stable binding is authorized under a
  fresh context, preserving original idempotency/lineage; it can never retarget the row to another
  binding. Quarantine is a terminal, observable disposition rather than an indefinitely pending row.

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
- Persistence impact: durable instance-local background-binding intent plus global/vault-bound
  routing, binding/context schema migration, and classification for pending queue/outbox rows
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

- [ ] MVR-06 atomically imports the live MVR-05/#3163 compatibility watcher binding, starts the
  revision-reconciling supervisor, and retires the legacy picker bridge; injected failure leaves
  the old bridge authoritative and never enables two or zero watcher owners.
  - Verify: `tests/integration/test_multi_vault_background_lifecycle.py::test_settings_spine_bridge_handoff_is_atomic`
- [ ] The imported live compatibility binding survives restart even when it differs from the
  instance default; a later legacy choose/open picker event or explicit default set/clear changes it
  while compatibility mode remains active, and governed background administration enters explicit mode.
  - Verify: `tests/runtime/test_background_binding_handoff.py::test_compatibility_handoff_binding_survives_restart_without_default_fallback`
- [ ] After bridge retirement, a legacy choose/open picker change still atomically updates the
  compatibility binding and drains/rebinds the supervisor; generic scoped selection and every picker
  event after explicit-mode transition leave background intent unchanged.
  - Verify: `tests/integration/test_multi_vault_background_lifecycle.py::test_picker_rebinds_only_compatibility_mode_after_bridge_handoff`
- [ ] The production supervisor runs independent watcher/worker lifecycles for two bindings and
  attributes ingest, queues, settings, health, and receipts to the correct immutable
  ActiveContextSet/vault/generation.
  - Verify: `tests/integration/test_multi_vault_background_lifecycle.py::test_two_bindings_run_isolated_lifecycles`
- [ ] Request/session selection does not alter durable background intent; after restart the
  supervisor reconstructs exactly the explicitly enrolled, deduplicated, re-authorized set.
  - Verify: `tests/runtime/test_background_binding_handoff.py::test_restart_uses_only_durable_authorized_binding_set`
- [ ] Governed production API and CLI add/remove/list operations are the tested producers of
  background intent, reject unknown/unauthorized bindings, atomically commit a durable revision,
  and publish an idempotent wake-up event for that revision.
  - Verify: `tests/api/test_background_binding_admin.py::test_production_enrollment_commands_drive_lifecycle_intent`
- [ ] Instance-authorized removal clears stale stored intent idempotently even after its registry
  entry disappears or content authority is lost; add still requires live membership and authority.
  - Verify: `tests/api/test_background_binding_admin.py::test_stale_binding_intent_can_be_removed_without_content_authority`
- [ ] Removing the final explicit member persists explicit-empty intent; restart and list remain
  empty/idle and never re-enrol the instance default.
  - Verify: `tests/runtime/test_background_binding_handoff.py::test_remove_last_then_restart_preserves_explicit_empty_intent`
- [ ] Replacing or clearing the instance default through MVR-02's production API/CLI drains and
  re-resolves a compatibility lifecycle before later work, but does not rebind explicit intent.
  - Verify: `tests/integration/test_multi_vault_background_lifecycle.py::test_default_mutation_rebinds_only_compatibility_lifecycle`
- [ ] Rebind drains in-flight work on the old generation and routes later work to the new one using
  #3163's production event/reload path.
  - Verify: `tests/integration/test_multi_vault_background_lifecycle.py::test_rebind_reuses_settings_spine_and_is_generation_clean`
- [ ] Relocating/removing a registered binding or changing authority-relevant provenance rotates
  every affected running lifecycle through drain, re-resolution, and re-authorization; a producer
  crash after registry commit but before event publication still converges from the durable
  revision cursor without accepting later work on the stale binding.
  - Verify: `tests/integration/test_multi_vault_background_lifecycle.py::test_registry_revision_rebinds_and_closes_event_crash_window`
- [ ] Zero bindings idle truthfully; one binding preserves current behavior; a failed member is
  loud and cannot redirect or mark the whole set healthy.
  - Verify: `tests/integration/test_multi_vault_background_lifecycle.py::test_zero_one_many_and_partial_failure_are_truthful`
- [ ] The parent lifecycle-and-dimension acceptance target composes the MVR-04 dimension authority
  contract with isolated zero/one/many watcher and worker behavior before MVR-06 merges.
  - Verify: `tests/integration/test_multi_vault_lifecycle_and_dimension.py::test_parent_dimension_background_acceptance`
- [ ] Cross-process worker startup consumes explicit versioned binding state, not an untracked
  process-global/env snapshot, and resolves it into the full background ActiveContextSet before
  work starts.
  - Verify: `tests/runtime/test_background_binding_handoff.py::test_worker_handoff_is_versioned_and_explicit`
- [ ] Pending pre-upgrade outbox work is classified through the production handler registry: global
  topics continue exactly once without a binding, vault-bound rows are assigned only from provable
  prior evidence, and unknown/ambiguous rows quarantine without dispatch or acknowledgement; new
  vault polling and ack are binding-scoped.
  - Verify: `tests/migrations/test_multi_vault_outbox_upgrade.py::test_legacy_pending_rows_backfill_or_quarantine_fail_loud`
- [ ] The MVR-06 minimum-runtime floor commits before the first background-intent field and blocks
  every older API/watcher/worker before registry access; fault injection leaves either untouched
  MVR-05 state or an MVR-06-compatible lineage.
  - Verify: `tests/migrations/test_multi_vault_background_intent_upgrade.py::test_background_intent_sets_mvr06_floor_before_first_write`
- [ ] Pending vault-bound rows are revalidated before dispatch; lifecycle removal, lost authority,
  or incompatible binding/locator change quarantines them durably without dispatch/ack, and governed reissue can
  target only the same re-authorized stable binding with lineage/idempotency preserved.
  - Verify: `tests/integration/test_multi_vault_background_lifecycle.py::test_pending_rows_quarantine_across_removal_and_rebind`
- [ ] A routine supervisor restart or generation rotation preserves valid pending rows for the same
  authorized binding, links fresh consumer context to immutable producer provenance, and does not
  quarantine or retarget them.
  - Verify: `tests/integration/test_multi_vault_background_lifecycle.py::test_pending_rows_survive_compatible_restart_generation`
- [ ] Production watcher/worker/settings callers consume ActiveContextSet outside named bootstrap
  adapters; no parallel lifecycle context type remains.
  - Verify: `tests/architecture/test_multi_vault_context_boundaries.py::test_background_consumers_use_lifecycle_seam`

## Out of Scope

- Reimplementing #3163, UI, scheduling policy/resource quotas, distributed orchestration, or
  changing ADR-0055 multi-writer semantics.

## How to Verify (Pre-Merge)

- `pytest -q tests/integration/test_multi_vault_background_lifecycle.py tests/integration/test_multi_vault_lifecycle_and_dimension.py tests/runtime/test_background_binding_handoff.py tests/api/test_background_binding_admin.py tests/migrations/test_multi_vault_outbox_upgrade.py tests/migrations/test_multi_vault_background_intent_upgrade.py tests/architecture/test_multi_vault_context_boundaries.py`
- `RUN_INTEGRATED_RUNTIME_UAT=1 pytest -q tests/integration -k "watcher or settings or multi_vault"`
- `ruff check app tests`

## Restart / Durability Posture

Lifecycle instances are rebuildable. On restart the supervisor reconstructs them from explicit
intent (including durable explicit-empty), or from durable `compatibility_binding_id` while the
migrated intent mode remains `compatibility`, and records fresh generations. It re-authorizes every
member, records its durable registry revision cursor, and continuously reconciles later revisions;
events are lossy wake-up hints only. Request/session selections are ignored. In-flight ephemeral
work is retried only under its existing idempotency contract, never silently rebound.

## Related Docs

- `docs/MULTI_VAULT_RUNTIME/README.md`
- `docs/SETTINGS_SPINE/REBIND_ON_VAULT_SELECTION.md`
- `docs/ENVIRONMENTS.md`

## Related GitHub Issues

Create one child under #2143 only after #3163 and MVR-02–05 merge. Use Sol/xhigh because watcher
concurrency, cross-process binding, and settings reload have high blast radius. Do not recreate
#3163 or its Settings Spine parent #3156.
