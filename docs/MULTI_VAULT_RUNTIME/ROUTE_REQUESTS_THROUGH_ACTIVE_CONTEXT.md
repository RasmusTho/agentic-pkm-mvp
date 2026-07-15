---
name: Route Requests Through Active Context
description: Migrate production HTTP retrieval and governed-write paths to immutable request context
task_id: MVR-05
source_anchor: "docs/MULTI_VAULT_RUNTIME/README.md :: Active context and isolation"
parent_capability: Multi-vault runtime selection
prerequisites: [MVR-03, MVR-04]
depends_on: [VERSION_ACTIVE_CONTEXT_SELECTION.md, GROUP_VAULT_BINDINGS_BY_DIMENSION.md]
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
- Define two authenticated ingress carriers rather than collapsing request and session precedence:
  `X-Active-Context-Session` carries the client's retained session selection, while
  `X-Active-Context-Override` carries a one-request selection and outranks it. Both values are
  opaque `context_selection_id` bearers resolved by MVR-03; the override is never persisted into,
  or used to mutate, the session selection. Supplying an invalid value in either explicit carrier
  fails that request closed rather than falling through to the other carrier or the instance default.
- Migrate the existing Companion choose/open-vault picker **and fresh-vault initialize flow** with
  their current client state—not the
  deferred #2566 visual switcher—to create or replace a scoped selection, retain the returned
  `context_selection_id` for that client session, and send it as
  `X-Active-Context-Session` on vault-bound **read** requests in MVR-05B. Until MVR-05C activates
  governed scoped writes, the server also returns an opaque, authenticated
  `X-Compatibility-Write-Precondition` bound to that client's intended stable binding and exact
  compatibility revision. The migrated client sends this value—not its context bearer—on every
  vault-bound mutation through a distinct compatibility-scoped mutation route. That route identity
  is the server-verifiable client-mode marker: it always requires the precondition and never
  downgrades to the legacy route when the header is absent, malformed, expired, or stripped. The old
  mutation route remains only for the unchanged legacy request shape and cannot accept the migrated
  route's request contract; the new Companion code never calls it. The precondition selects no target
  and grants no authority; immediately before effect the
  server requires its binding/revision to equal the freshly resolved sole compatibility state or
  fails `capability_not_ready`. Thus client S1 retaining A cannot become an indistinguishable legacy
  B writer after client S2 moves the picker to B. Truly legacy clients remain carrier/precondition-
  free only on that separately identified old route for their existing one-vault journey against the
  fresh compatibility binding. MVR-05C
  switches mutation call sites to the scoped carrier in the same delivery that installs their
  DecisionToken/effect fence. On
  expiry/restart the client clears the stale ID and never retries the failed request via fallback.
  It then shows the visible reselection contract; it never remints from registry/default state
  because the ephemeral store cannot prove the stale bearer's former target. A genuinely new client
  that presents no stale explicit selection may independently resolve the normal default and create
  a new selection. Successful initialization atomically registers/sets
  the explicit default where the current one-vault journey requires it, then returns and persists a
  scoped selection for the new binding; it never relies on `last_active_vault_ref`. Any
  zero/many/ambiguous/default mismatch shows the existing reselection contract.
- Preserve and repair #3163 during the MVR-05→MVR-06 transition: before 05B can activate the scoped
  picker client, the legacy choose/open action must first commit a monotonic compatibility-binding
  revision to the production shared app-local/instance-state seam. The separately deployed watcher
  reconciles that durable revision and then applies the one Settings Spine reload/rebind path;
  `VaultChangedEvent` is only an in-process wake-up hint and never the cross-process handoff. Generic
  scoped request/session selections never mutate this record. From 05B until 06B takes ownership,
  every MVR-02 default set/clear producer also derives the candidate through canonical precedence and
  executes this same mutation-gate → prepare/old-root observation → default+compatibility commit →
  post-commit drain → resume transaction. It never commits the default before watcher/scalar-worker
  handoff; failure before commit leaves both default and binding unchanged, while post-commit recovery
  rolls forward. A deployed API-container → watcher-
  container test is required in #3163/05B. MVR-06 atomically initializes durable background intent
  from the then-current compatibility watcher revision and disables this bridge when its supervisor
  takes ownership; no release may leave both or neither mechanism active.
  Treat picker replacement plus compatibility rebind as one recoverable operation: stage the new
  selection as unusable and journal its prior/new binding and compatibility revisions. When a
  watcher lifecycle is enabled, the picker first closes a durable compatibility-mutation ingress
  gate, drains every old-binding mutation already admitted, and publishes a `prepare` revision. The
  watcher finishes its captured old tick and enters a durable handoff-observation state for A: it
  stops normal old-binding effects but keeps the filesystem subscription live, journals every A
  event, performs a reconciliation scan after the mutation drain, and acknowledges that exact
  prepare revision. The acknowledgement does not end observation. The watcher keeps buffering A
  events through the picker commit; after it observes the committed revision it performs a second
  reconciliation scan of A, drains the durable event buffer, and records the old-root handoff
  receipt before it may resolve or load B. This commit-bracketing observation window is the atomic
  filesystem cutoff: an Obsidian/direct-filesystem write after either pre-commit scan but before the
  selection commit is still reconciled under A even when an event hint is lost. The picker then
  atomically commits the new durable selection/compatibility binding and prior-selection
  invalidation before publishing `resume`; only
  that resume lets the watcher resolve/reload B and perform effects, and only the committed picker
  bearer is returned. An intentionally disabled or absent watcher is durably classified
  `no_lifecycle` by instance configuration/preflight, so the same picker commit does not wait for an
  acknowledgement that no process can produce; in that posture the mutation gate drains directly
  into the picker commit because no ingest lifecycle is promised. A failure or crash before the
  selection commit keeps the prior selection authoritative, issues a CAS-safe cancel/compensation,
  resumes the watcher on A, then reopens A mutation ingress; B has produced no effects. A failure
  after commit is recovered as committed: ingress remains blocked until recovery completes A's
  post-commit scan/buffer drain and publishes/reconciles resume, never compensated to A after B
  effects. Picker bridge operations serialize under the journal revision/CAS so recovery
  cannot roll back a later picker. This alignment invariant applies only to the picker transition
  being replaced: other clients' immutable scoped read sessions may legitimately remain on A while
  the one compatibility watcher follows the latest legacy picker B, and are never invalidated or
  redirected by the bridge.
- Resolve per-binding settings, paths, caches, retrieval scope, and write provenance from the
  snapshot. Settings keys are classified by the canonical settings registry as either
  `binding_local` (resolved and consumed only inside that binding's isolated sub-operation) or
  `request_wide_must_match` (model/provider, rerank policy, thresholds, limits, and any other value
  that shapes a combined operation). Before a many-binding request performs a read, cache fill,
  model call, or retrieval, resolve the complete effective bundle for every participating binding.
  Every `request_wide_must_match` key must have one identical typed effective value across the set,
  including uniformly applied authorized runtime/session overrides; otherwise fail the whole
  request with `incompatible_binding_settings` before effects. Never choose the first binding,
  merge by iteration order, compare only raw vault files, or combine results produced under
  incompatible request-wide behavior. Binding-local values never escape their binding's
  sub-operation, and result provenance records the settings bundle revision used there.
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
  still-scalar worker to recognize that envelope. It may dispatch only after acquiring the MVR-01
  host-global ownership fence and then that binding's cross-process shared effect lease. Under those
  fences production resolution
  proves the row names the worker's one explicit current compatibility binding and the worker's
  authorization, resolved root/fingerprint, and binding revision all still match. Other remembered
  registry entries are irrelevant and must not stall that uniquely bound worker. A missing,
  ambiguous, env-only, or mismatched worker binding leaves the
  row durably pending/unacknowledged, reports readiness `blocked_pending_mvr06`, and continues only
  independently safe `global` work. The worker releases the global fence after the stable snapshot
  but holds the shared lease through external dispatch, acknowledgement, and receipt; revocation,
  relocation, or removal therefore waits for an already-authorized effect or blocks it before effect.
  Before 05A enables that dispatch, it migrates every already-enabled GOV revocation producer to
  acquire the host-global ownership fence and the same binding's exclusive effect lease before
  advancing the authorization epoch. Removal and relocation remain capability-not-ready, but an
  enabled revocation can no longer cross the worker validation-to-dispatch window.
  MVR-06 owns multi-binding dispatch and governed quarantine
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
  for writes unless the command contract already provides one unambiguously. The target must be a
  member of the immutable request `ActiveContextSet.source_bindings`; every governed batch target
  must be a subset. Registry membership, ownership, and independent GOV authorization cannot widen
  the selected set. Reject an otherwise valid/authorized binding outside that set before token
  issuance or any effect.
- At every production filesystem, settings, projection, cache-fill, and retrieval read call site,
  acquire the MVR-01 host-global ownership fence and then the stable binding's cross-process shared
  effect lease. While both are held, require an active ownership lease for the current `(channel,
  vault_binding_id, canonical-root fingerprint)`, compare current binding revision/root and auth epoch
  with the request snapshot, and re-authorize the principal/scope/operation. Canonicalize the requested
  locator and resolve its nearest enclosing initialized vault boundary before I/O; that boundary must
  be the exact root of the declared target binding. A parent binding cannot read through an initialized
  nested child boundary, even when the child is registered on the same instance; the caller must
  select and independently authorize the child binding. An unregistered nested boundary fails closed.
  Release the global fence
  only after this stable snapshot is established, but hold the shared binding lease through data I/O,
  cache/response publication, and receipt. A pending, missing, released, or foreign-channel lease
  fails closed even when stale registry/selection still names the root. Relocation, removal, or
  revocation takes the matching exclusive lease and therefore drains the in-flight read or causes a
  stale-context/reauthorization error without stale data publication. Immutable request context alone
  is not an authorization lease.
- At every governed mutation seam, acquire the MVR-01 host-global ownership fence first and then the
  stable binding's cross-process shared effect lease. While both are held, re-resolve the target,
  require the matching active channel/binding/root ownership lease, compare current revision/root and
  auth epoch with the request snapshot, validate a live GOV `DecisionToken`, canonicalize the output
  locator, and require its nearest enclosing initialized vault boundary to equal that token's exact
  target binding root. Parent authority never crosses into an initialized nested child; targeting the
  child requires its own selected membership, GOV decision, and lease, while an unregistered nested
  boundary rejects the write. Release the global
  fence only after the stable snapshot is established, but hold the shared binding lease through the
  filesystem/store effect and receipt. Enabled GOV revocation acquires the global ownership fence
  and then the same binding's exclusive lease before changing authority state and waits for shared
  effects to drain. Registration removal is wired to that exclusive path but remains
  capability-not-ready until MVR-06B installs the background side of the consumer floor; relocation
  remains capability-not-ready until MVR-06C. The lock-order contract is host-global ownership fence → binding effect fence → registry/auth transaction →
  owner-store lock; no producer may invert it. A process-local mutex or check released before I/O is
  insufficient. Relocation, removal, or revocation racing before lease acquisition returns a
  stale-context/reauthorization error without writing; a change racing afterward waits until the
  already-authorized effect and receipt finish, then advances revision/epoch before later effects.
  Long-running owner transactions use the same lease for their full externally visible effect.
- Extend the canonical GOV token/receipt schema in this slice. A server-minted DecisionToken binds
  decision ID, authenticated human/delegated-role principal, instance identity, the exact
  ActiveContextSet context ID and generation, workspace identity/explicit no-workspace state,
  cognitive scope, sphere memberships, situated identity, selection-capability digest and complete
  selected binding set, action/write class, target stable vault binding, binding revision/root
  fingerprint, authorization epoch, issued/expiry times, and policy/delegation revision. Validation
  compares every field against current state immediately before mutation and proves the target
  remains a member of that immutable selected set. AuthorityReceipt references the token/decision
  and records the evaluated context generation/dimensions, target membership, and binding/auth revisions plus
  applied/denied/stale outcome without raw paths, bearer values, or secrets.
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

## Bounded implementation issue decomposition

This specification maps to four serial implementation issues and must never be filed as one child.
Each extracted issue copies a complete canonical Issue contract/SBS block and carries only the
acceptance criteria prefixed with its ID:

1. **MVR-05A — binding-keyed persistence cutover:** projection/outbox schema and backfill,
   idempotency classification, all-process mixed-version fence, minimum-runtime floor, duplicate-
   binding projection isolation, and an immediately shipped scalar-worker poll/ack compatibility
   gate holding the per-binding shared effect lease through dispatch/ack/receipt plus migration of
   every enabled GOV-revocation producer to the matching exclusive lease before dispatch activates,
   with a non-skippable
   real-PostgreSQL CI receipt and DB/deployment/release owner-doc
   writebacks.
2. **MVR-05B — request ingress and reads:** production resolver, picker, API/CLI/agent/MCP context
   propagation including distinct one-request-override and retained-session carriers, preserved
   cognitive dimensions plus separately server-derived per-call GOV action/permission, foreground
   channel-ownership lease enforcement, retrieval/cache
   provenance, pre-read revision/auth revalidation, and reuse of 05A's exclusive revocation fencing
   at every foreground producer, plus the pre-wired but still dormant removal and relocation
   producers. Cross-channel transfer remains
   capability-gated. It also installs the pre-05C mutation seal: any vault-bound write carrying a
   scoped session/override, or resolving differently from the sole named compatibility binding,
   fails `capability_not_ready` before the compatibility translator or filesystem/store seam. A
   migrated client uses the distinct compatibility-scoped mutation route and supplies an opaque
   expected-binding/revision precondition that must match that exact compatibility state. That route
   never falls back to the old route when the precondition is stripped; only a truly legacy request
   on the separately identified old route may retain the old single-binding write journey until 05C.
   This slice also owns stale selection, deterministic
   many-binding settings compatibility, the temporary #3163 picker bridge, and active-context/
   settings architecture writeback. Depends on 05A and #3163.
3. **MVR-05C — governed writes:** explicit target selection plus expanded DecisionToken/
   AuthorityReceipt producers, migration, fixtures, preflight, and the cross-process per-binding
   shared effect fence plus active channel-ownership lease spanning final revalidation through
   I/O/receipt. It reuses the exclusive GOV-revocation fence and dormant removal/relocation paths shipped by
   05B, proves write-side lock-order enforcement, and then enables cross-channel transfer, with governed-write
   owner-contract writeback. Depends on 05B.
4. **MVR-05D — outbox producers and delivery completion:** production envelope registry, binding-keyed
   dedup, remaining-producer migration and full worker delivery, event-contract writeback, and aggregate request
   acceptance. Depends on 05C and closes MVR-05.

Every partial state remains fenced as described in `Cross-Task Invariants / Interaction Safety`;
four distinct merged receipts are required on #2143.

Partial-delivery gates are explicit: after 05A, only the compatible new runtime may use the migrated
binding-keyed store and its scalar worker may poll/ack only a row matching its explicit current
single-binding compatibility context, authorization, revision, and root while holding the binding's
shared effect lease through dispatch, acknowledgement, and receipt; mismatched/ambiguous rows
remain pending/unacknowledged with blocked readiness while independent global work continues. Existing
single-vault watcher/ingest/capture/Heimdal producers remain live throughout 05A–05D through the 05A
compatibility ingress translator: it derives their one authoritative compatibility binding, validates
authority/revision/root immediately, and writes a complete versioned envelope (or fails that request
loudly), never a fresh legacy row. After 05B, that translator accepts either a truly legacy
carrier/precondition-free write whose fresh target equals the sole compatibility binding or a
migrated-client write whose opaque expected binding/revision matches that same fresh state. A scoped
write, stale/mismatched precondition, or missing precondition at a migrated production call site
fails before translation/effect, so client S2 cannot redirect client S1's intended A write into B.
05B enables scoped reads; 05C replaces this seal with governed explicit-target
writes and their native envelope; 05D removes the translator only after every producer has migrated
and proves no unscoped row appeared. No stage permits a legacy envelope, old scalar process, or
un-revalidated read/write to cross its floor; independently safe explicit-global work may continue.

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
- Owner-doc impact: each owning child updates in its PR: 05A `docs/DB_SCHEMA.md`, the durable envelope
  and worker-compatibility portions of `docs/EVENTS.md`, deployment, and release channels; 05B
  `docs/ARCHITECTURE.md` and `docs/SETTINGS.md`; 05C
  `docs/contracts/GOVERNED_WRITE_PROTOCOL.md`; 05D completes `docs/EVENTS.md` with the later producer,
  delivery, and idempotency behavior
- Transition debt impact: reduces D1 and request-side D13 global-binding debt
- Fitness rule impact: adds production-entrypoint context-boundary guard

## Constraints

- No route accepts a client path as authority or silently falls back on selection failure.
- Cross-vault reads retain source provenance; writes name exactly one authorized target per
  operation unless an existing governed batch contract explicitly covers several.
- Preserve current response shapes for no-vault and single-vault callers unless additive context
  provenance is required.

## Acceptance Criteria

- [ ] **MVR-05B:** Two production API sessions read different vaults concurrently without cross-talk or global
  mutation.
  - Verify: `tests/integration/test_multi_vault_request_isolation.py::test_two_sessions_use_distinct_vaults_without_cross_talk`
- [ ] **MVR-05B:** Production retrieval over several bindings preserves source vault and context generation on
  every result and cache lookup.
  - Verify: `tests/retrieval/test_multi_vault_retrieval.py::test_production_retrieval_preserves_binding_provenance`
- [ ] **MVR-05B:** A production many-binding request resolves every participating binding's complete
  effective settings bundle before work begins. Binding-local settings stay inside their isolated
  sub-operation, while every registry-classified request-wide setting must resolve to one identical
  typed value across the set; a conflict fails the whole request with
  `incompatible_binding_settings` before reads, cache fills, model calls, or retrieval, without
  iteration-order selection or partial results.
  - Verify: `tests/integration/test_multi_vault_settings_resolution.py::test_many_binding_request_fails_before_effect_when_request_wide_settings_conflict`
- [ ] **MVR-05A:** Two registered bindings containing the same artifact UUID retain independent object,
  file-state, vector/index, retrieval, and receipt provenance without overwrite or cross-read.
  - Verify: `tests/integration/test_multi_vault_projection_isolation.py::test_duplicate_uuid_is_namespaced_by_binding`
- [ ] **MVR-05A:** Legacy single-vault projection rows backfill only with one provable binding; ambiguous rows
  block mixed-mode startup until quarantined/rebuilt, without destructive guessing.
  - Verify: `tests/migrations/test_multi_vault_projection_backfill.py::test_projection_backfill_is_unambiguous_or_fails_loud`
- [ ] **MVR-05A:** Projection/outbox migration, uniqueness, foreign-key, and binding-keyed dedup targets
  execute against the provisioned real PostgreSQL service in repository CI on the exact delivery
  SHA; the tests error rather than skip when PostgreSQL or required constraints are absent.
  - Verify: `tests/architecture/test_multi_vault_pg_ci_lane.py::test_mvr05_pg_targets_run_on_provisioned_postgres_and_cannot_skip` +
    successful exact-SHA `integration-nightly / pg-contracts` workflow receipt on #2143
- [ ] **MVR-05A:** Before any binding-keyed producer starts, all pending legacy outbox keys are classified and
  scoped/coalesced under the DB fence; an identical retry produces one canonical dispatch lineage,
  while conflicting or ambiguous rows quarantine and cannot later duplicate the upgraded event.
  - Verify: `tests/migrations/test_multi_vault_outbox_upgrade.py::test_legacy_idempotency_keys_coalesce_before_new_producer_enable`
- [ ] **MVR-05A:** The migration records the MVR-05 minimum-runtime floor before any binding-keyed database
  state is written; scalar rollback then fails before starting an old API/worker, including on a
  one-binding instance, while a compatible roll-forward retains the full lineage.
  - Verify: `tests/migrations/test_multi_vault_projection_backfill.py::test_projection_upgrade_blocks_scalar_rollback_before_first_write`
- [ ] **MVR-05A:** Pinned-image deployment fences writes/dequeue, drains and stops the old scalar API/worker,
  every enabled watcher, Heimdal, capture, and auxiliary DB/outbox producer, and proves none can
  restart or retain a DB session before setting the floor or running the binding-keyed migration;
  fault injection leaves the floor/database untouched or requires compatible roll-forward.
  - Verify: `tests/ops/test_mvr05_mixed_version_fence.py::test_all_old_scalar_db_clients_are_stopped_before_binding_keyed_migration`
- [ ] **MVR-05A:** The deployment fence inventory is generated from production compose/runtime producer truth and
  fails when any enabled process that can call the DB/outbox seam is absent from the drain/stop plan.
  - Verify: `tests/ops/test_mvr05_mixed_version_fence.py::test_fence_inventory_covers_every_enabled_db_outbox_process`
- [ ] **MVR-05A:** Existing vault-bound watcher/ingest and Heimdal vault-note projection producers
  remain live across 05A–05D through the compatibility ingress translator, which derives one
  authorized binding and emits a complete versioned envelope or fails loud. Vault-independent raw
  Heimdal capture/observation remains explicitly `global` and needs no invented vault binding; no
  fresh legacy row can appear while later native producer migrations remain pending.
  - Verify: `tests/ops/test_mvr05_mixed_version_fence.py::test_compatibility_translator_keeps_existing_producers_live_without_legacy_rows`
- [ ] **MVR-05A:** Before any migrated vault-bound row is polled, the recreated scalar worker validates
  its explicit compatibility binding, authority, revision, and root; a mismatched or ambiguous row
  remains pending/unacknowledged with blocked readiness, while explicit-global work remains processable.
  It holds the binding shared-effect lease from final validation through dispatch, acknowledgement,
  and receipt, so concurrent revocation/removal/relocation cannot complete across an effect window.
  - Verify: `tests/workers/test_multi_vault_partial_delivery_gate.py::test_mvr05a_scalar_worker_gates_migrated_rows_before_dispatch`
- [ ] **MVR-05A:** Before vault-bound worker dispatch activates, every enabled GOV-revocation
  production path takes the ownership fence and matching exclusive binding lease before advancing
  authorization state; a revocation after worker validation either blocks dispatch or waits for the
  authorized dispatch, acknowledgement, and receipt to finish. Removal/relocation stay dormant.
  - Verify: `tests/workers/test_multi_vault_partial_delivery_gate.py::test_mvr05a_revocation_cannot_cross_worker_dispatch_effect_window`
- [ ] **MVR-05C:** Production capture/governed-write paths require one explicit authorized target,
  reject an otherwise registered/owned/GOV-authorized target outside the immutable selected binding
  set (and any batch that is not a subset), and record vault/context provenance in their receipt.
  - Verify: `tests/api/test_multi_vault_governed_writes.py::test_capture_uses_explicit_authorized_target_and_receipt`
  - Verify: `tests/api/test_multi_vault_governed_writes.py::test_write_target_must_belong_to_active_context_set`
- [ ] **MVR-05C:** GOV revocation after request resolution but before
  commit invalidates the current DecisionToken/binding revision and blocks the in-flight mutation
  without writing. Production removal/relocation remain capability-not-ready and are proved after
  activation by MVR-06B/MVR-06C.
  - Verify: `tests/api/test_multi_vault_governed_writes.py::test_authority_change_blocks_inflight_write_before_commit`
- [ ] **MVR-05C:** Production governed writes hold the cross-process per-binding shared effect lease from
  final revalidation through filesystem/store mutation and receipt. Enabled revocation uses the same
  binding's exclusive lease, while removal/relocation remain capability-not-ready on their pre-wired
  exclusive paths until 06B/06C; an injected enabled change after validation but before I/O either blocks
  the write before effect or waits until its authorized effect completes under the old revision.
  - Verify: `tests/integration/test_multi_vault_write_effect_fence.py::test_authority_change_cannot_cross_validation_write_window`
- [ ] **MVR-05B:** GOV revocation after request resolution but before a production
  filesystem/retrieval/cache read cannot cross the effect window: the read holds the shared binding
  lease from final revalidation through I/O and cache/response publication. This slice reuses the
  05A ownership-fence → exclusive-binding-lease protocol at every foreground revocation call site
  and either waits or prevents stale data publication; removal and relocation are wired to that path
  but still return capability-not-ready. No unfenced locator/authority producer remains enabled in
  the independently mergeable 05B state.
  - Verify: `tests/integration/test_multi_vault_request_isolation.py::test_authority_change_cannot_cross_read_effect_window`
- [ ] **MVR-05B:** Every production filesystem/retrieval read resolves the canonical locator's
  nearest enclosing initialized vault boundary and requires it to equal the declared target binding
  root. Parent-only selection/authority cannot read an initialized registered or unregistered nested
  child, while an independently selected and GOV-authorized child binding can.
  - Verify: `tests/integration/test_multi_vault_nested_effect_boundary.py::test_parent_authority_cannot_read_registered_child_vault`
- [ ] **MVR-05C:** Every production filesystem/store write resolves the canonical locator's nearest
  enclosing initialized vault boundary and requires it to equal the DecisionToken target binding
  root. A parent-targeted write cannot enter an initialized registered or unregistered nested child;
  writing the child requires its own selected membership, GOV decision, and shared effect lease.
  - Verify: `tests/integration/test_multi_vault_nested_effect_boundary.py::test_parent_authority_cannot_write_registered_child_vault`
- [ ] **MVR-05B:** With cross-channel transfer still dormant, production request resolution and read
  seams require the current channel's active binding/root-fingerprint lease. A staged transfer
  simulation followed by source restart proves stale source registry/selection state cannot read the
  destination-owned root.
  - Verify: `tests/integration/test_multi_vault_channel_transfer_foreground.py::test_source_restart_cannot_read_after_staged_channel_lease_transfer`
- [ ] **MVR-05C:** After both production read and governed-write lease seams are installed, MVR-05C
  atomically advances the foreground-ownership floor and enables MVR-01B cross-channel transfer. The
  production transfer/restart scenario rejects reads and writes from the stale source before token
  use or filesystem effect, while the destination can access only under its freshly minted
  destination-local binding ID, matching active lease, immutable source/destination lineage, and
  current GOV authorization; failure to advance the floor leaves transfer dormant.
  - Verify: `tests/integration/test_multi_vault_channel_transfer_foreground.py::test_source_restart_cannot_write_after_channel_lease_transfer`
  - Verify: `tests/integration/test_multi_vault_channel_transfer_foreground.py::test_destination_uses_minted_binding_and_transfer_lineage`
- [ ] **MVR-05C:** Transfer invokes the MVR-02 and MVR-04 journal hooks to atomically clear or
  explicitly replace the source default and remove the source binding from every dimension before
  retirement; destination default/dimension membership is never inferred, and recovery exposes no
  dangling or duplicated reference.
  - Verify: `tests/integration/test_vault_registry_channel_isolation.py::test_transfer_repairs_source_default_and_dimensions_before_retirement`
- [ ] **MVR-05C:** Transfer invokes the MVR-05A drain hook and cannot change binding identity while
  any source-bound outbox/queue row is unsettled. Every row reaches a terminal receipted outcome
  under the source ID with idempotency lineage preserved; failure aborts before source retirement
  without retargeting the row.
  - Verify: `tests/integration/test_vault_registry_channel_isolation.py::test_transfer_drains_source_bound_rows_before_destination_id_activation`
- [ ] **MVR-05C:** The production capture path issues, persists, validates, and receipts the expanded
  token bound to principal/instance plus exact context ID/generation, workspace/no-workspace,
  cognitive dimensions, selection digest and complete selected set, as well as target binding
  revision/auth epoch. A token replayed under a different generation, workspace, sphere, situated
  identity, selection, or target membership fails before mutation; legacy-shaped tokens and stale
  epochs fail, and all token producers/fixtures satisfy the same schema.
  - Verify: `tests/api/test_multi_vault_governed_writes.py::test_capture_token_binds_exact_active_context_and_target_membership`
- [ ] **MVR-05D:** A production producer registry and architecture guard enumerate every vault-bound watcher,
  API/ingest/capture, Heimdal, and shared outbox call site; no unregistered call site can emit a
  legacy envelope.
  - Verify: `tests/architecture/test_multi_vault_context_boundaries.py::test_vault_bound_outbox_producers_cannot_emit_legacy_envelopes`
- [ ] **MVR-05D:** Invoking every registered production vault-bound producer emits the versioned stable-binding,
  context, routing-class, and idempotency envelope without fixture-only row construction.
  - Verify: `tests/integration/test_multi_vault_outbox_producers.py::test_production_call_sites_emit_binding_context_envelopes`
- [ ] **MVR-05D:** After every vault-bound producer is migrated, the worker consumes only complete
  versioned envelopes under the binding/context delivery contract and retains the 05A fail-closed
  treatment for corrupt, mismatched, or ambiguous rows.
  - Verify: `tests/workers/test_multi_vault_partial_delivery_gate.py::test_completed_worker_delivery_retains_mvr05a_fail_closed_gate`
- [ ] **MVR-05D:** Vault-bound outbox idempotency keys include the stable binding: duplicate logical identities
  in two bindings persist independently, while same-binding retries deduplicate.
  - Verify: `tests/services/test_multi_vault_outbox_idempotency.py::test_duplicate_identity_events_are_deduplicated_per_binding`
- [ ] **MVR-05B:** Invalid or unauthorized request selection returns the explicit error/picker contract and
  never serves default, last-active, CWD, or another binding.
  - Verify: `tests/api/test_multi_vault_request_fail_closed.py::test_invalid_selection_never_falls_back`
- [ ] **MVR-05B:** `X-Active-Context-Override` outranks `X-Active-Context-Session` for exactly one
  production request without mutating the retained session; an invalid explicit override fails closed
  rather than using the valid session selection.
  - Verify: `tests/api/test_active_context_resolution.py::test_request_override_header_outranks_session_without_mutating_it`
- [ ] **MVR-05B:** One retained selection bearer can drive an authorized production read and, later,
  an independently authorized governed-write request because action/write class/permission is
  server-derived per call rather than stored as selection authority; cognitive scope/sphere/situated
  identity remains unchanged and a denied operation stays denied without widening the bearer.
  - Verify: `tests/integration/test_multi_vault_picker_context.py::test_session_selection_reuses_bindings_with_per_request_server_scope`
- [ ] **MVR-05B:** Until MVR-05C replaces the compatibility write path, every production vault-bound
  mutation carrying a scoped session/override—or resolving to a target other than the sole freshly
  revalidated compatibility binding—fails `capability_not_ready` before the translator and before
  filesystem/store/outbox effects. Every migrated picker-client mutation carries an opaque
  authenticated expected-binding/revision precondition through the distinct compatibility-scoped
  mutation route; stale, missing, stripped, or mismatched preconditions fail before effect and the
  route cannot retry or downgrade through the old endpoint. The precondition never selects a target
  or grants authority. A truly legacy carrier/precondition-free single-binding write to the exact
  compatibility binding remains available only on the separately identified old route. If
  S1 retains A and S2 moves the compatibility picker to B, S1's mutation fails rather than becoming
  a legacy B write.
  - Verify: `tests/integration/test_multi_vault_partial_delivery.py::test_scoped_write_is_sealed_until_mvr05c`
  - Verify: `tests/integration/test_multi_vault_partial_delivery.py::test_migrated_client_write_precondition_prevents_cross_client_compatibility_redirect`
  - Verify: `tests/integration/test_multi_vault_partial_delivery.py::test_migrated_write_route_rejects_stripped_precondition_without_legacy_downgrade`
- [ ] **MVR-05B:** The production request dependency resolves and propagates exactly one immutable
  ActiveContextSet per request, including preserved cognitive dimensions and active ownership lease
  evidence, while passing action/write class/permission separately to GOV without consulting mutable
  global selection again.
  - Verify: `tests/api/test_active_context_resolution.py::test_request_uses_one_context_generation_end_to_end`
- [ ] **MVR-05B:** The shipped Companion picker creates/replaces a scoped selection and its client sends that
  bearer ID through production read requests; choosing B changes later reads to B, and stale-ID
  recovery with zero, many, ambiguous, or default-mismatched bindings visibly asks for reselection.
  - Verify: `tests/integration/test_multi_vault_picker_context.py::test_existing_picker_drives_scoped_request_context`
- [ ] **MVR-05C:** The scoped picker client sends its bearer context through a production governed-write
  request, which targets the selected binding only after MVR-05C's DecisionToken/authority gate.
  - Verify: `tests/integration/test_multi_vault_picker_context.py::test_scoped_picker_governed_write_targets_selected_binding`
- [ ] **MVR-05B:** A fresh no-vault production initialize first obtains a short-lived, single-use,
  authenticated bootstrap precondition bound to the canonical target fingerprint, empty-registry
  revision, no-compatibility state, and initialization confirmation. Execution revalidates that
  exact precondition under the ownership/registry lock, reserves the first binding and compatibility
  revision, performs initialization, and atomically establishes the explicit default plus scoped
  selection; failure before content effect leaves no registry/default/compatibility record, while
  failure after effect recovers forward idempotently. This bootstrap token selects no general write
  target, grants no authority, and cannot be replayed once registry/revision state changes. The
  immediately following vault-bound request resolves the binding without last-active fallback.
  - Verify: `tests/integration/test_multi_vault_picker_context.py::test_fresh_vault_initialize_returns_usable_scoped_context`
  - Verify: `tests/integration/test_multi_vault_picker_context.py::test_first_vault_initialize_bootstrap_is_single_use_and_failure_atomic`
- [ ] **MVR-05B:** After API restart, a stale bearer never authorizes, falls back, retries, or
  transparently remints for any request. Because the ephemeral store cannot prove which binding the
  stale bearer named, even a sole authorized binding equal to the default requires visible
  reselection. A new client with no stale explicit intent may independently resolve the normal
  instance default; it is not recovery of the stale session.
  - Verify: `tests/integration/test_multi_vault_picker_context.py::test_stale_selection_restart_requires_visible_reselection`
- [ ] **MVR-05B:** Before MVR-06 takes ownership, the legacy choose/open picker and every MVR-02
  default set/clear producer drive #3163's single-watcher rebind through the shared bracketing
  transaction that the separately deployed watcher reconciles before reload/effects, while an
  in-memory event is only a hint. Default mutation either commits atomically with compatibility
  handoff or fails before changing the default. Generic scoped session/request selection does not
  mutate it, and the bridge is named and guarded for atomic retirement by MVR-06.
  - Verify: `tests/integration/test_multi_vault_picker_context.py::test_legacy_picker_bridge_preserves_single_watcher_until_mvr06`
  - Verify: `tests/integration/test_multi_vault_picker_context.py::test_interim_default_mutation_rebinds_before_foreground_commit`
- [ ] **MVR-05B:** Picker replacement and the #3163 compatibility watcher rebind are recoverable as
  one operation. Before prepare, carrier-free compatibility mutations are durably gated and drained;
  the enabled watcher scans A, acknowledges a durable prepared/quiescent revision without effects
  on B, and retains durable old-root event observation through selection commit. After commit it
  completes the bracketing A scan/buffer drain and handoff receipt before a resume revision may
  permit B effects. A direct-filesystem write after the pre-commit scan but before commit remains an
  A write and cannot be stranded, including when its event hint is lost. Pre-commit faults
  cancel/compensate while B has no effects, resume A, and reopen A ingress; post-commit faults recover
  forward and block ingress until the A drain and resume complete. An intentionally
  disabled/absent watcher is a durable `no_lifecycle` outcome and needs no process acknowledgement.
  Concurrent picker operations serialize, while unrelated clients' existing scoped reads remain
  valid on their immutable bindings and may intentionally differ from the single watcher.
  - Verify: `tests/integration/test_multi_vault_picker_context.py::test_picker_and_watcher_rebind_is_failure_atomic`
  - Verify: `tests/integration/test_multi_vault_picker_context.py::test_prepare_drains_old_binding_writes_before_quiescent_ack`
  - Verify: `tests/integration/test_multi_vault_picker_context.py::test_direct_filesystem_write_between_scan_and_commit_is_receipted_under_old_binding`
  - Verify: `tests/integration/test_multi_vault_picker_context.py::test_picker_commit_succeeds_with_durable_no_lifecycle_watcher_posture`
- [ ] **MVR-05B:** Request-bound production code cannot introduce new direct global vault resolution outside
  named compatibility adapters.
  - Verify: `tests/architecture/test_multi_vault_context_boundaries.py::test_request_consumers_use_context_seam`
- [ ] **MVR-05D:** The parent request acceptance target composes two-session isolation, resolution precedence,
  fail-closed stale selection, projection separation, retrieval provenance, and governed writes on
  the production request seam.
  - Verify: `tests/integration/test_multi_vault_request_isolation.py::test_parent_request_context_acceptance`
- [ ] **MVR-05B:** Production resolution applies explicit selection, instance default, and no-vault precedence
  without consulting last-active, CWD, or another binding after an invalid explicit choice.
  - Verify: `tests/integration/test_multi_vault_resolution.py::test_resolution_precedence_and_fail_closed_behavior`
- [ ] **MVR-05A:** DB, deployment, and release owner contracts describe the shipped binding-keyed
  projection/outbox schema, migration and idempotency classification, minimum-runtime floor, and
  all-process fenced cutover in the same PR.
  - Verify: doc writeback at `docs/DB_SCHEMA.md :: DB Schema (Current Reality)` + doc writeback at
    `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md :: Deployment and Environments` + doc writeback at
    `docs/RELEASE_CHANNELS/README.md :: Release Channels Specification` + doc writeback at
    `docs/EVENTS.md :: Outbox envelope (canonical)`
- [ ] **MVR-05B:** The architecture owner contract describes the shipped immutable request context,
  scoped selection/read resolution, and immediately-before-read revision/auth enforcement.
  - Verify: doc writeback at `docs/ARCHITECTURE.md :: Active context and vault bindings`
- [ ] **MVR-05B:** The settings owner document describes the shipped instance versus request/binding
  scope and no longer presents global `VAULT_ROOT` or compiled-vault state as request authority.
  - Verify: doc writeback at `docs/SETTINGS.md :: Runtime settings (compiled)`
- [ ] **MVR-05C:** The governed-write owner contract describes the shipped expanded DecisionToken/
  AuthorityReceipt fields and immediately-before-write validation.
  - Verify: doc writeback at `docs/contracts/GOVERNED_WRITE_PROTOCOL.md :: GovernedWriteProtocol`
- [ ] **MVR-05D:** The event owner contract describes the shipped binding/context envelope,
  routing class, binding-keyed idempotency, and producer/worker compatibility posture.
  - Verify: doc writeback at `docs/EVENTS.md :: Events`

## Out of Scope

- Watcher/worker lifecycle, the new visual switcher/overlay behavior owned by #2566,
  registry/default/dimension storage, or removing all compatibility adapters.

## How to Verify (Pre-Merge)

Issue extraction copies only the matching child subsection plus the shared gates. Each selector below
maps directly to that child ID; an early child never runs a later slice's acceptance target.

### MVR-05A validation

- `pytest -q tests/integration/test_multi_vault_projection_isolation.py::test_duplicate_uuid_is_namespaced_by_binding tests/migrations/test_multi_vault_projection_backfill.py::test_projection_backfill_is_unambiguous_or_fails_loud tests/migrations/test_multi_vault_projection_backfill.py::test_projection_upgrade_blocks_scalar_rollback_before_first_write tests/migrations/test_multi_vault_outbox_upgrade.py::test_legacy_idempotency_keys_coalesce_before_new_producer_enable tests/ops/test_mvr05_mixed_version_fence.py::test_all_old_scalar_db_clients_are_stopped_before_binding_keyed_migration tests/ops/test_mvr05_mixed_version_fence.py::test_fence_inventory_covers_every_enabled_db_outbox_process tests/ops/test_mvr05_mixed_version_fence.py::test_compatibility_translator_keeps_existing_producers_live_without_legacy_rows tests/workers/test_multi_vault_partial_delivery_gate.py::test_mvr05a_scalar_worker_gates_migrated_rows_before_dispatch tests/architecture/test_multi_vault_pg_ci_lane.py::test_mvr05_pg_targets_run_on_provisioned_postgres_and_cannot_skip`
- `pytest -q tests/workers/test_multi_vault_partial_delivery_gate.py::test_mvr05a_revocation_cannot_cross_worker_dispatch_effect_window`
- Dispatch exact-head `.github/workflows/integration-nightly.yaml` job `pg-contracts`, whose asserted
  MVR-05A manifest runs the binding-keyed migration/backfill/dedup targets against provisioned
  PostgreSQL and errors rather than skips; attach its URL and SHA to #2143.
- Verify the 05A PR diff contains its mapped `docs/DB_SCHEMA.md`, `docs/EVENTS.md` durable-envelope,
  deployment, and release owner-doc writebacks.

### MVR-05B validation

- `pytest -q tests/integration/test_multi_vault_request_isolation.py::test_two_sessions_use_distinct_vaults_without_cross_talk tests/integration/test_multi_vault_request_isolation.py::test_authority_change_cannot_cross_read_effect_window tests/integration/test_multi_vault_nested_effect_boundary.py::test_parent_authority_cannot_read_registered_child_vault tests/integration/test_multi_vault_channel_transfer_foreground.py::test_source_restart_cannot_read_after_staged_channel_lease_transfer tests/retrieval/test_multi_vault_retrieval.py::test_production_retrieval_preserves_binding_provenance tests/integration/test_multi_vault_settings_resolution.py::test_many_binding_request_fails_before_effect_when_request_wide_settings_conflict tests/api/test_multi_vault_request_fail_closed.py::test_invalid_selection_never_falls_back tests/api/test_active_context_resolution.py::test_request_override_header_outranks_session_without_mutating_it tests/api/test_active_context_resolution.py::test_request_uses_one_context_generation_end_to_end tests/integration/test_multi_vault_picker_context.py::test_session_selection_reuses_bindings_with_per_request_server_scope tests/integration/test_multi_vault_partial_delivery.py::test_scoped_write_is_sealed_until_mvr05c tests/integration/test_multi_vault_picker_context.py::test_existing_picker_drives_scoped_request_context tests/integration/test_multi_vault_picker_context.py::test_fresh_vault_initialize_returns_usable_scoped_context tests/integration/test_multi_vault_picker_context.py::test_stale_selection_restart_requires_visible_reselection tests/integration/test_multi_vault_picker_context.py::test_legacy_picker_bridge_preserves_single_watcher_until_mvr06 tests/integration/test_multi_vault_picker_context.py::test_interim_default_mutation_rebinds_before_foreground_commit tests/integration/test_multi_vault_picker_context.py::test_picker_and_watcher_rebind_is_failure_atomic tests/integration/test_multi_vault_picker_context.py::test_prepare_drains_old_binding_writes_before_quiescent_ack tests/integration/test_multi_vault_picker_context.py::test_picker_commit_succeeds_with_durable_no_lifecycle_watcher_posture tests/architecture/test_multi_vault_context_boundaries.py::test_request_consumers_use_context_seam tests/integration/test_multi_vault_resolution.py::test_resolution_precedence_and_fail_closed_behavior`
- `pytest -q tests/integration/test_multi_vault_partial_delivery.py::test_migrated_client_write_precondition_prevents_cross_client_compatibility_redirect tests/integration/test_multi_vault_partial_delivery.py::test_migrated_write_route_rejects_stripped_precondition_without_legacy_downgrade tests/integration/test_multi_vault_picker_context.py::test_direct_filesystem_write_between_scan_and_commit_is_receipted_under_old_binding`
- `pytest -q tests/integration/test_multi_vault_picker_context.py::test_first_vault_initialize_bootstrap_is_single_use_and_failure_atomic`
- Verify the 05B PR diff contains its mapped `docs/ARCHITECTURE.md` and `docs/SETTINGS.md` writebacks.

### MVR-05C validation

- `pytest -q tests/api/test_multi_vault_governed_writes.py::test_capture_uses_explicit_authorized_target_and_receipt tests/api/test_multi_vault_governed_writes.py::test_write_target_must_belong_to_active_context_set tests/api/test_multi_vault_governed_writes.py::test_authority_change_blocks_inflight_write_before_commit tests/api/test_multi_vault_governed_writes.py::test_capture_token_binds_exact_active_context_and_target_membership tests/integration/test_multi_vault_write_effect_fence.py::test_authority_change_cannot_cross_validation_write_window tests/integration/test_multi_vault_nested_effect_boundary.py::test_parent_authority_cannot_write_registered_child_vault tests/integration/test_multi_vault_channel_transfer_foreground.py::test_source_restart_cannot_write_after_channel_lease_transfer tests/integration/test_multi_vault_channel_transfer_foreground.py::test_destination_uses_minted_binding_and_transfer_lineage tests/integration/test_vault_registry_channel_isolation.py::test_transfer_repairs_source_default_and_dimensions_before_retirement tests/integration/test_vault_registry_channel_isolation.py::test_transfer_drains_source_bound_rows_before_destination_id_activation tests/integration/test_multi_vault_picker_context.py::test_scoped_picker_governed_write_targets_selected_binding`
- Verify the 05C PR diff contains its mapped `docs/contracts/GOVERNED_WRITE_PROTOCOL.md` writeback.

### MVR-05D validation

- `pytest -q tests/architecture/test_multi_vault_context_boundaries.py::test_vault_bound_outbox_producers_cannot_emit_legacy_envelopes tests/integration/test_multi_vault_outbox_producers.py::test_production_call_sites_emit_binding_context_envelopes tests/workers/test_multi_vault_partial_delivery_gate.py::test_completed_worker_delivery_retains_mvr05a_fail_closed_gate tests/services/test_multi_vault_outbox_idempotency.py::test_duplicate_identity_events_are_deduplicated_per_binding tests/integration/test_multi_vault_request_isolation.py::test_parent_request_context_acceptance`
- Verify the 05D PR diff contains its mapped `docs/EVENTS.md` writeback.

Every child also runs `mypy app`, `pytest -q -m "not pg"`, and `ruff check app tests` as shared repo
gates; those gates do not substitute for its exact mapped selectors above.

## Restart / Durability Posture

Request contexts are not durable. Durable effects remain the existing governed content writes and
receipts, now carrying binding/generation provenance. After restart, clients resolve a fresh
session/default context and never inherit an unrecorded process selection.

## Related Docs

- `docs/MULTI_VAULT_RUNTIME/README.md`
- `docs/contracts/ACTIVE_CONTEXT_SET.md`
- `docs/ARCHITECTURE.md`

## Related GitHub Issues

Create the four serial children in `Bounded implementation issue decomposition` under #2143 after
MVR-03/04, adding the #3163 dependency at 05B. Use Sol/high for binding-key schema/backfill and
authority review; Terra/high is acceptable only for the mechanically bounded call-site work after
those gates are fixed. This family owns compatibility migration of the already-shipped picker;
#2566 remains the separate downstream visual switcher/overlay issue.
