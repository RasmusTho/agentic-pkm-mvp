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
  expiry/restart the client clears the stale ID and never retries the failed request via fallback.
  It may mint a fresh selection automatically only when a new authenticated resolution proves
  exactly one authorized registered binding and that binding is the explicit instance default; the
  reminted context is used for a new request. Any zero/many/ambiguous/default mismatch shows the
  existing reselection contract.
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
- Before enabling the first binding-keyed database producer or migrating any row, acquire the
  channel deployment fence and enumerate every enabled old process that can query/mutate the shared
  database or emit an outbox row from compose/runtime producer truth—not a hard-coded API/worker
  pair. This includes API, worker, watcher, Heimdal/capture services, and any enabled auxiliary
  producer. Remove API/producer ingress, stop enqueue/dequeue/ack, drain in-flight work, and stop all
  enumerated processes. The host-side coordinator does not depend on new-image code executing inside
  old containers: after timeout it may terminate them only after proving their database sessions are
  gone and incomplete transactions rolled back. The migration must prove every inventoried process
  identity and session is gone and prevent restart before it atomically records durable
  `minimum_runtime_schema=MVR-05` in instance state and touches the shared database. The pinned-image
  deploy path must run this drain/stop gate before its new-image `migrate` service; its current
  migrate-before-force-recreate ordering is not acceptable for MVR-05. Any failed fence/drain/stop
  aborts before the floor or database changes. After the floor commits, scalar pre-MVR rollback is
  blocked even on a one-binding instance, because the old API/worker cannot safely filter or
  acknowledge binding-keyed projection/outbox rows. Recovery is roll-forward or rollback to a build
  that understands at least MVR-05. Apply invariant→producers to deployment, startup, migrations,
  fixtures, and rollback preflight.
- Version every MVR-05 vault-bound outbox producer with `routing_class=vault_bound`, stable binding,
  and captured context identity before it may serve multi-vault writes. In the same slice, teach the
  still-scalar worker to recognize that envelope. It may dispatch only after production resolution
  proves the row names the worker's one explicit current compatibility binding and the worker's
  authorization, resolved root/fingerprint, and binding revision all still match. Other remembered
  registry entries are irrelevant and must not stall that uniquely bound worker. A missing,
  ambiguous, env-only, or mismatched worker binding leaves the
  row durably pending/unacknowledged, reports readiness `blocked_pending_mvr06`, and continues only
  independently safe `global` work. MVR-06 owns multi-binding dispatch and governed quarantine
  recovery; until it lands no ambiguous row can execute against an env-selected vault.
- While every old DB/outbox producer is fenced and before any upgraded producer is enabled, classify
  every undelivered legacy row through the production handler registry and reconcile its idempotency
  key transactionally. Known global rows retain an explicit global key. A known vault-bound row is
  assigned/scoped only from provable producer evidence and the explicit compatibility binding. If
  its recomputed binding-scoped key already exists with identical topic/source/payload fingerprint,
  coalesce to one canonical row while preserving lineage/attempt history; a differing collision,
  unknown topic, or ambiguous binding quarantines without dispatch/ack. Commit a migration receipt
  proving no dispatchable unscoped vault-bound row remains before new producers start. MVR-06 consumes
  this result and must not independently backfill a second copy.
- Namespace every migrated vault-bound outbox idempotency/dedup key by `vault_binding_id` in
  addition to topic, logical source identity, and content fingerprint. A global producer uses an
  explicit `global` scope marker. Two vaults containing the same UUID/path/content must create
  independent rows; retry within one binding must still deduplicate normally.
- Make many-binding reads explicit and provenance-preserving; require an explicit target binding
  for writes unless the command contract already provides one unambiguously.
- At every governed mutation seam, immediately before the owner store writes, re-resolve the target
  binding and compare its current revision/root plus the current authorization epoch with the
  request snapshot, then validate a live GOV `DecisionToken` for that principal, scope, operation,
  and binding. Relocation, removal, or revocation after request resolution returns a stale-context/
  reauthorization error without writing; it never continues merely because the request snapshot is
  immutable. Long-running owner transactions must use their existing drain/fence contract.
- Extend the canonical GOV token/receipt schema in this slice. A server-minted DecisionToken binds
  decision ID, authenticated human/delegated-role principal, instance identity, operational scope,
  action/write class, stable vault binding, binding revision/root fingerprint, authorization epoch,
  issued/expiry times, and policy/delegation revision. Validation compares every field to current
  state immediately before mutation. AuthorityReceipt references the token/decision and records the
  evaluated binding/auth revisions plus applied/denied/stale outcome without raw paths or secrets.
  Update capture and every governed-write producer, serializer/store, migration, fixture, and
  fail-loud preflight together; an old actor/resource/action-only token cannot authorize the new seam.
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
- Owner-doc impact: will-update-in-PR at `docs/ARCHITECTURE.md`,
  `docs/contracts/GOVERNED_WRITE_PROTOCOL.md`, `docs/EVENTS.md`,
  `docs/DB_SCHEMA.md`, `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md`, and
  `docs/RELEASE_CHANNELS/README.md`
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
- [ ] Before any binding-keyed producer starts, all pending legacy outbox keys are classified and
  scoped/coalesced under the DB fence; an identical retry produces one canonical dispatch lineage,
  while conflicting or ambiguous rows quarantine and cannot later duplicate the upgraded event.
  - Verify: `tests/migrations/test_multi_vault_outbox_upgrade.py::test_legacy_idempotency_keys_coalesce_before_new_producer_enable`
- [ ] The migration records the MVR-05 minimum-runtime floor before any binding-keyed database
  state is written; scalar rollback then fails before starting an old API/worker, including on a
  one-binding instance, while a compatible roll-forward retains the full lineage.
  - Verify: `tests/migrations/test_multi_vault_projection_backfill.py::test_projection_upgrade_blocks_scalar_rollback_before_first_write`
- [ ] Pinned-image deployment fences writes/dequeue, drains and stops the old scalar API/worker,
  every enabled watcher, Heimdal, capture, and auxiliary DB/outbox producer, and proves none can
  restart or retain a DB session before setting the floor or running the binding-keyed migration;
  fault injection leaves the floor/database untouched or requires compatible roll-forward.
  - Verify: `tests/ops/test_mvr05_mixed_version_fence.py::test_all_old_scalar_db_clients_are_stopped_before_binding_keyed_migration`
- [ ] The deployment fence inventory is generated from production compose/runtime producer truth and
  fails when any enabled process that can call the DB/outbox seam is absent from the drain/stop plan.
  - Verify: `tests/ops/test_mvr05_mixed_version_fence.py::test_fence_inventory_covers_every_enabled_db_outbox_process`
- [ ] Production capture/governed-write paths require one explicit authorized target and record
  vault/context provenance in their receipt.
  - Verify: `tests/api/test_multi_vault_governed_writes.py::test_capture_uses_explicit_authorized_target_and_receipt`
- [ ] Relocation, removal, or GOV revocation after request resolution but before commit invalidates
  the current DecisionToken/binding revision and blocks the in-flight mutation without writing to
  either the old or replacement root.
  - Verify: `tests/api/test_multi_vault_governed_writes.py::test_authority_or_locator_change_blocks_inflight_write_before_commit`
- [ ] The production capture path issues, persists, validates, and receipts the expanded token bound
  to principal/instance/scope/binding revision/auth epoch; legacy-shaped tokens and stale epochs fail
  before mutation, and all token producers/fixtures satisfy the same schema.
  - Verify: `tests/api/test_multi_vault_governed_writes.py::test_capture_token_binds_principal_scope_binding_revision_and_auth_epoch`
- [ ] A production producer registry and architecture guard enumerate every vault-bound watcher,
  API/ingest/capture, Heimdal, and shared outbox call site; no unregistered call site can emit a
  legacy envelope.
  - Verify: `tests/architecture/test_multi_vault_context_boundaries.py::test_vault_bound_outbox_producers_cannot_emit_legacy_envelopes`
- [ ] Invoking every registered production vault-bound producer emits the versioned stable-binding,
  context, routing-class, and idempotency envelope without fixture-only row construction.
  - Verify: `tests/integration/test_multi_vault_outbox_producers.py::test_production_call_sites_emit_binding_context_envelopes`
- [ ] The interim scalar worker dispatches only a row matching its explicit current single-binding
  compatibility context, authorization, revision, and root even when other vaults are remembered;
  it leaves every ambiguous/mismatched row pending/unacknowledged with blocked readiness,
  while global work remains independently processable until MVR-06.
  - Verify: `tests/workers/test_multi_vault_partial_delivery_gate.py::test_scalar_worker_dispatches_only_rows_matching_explicit_worker_binding`
- [ ] Vault-bound outbox idempotency keys include the stable binding: duplicate logical identities
  in two bindings persist independently, while same-binding retries deduplicate.
  - Verify: `tests/services/test_multi_vault_outbox_idempotency.py::test_duplicate_identity_events_are_deduplicated_per_binding`
- [ ] Invalid or unauthorized request selection returns the explicit error/picker contract and
  never serves default, last-active, CWD, or another binding.
  - Verify: `tests/api/test_multi_vault_request_fail_closed.py::test_invalid_selection_never_falls_back`
- [ ] The shipped Companion picker creates/replaces a scoped selection and its client sends that
  bearer ID through production read and governed-write requests; choosing B changes later requests
  to B, and stale-ID recovery with zero, many, ambiguous, or default-mismatched bindings visibly
  asks for reselection.
  - Verify: `tests/integration/test_multi_vault_picker_context.py::test_existing_picker_drives_scoped_request_context`
- [ ] After API restart, a stale bearer never authorizes or falls back for its failed request; the
  client never retries that failed request. Before a later, newly initiated request it may
  transparently mint a replacement only after fresh authenticated resolution proves exactly one
  authorized binding equal to the explicit default; otherwise reselection remains visible.
  - Verify: `tests/integration/test_multi_vault_picker_context.py::test_stale_selection_restart_recovers_only_unambiguous_singleton_default`
- [ ] Before MVR-06 takes ownership, only the legacy choose/open picker action also drives #3163's
  single-watcher rebind; generic scoped session/request selection does not. The bridge is named and
  guarded for atomic retirement by MVR-06.
  - Verify: `tests/integration/test_multi_vault_picker_context.py::test_legacy_picker_bridge_preserves_single_watcher_until_mvr06`
- [ ] Request-bound production code cannot introduce new direct global vault resolution outside
  named compatibility adapters.
  - Verify: `tests/architecture/test_multi_vault_context_boundaries.py::test_request_consumers_use_context_seam`
- [ ] The parent request acceptance target composes two-session isolation, resolution precedence,
  fail-closed stale selection, projection separation, retrieval provenance, and governed writes on
  the production request seam.
  - Verify: `tests/integration/test_multi_vault_request_isolation.py::test_parent_request_context_acceptance`
- [ ] Production resolution applies explicit selection, instance default, and no-vault precedence
  without consulting last-active, CWD, or another binding after an invalid explicit choice.
  - Verify: `tests/integration/test_multi_vault_resolution.py::test_resolution_precedence_and_fail_closed_behavior`
- [ ] Architecture, event, DB, deployment, and release-channel owner contracts describe the shipped
  binding/context envelope, idempotency-key migration, projection namespace, minimum-runtime floor,
  and all-process fenced cutover.
  - Verify: doc writeback at `docs/ARCHITECTURE.md :: Active context and vault bindings` + doc
    writeback at `docs/contracts/GOVERNED_WRITE_PROTOCOL.md :: GovernedWriteProtocol` + doc
    writeback at `docs/EVENTS.md :: Events` + doc writeback at
    `docs/DB_SCHEMA.md :: DB Schema (Current Reality)` + doc writeback at
    `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md :: Deployment and Environments` + doc writeback at
    `docs/RELEASE_CHANNELS/README.md :: Release Channels Specification`

## Out of Scope

- Watcher/worker lifecycle, the new visual switcher/overlay behavior owned by #2566,
  registry/default/dimension storage, or removing all compatibility adapters.

## How to Verify (Pre-Merge)

- `pytest -q tests/integration/test_multi_vault_request_isolation.py tests/integration/test_multi_vault_resolution.py tests/integration/test_multi_vault_picker_context.py tests/integration/test_multi_vault_projection_isolation.py tests/integration/test_multi_vault_outbox_producers.py tests/migrations/test_multi_vault_projection_backfill.py tests/migrations/test_multi_vault_outbox_upgrade.py tests/ops/test_mvr05_mixed_version_fence.py tests/retrieval/test_multi_vault_retrieval.py tests/api/test_multi_vault_governed_writes.py tests/api/test_multi_vault_request_fail_closed.py tests/workers/test_multi_vault_partial_delivery_gate.py tests/services/test_multi_vault_outbox_idempotency.py tests/architecture/test_multi_vault_context_boundaries.py`
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
