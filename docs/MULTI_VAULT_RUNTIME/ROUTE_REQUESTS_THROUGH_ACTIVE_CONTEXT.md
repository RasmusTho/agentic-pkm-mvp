---
name: Route Requests Through Active Context
description: Migrate production HTTP retrieval and governed-write paths to immutable request context
task_id: MVR-05
source_anchor: "docs/MULTI_VAULT_RUNTIME/README.md :: Active context and isolation"
parent_capability: Multi-vault runtime selection
prerequisites: [MVR-03, MVR-04, SETTINGS-05]
depends_on: [VERSION_ACTIVE_CONTEXT_SELECTION.md, GROUP_VAULT_BINDINGS_BY_DIMENSION.md, "#3163"]
can_parallelize_with: []
---

# Route Requests Through Active Context

## Purpose

After the versioned context seam exists, production HTTP, retrieval, and governed-write paths must
stop resolving a process-global vault mid-request. This slice migrates request-bound consumers,
not background lifecycles.

## What This Task Does

- Inject the request's immutable `ActiveContextSet` into Companion/API routes and shared service
  calls that read, retrieve, capture, mutate, or emit receipts against content vaults.
- Migrate the existing Companion choose/open-vault picker and its current client state—not the
  deferred #2566 visual switcher—to create or replace a scoped selection, retain the returned
  `context_selection_id` for that client session, and send it on every vault-bound request. On
  expiry/restart the client clears the stale ID, shows the existing reselection contract, and never
  silently continues on the instance default.
- Preserve #3163 during the MVR-05→MVR-06 transition: the legacy choose/open picker action also
  emits its existing single-watcher selection event through one named compatibility bridge, while
  generic scoped request/session selections never do. MVR-06 must atomically initialize durable
  background intent from the then-current compatibility watcher binding and disable this bridge
  when its supervisor takes ownership; no release may leave both or neither mechanism active.
- Resolve per-binding settings, paths, caches, retrieval scope, and write provenance from the
  snapshot.
- Namespace durable/rebuildable projections and associations by `vault_binding_id` plus their
  existing artifact identity. This includes object/file-state rows, vector/index metadata, and any
  retrieval association that currently keys only by UUID/path. Migrate schema and every producer,
  consumer, fixture, and query together. Existing single-vault rows are assigned only when the
  legacy binding is provably unique; ambiguous rows are quarantined and rebuilt from their source
  vault under a fail-loud preflight—never copied to several bindings or guessed from a default.
- Before enabling the first binding-keyed database producer or migrating any row, atomically set a
  durable `minimum_runtime_schema=MVR-05` compatibility floor in instance state. Scalar pre-MVR
  rollback is blocked from that point even on a one-binding instance, because the old API/worker
  cannot safely filter or acknowledge binding-keyed projection/outbox rows. Promotion preflight
  names this forward-only boundary; rollback remains available only to a build that understands at
  least MVR-05. Apply invariant→producers to startup, migrations, fixtures, and rollback preflight.
- Version every MVR-05 vault-bound outbox producer with `routing_class=vault_bound`, stable binding,
  and captured context identity before it may serve multi-vault writes. In the same slice, teach the
  still-scalar worker to recognize that envelope and fail closed before handler dispatch: leave the
  row durably pending/unacknowledged, report readiness `blocked_pending_mvr06`, and continue only
  independently safe `global` work. MVR-06 owns binding-scoped dispatch, legacy classification,
  quarantine, and recovery; until it lands no versioned vault-bound row can execute against the
  worker's env-selected vault.
- Make many-binding reads explicit and provenance-preserving; require an explicit target binding
  for writes unless the command contract already provides one unambiguously.
- Add an architecture guard against new direct process-global vault resolution in request code.

## Concretely

Two clients call the production retrieval and capture routes concurrently with contexts for vaults
A and B. Results, caches, governed writes, and receipts stay attributed to their own binding; an
unknown selection returns the explicit picker/error contract and touches neither vault.

## Why This Matters

A correct resolver is insufficient if a downstream route re-reads mutable global state. One such
call site can leak retrieval context or write to the wrong human artifact surface.

## Source Anchors

- `docs/MULTI_VAULT_RUNTIME/README.md :: Active context and isolation`
- `app/api/routes/companion.py :: vault-bound request paths`
- `app/api/routes/capture.py :: governed capture path`
- `docs/contracts/ACTIVE_CONTEXT_SET.md`

## SBS Impact

- Primary subsystem: WSP
- Secondary subsystem(s): GOV, RCA, HKA, EBF, HIX, OEF
- Write class: existing governed human-artifact writes; no new write authority
- Authority impact: enforces per-binding authorization and explicit write target
- Persistence impact: additive binding namespace/association migration for durable projection rows;
  ambiguous legacy projection state is quarantined/rebuilt, never guessed
- Derived/rebuildable impact: caches/retrieval/object/file/vector projections become binding-keyed and rebuildable
- Human knowledge impact: preserves source vault and target attribution
- Memory impact: retrieval/memory reads are scoped to explicit bindings
- Retrieval/context impact: production request consumers adopt ActiveContextSet
- Sync/deployment impact: supports concurrent requests without process rebinding
- External boundary impact: API input maps to context selectors, not raw trusted paths
- New or changed contract: request-context propagation and explicit multi-binding write target
- Owner-doc impact: will-update-in-PR at `docs/ARCHITECTURE.md`
- Transition debt impact: reduces D1 and request-side D13 global-binding debt
- Fitness rule impact: adds production-entrypoint context-boundary guard

## Constraints

- No route accepts a client path as authority or silently falls back on selection failure.
- Cross-vault reads retain source provenance; writes name exactly one authorized target per
  operation unless an existing governed batch contract explicitly covers several.
- Preserve current response shapes for no-vault and single-vault callers unless additive context
  provenance is required.

## Acceptance Criteria

- [ ] Two production API sessions read different vaults concurrently without cross-talk or global
  mutation.
  - Verify: `tests/integration/test_multi_vault_request_isolation.py::test_two_sessions_use_distinct_vaults_without_cross_talk`
- [ ] Production retrieval over several bindings preserves source vault and context generation on
  every result and cache lookup.
  - Verify: `tests/retrieval/test_multi_vault_retrieval.py::test_production_retrieval_preserves_binding_provenance`
- [ ] Two registered bindings containing the same artifact UUID retain independent object,
  file-state, vector/index, retrieval, and receipt provenance without overwrite or cross-read.
  - Verify: `tests/integration/test_multi_vault_projection_isolation.py::test_duplicate_uuid_is_namespaced_by_binding`
- [ ] Legacy single-vault projection rows backfill only with one provable binding; ambiguous rows
  block mixed-mode startup until quarantined/rebuilt, without destructive guessing.
  - Verify: `tests/migrations/test_multi_vault_projection_backfill.py::test_projection_backfill_is_unambiguous_or_fails_loud`
- [ ] The migration records the MVR-05 minimum-runtime floor before any binding-keyed database
  state is written; scalar rollback then fails before starting an old API/worker, including on a
  one-binding instance, while a compatible roll-forward retains the full lineage.
  - Verify: `tests/migrations/test_multi_vault_projection_backfill.py::test_projection_upgrade_blocks_scalar_rollback_before_first_write`
- [ ] Production capture/governed-write paths require one explicit authorized target and record
  vault/context provenance in their receipt.
  - Verify: `tests/api/test_multi_vault_governed_writes.py::test_capture_uses_explicit_authorized_target_and_receipt`
- [ ] Every MVR-05 vault-bound producer emits the versioned binding/context routing envelope, and
  the interim scalar worker leaves such rows pending/unacknowledged with blocked readiness instead
  of dispatching them; global work remains independently processable until MVR-06.
  - Verify: `tests/workers/test_multi_vault_partial_delivery_gate.py::test_scalar_worker_never_dispatches_mvr05_vault_bound_rows`
- [ ] Invalid or unauthorized request selection returns the explicit error/picker contract and
  never serves default, last-active, CWD, or another binding.
  - Verify: `tests/api/test_multi_vault_request_fail_closed.py::test_invalid_selection_never_falls_back`
- [ ] The shipped Companion picker creates/replaces a scoped selection and its client sends that
  bearer ID through production read and governed-write requests; choosing B changes later requests
  to B, and stale-ID recovery visibly asks for reselection.
  - Verify: `tests/integration/test_multi_vault_picker_context.py::test_existing_picker_drives_scoped_request_context`
- [ ] Before MVR-06 takes ownership, only the legacy choose/open picker action also drives #3163's
  single-watcher rebind; generic scoped session/request selection does not. The bridge is named and
  guarded for atomic retirement by MVR-06.
  - Verify: `tests/integration/test_multi_vault_picker_context.py::test_legacy_picker_bridge_preserves_single_watcher_until_mvr06`
- [ ] Request-bound production code cannot introduce new direct global vault resolution outside
  named compatibility adapters.
  - Verify: `tests/architecture/test_multi_vault_context_boundaries.py::test_request_consumers_use_context_seam`

## Out of Scope

- Watcher/worker lifecycle, the new visual switcher/overlay behavior owned by #2566,
  registry/default/dimension storage, or removing all compatibility adapters.

## How to Verify (Pre-Merge)

- `pytest -q tests/integration/test_multi_vault_request_isolation.py tests/integration/test_multi_vault_picker_context.py tests/integration/test_multi_vault_projection_isolation.py tests/migrations/test_multi_vault_projection_backfill.py tests/retrieval/test_multi_vault_retrieval.py tests/api/test_multi_vault_governed_writes.py tests/api/test_multi_vault_request_fail_closed.py tests/workers/test_multi_vault_partial_delivery_gate.py tests/architecture/test_multi_vault_context_boundaries.py`
- `ruff check app tests`

## Restart / Durability Posture

Request contexts are not durable. Durable effects remain the existing governed content writes and
receipts, now carrying binding/generation provenance. After restart, clients resolve a fresh
session/default context and never inherit an unrecorded process selection.

## Related Docs

- `docs/MULTI_VAULT_RUNTIME/README.md`
- `docs/contracts/ACTIVE_CONTEXT_SET.md`
- `docs/ARCHITECTURE.md`

## Related GitHub Issues

Create one child under #2143 after MVR-03/04 and #3163. Use Sol/high for binding-key schema/backfill and
authority review; Terra/high is acceptable only for decomposed mechanical call-site migration after
those gates are fixed. This slice owns compatibility migration of the already-shipped picker;
#2566 remains the separate downstream visual switcher/overlay issue.
