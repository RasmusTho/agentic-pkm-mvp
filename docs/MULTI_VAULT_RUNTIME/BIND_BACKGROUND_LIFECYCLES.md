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

- Reuse #3163's durable monotonic cross-process selection revision plus its one settings-reload/
  rebind mechanism; do not duplicate it. `VaultChangedEvent` remains only a same-process wake-up
  hint and is never treated as delivery between the API and watcher containers.
- At the MVR-06 migration boundary, read the live binding owned by MVR-05's named legacy-picker
  bridge, materialize that binding as durable `compatibility_binding_id` in compatibility mode,
  start the revision-reconciling supervisor, and disable the bridge in one fail-closed cutover. Roll back
  the cutover if either handoff step fails. Afterward, the production legacy choose/open picker
  producer and replacement supervisor preserve #3163's full two-phase protocol while mode is
  `compatibility`: close/drain compatibility-mutation ingress, prepare the candidate revision, final-
  scan and quiesce normal old-binding effects while retaining a durable old-root event buffer through
  commit, then atomically commit `compatibility_binding_id`, provenance, and revision. After commit it
  performs the bracketing old-root scan/buffer drain and records the handoff receipt before resume.
  The supervisor cannot resolve/reload/perform candidate-binding effects
  before committed resume. Pre-commit failure resumes the old lifecycle and reopens old-binding
  ingress; post-commit failure recovers forward with ingress blocked. Durable phase/revision truth,
  not the wake-up hint, closes event-loss and restart windows. Generic request/session selection
  never changes background intent. Once a governed add/remove command enters `explicit` mode, picker
  and default changes cannot alter the explicit set.
- Add a durable, mechanical instance-local `background_vault_binding_ids` intent set. Request or
  session selection never auto-enrols a member. Each unique binding is re-resolved and
  re-authorized at lifecycle start; a missing/unauthorized member remains explicitly failed.
- Persist an intent mode that distinguishes `compatibility` from `explicit`. A missing legacy field
  is initialized exactly once as compatibility mode: MVR-06 snapshots the live bridge binding when
  present, otherwise resolves the current instance default, then the explicit legacy bootstrap
  (`VAULT_ROOT`/`WATCHER_VAULT_PATH` through the MVR-02 adapter and the stable registration produced
  by MVR-01B), then no-vault, into nullable durable
  `compatibility_binding_id`. Restart reuses that exact binding and never re-derives another from
  unrecorded interaction history or default. While mode remains compatibility, a production legacy
  choose/open command or explicit MVR-02 default set/clear derives a candidate and routes it through
  the same prepare/quiesce/commit/resume transaction before publishing a rebind hint. Default set
  selects that explicit binding. Default clear re-runs MVR-02 precedence after removal—registered
  legacy bootstrap, then truthful no-vault—so an env-backed one-vault watcher is not idled while
  foreground resolution still selects its bootstrap binding. The commit atomically replaces
  `compatibility_binding_id` with that resolved binding or nullable no-vault and stores event
  provenance in the revision. The first governed add/remove command never starts from an implicit
  empty set: under the same locked revision-checked transaction it snapshots the effective
  compatibility singleton (`{compatibility_binding_id}`), or the truthful empty set when
  compatibility is no-vault, then applies the requested add/remove and commits the result as
  explicit. Adding the same member or removing a nonmember is idempotent against that snapshot;
  removing the compatibility member yields explicit-empty. While 06B permits at most one explicit
  member, adding a different member to a non-empty compatibility snapshot would yield two and
  therefore fails `capability_not_ready` without changing mode or state; replacement requires an
  explicit remove followed by add. `explicit` with an empty binding list is durable and means idle—it
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
- Own the background-principal producer rather than inventing identity inside the supervisor. MVR-06
  first atomically advances `minimum_runtime_schema=MVR-06` under the MVR-05 channel fence and proves
  every API/watcher/worker candidate understands the role, delegation, intent, and compatibility
  schemas; no role/delegation producer may run before that floor commits. It then
  creates a distinct opaque `background_runtime_role_id` in private versioned auth/GOV state,
  delegated from MVR-03's `local_operator_role_id` with schema/revision and delegation provenance.
  Its least-privilege scopes cover only the watcher, worker, settings, queue, and receipt operations
  required for an authorized binding; it cannot exceed its delegator and is independent of API-key
  rotation, human identity, and `appInstallId`. Existing-install migration, channel/native bootstrap,
  and production fixtures create and validate this role before the supervisor starts. Missing,
  ambiguous, over-broad, stale, or partially persisted delegation fails preflight; GOV revocation
  advances the auth epoch and drains affected lifecycles before their next effect.
- Introduce a lifecycle supervisor that treats the durable set only as intent. At start/rebind it
  derives one immutable full `ActiveContextSet` per lifecycle binding, including context ID,
  generation, stable binding, server-derived instance-background principal, explicit cognitive
  scope/sphere/situated-identity values, topology posture, typed `no_workspace` (instance background
  work is not silently assigned to a human workspace), and a non-reversible domain-separated
  background capability digest derived server-side from instance identity, durable intent ID/
  revision, binding, and generation. This digest occupies the required context-capability identity
  field without inventing a bearer selection and never grants authority. Selection provenance is
  `background_intent`,
  `compatibility_handoff`, or `compatibility_default` provenance. Each lifecycle operation passes
  its action/write class/permission separately to GOV. Watcher, worker, settings, queues, health,
  and receipts propagate the bounded context projection authorized for their EBF/PDM mechanism
  rather than a rival binding-plus-generation model. For migrated one-vault installs with no
  explicit set, the captured
  live bridge binding—or, absent that, the instance default/legacy bootstrap—yields exactly
  one durable compatibility context; no later request/session state participates.
- Before every lifecycle start/rebind, require the MVR-01 shared channel-ownership ledger to show an
  active lease for this exact channel, binding, and canonical-root fingerprint. A missing, pending,
  foreign-channel, or changed lease blocks lifecycle work; runtime state cannot self-claim ownership.
- Subscribe the supervisor to MVR-02's versioned default-mutation event. While intent mode is
  `compatibility`, default set/clear is a producer of the full prepare/quiesce/commit/resume protocol,
  not a commit-before-drain mutation. It derives the candidate using MVR-02 precedence, closes and
  drains mutation ingress, keeps old-root observation buffered through commit, completes the
  post-commit old-root scan/buffer drain, and only then resumes the replacement binding or truthful
  no-vault state. The atomic commit precedes only the idempotent wake-up hint; a delayed/lost hint or
  crash converges from durable phase/revision truth without splitting foreground and background.
  The same event cannot alter an `explicit` intent set. A default mutation may not leave a running
  compatibility lifecycle silently bound to the prior vault or rely on process restart.
- Extend registration removal in the same schema-aware service: compatibility mode atomically clears
  a removed `compatibility_binding_id`; explicit mode retains a now-stale member as loudly failed
  intent until instance-authorized removal, preserving the explicit operator decision. MVR-06 never
  requires MVR-02 to interpret these fields retroactively.
- Before writing the first background role/delegation, background-intent, or compatibility-binding
  field, use the MVR-05 channel fence to atomically advance `minimum_runtime_schema=MVR-06`. A build
  below that floor cannot start watcher/worker/API against the registry; recovery preserves the
  complete lineage and uses an MVR-06-compatible roll-forward/rollback, never a projection that
  discards background intent.
- Reconcile both durable registry revisions and the auth/GOV authorization-decision epoch at
  supervisor startup and continuously while running, with idempotent event hints only accelerating
  reconciliation. For every unseen registry revision or auth epoch, diff
  registration path/device/authority provenance, removal, default, and background intent. Drain,
  re-resolve, and re-authorize every affected lifecycle into a new ActiveContextSet generation
  before accepting later work; removal or failed authorization stops that binding loudly. This
  revision cursor makes a producer crash after the atomic commit but before event publication
  converge without leaving removed or relocated bindings active.
- Before each watcher batch, content read/write, queue dispatch/ack, or emitted outbox mutation,
  acquire the host-global ownership fence and then the binding's cross-process shared effect lease;
  validate the active channel/root lease, current auth epoch/binding revision, and a live GOV decision.
  Release the global fence after the stable snapshot but hold the shared lease through I/O, dispatch,
  acknowledgement, and receipt. Relocation/removal/revocation/transfer takes the ownership fence then
  matching exclusive binding lease and drains shared effects before changing state. A process-local or
  check-then-effect guard is insufficient; immutable producer provenance never authorizes continued work.
- Define start/rebind/drain/stop behavior for zero/one/many bindings, including clean in-flight
  completion and loud partial failure.
- Propagate the complete background `ActiveContextSet` identity, including binding and generation,
  into health, receipts, settings reload, and work queues.
- Make cross-process consumers receive/re-resolve versioned binding state rather than sharing an
  untracked env snapshot.
- Version queued work and outbox rows with an explicit routing class:
  `global` for handlers that touch no content vault, or `vault_bound` with binding/context identity.
  Global rows remain singleton work and require no invented vault. Vault-bound polling/ack ownership
  is binding-scoped. Before enabling more than one lifecycle, a fail-loud upgrade gate validates
  MVR-05's committed classification/key-coalescing receipt and proves that no dispatchable unscoped
  vault-bound row remains. It revalidates already-scoped rows against current intent; any residual
  unknown/ambiguous row remains quarantined for explicit recovery without dispatch or ack. A quarantined unsafe row makes the affected worker
  readiness degraded/blocked but a valid global row never blocks multi-binding startup merely for
  lacking a binding.
- Before multi-worker activation, prove the production PostgreSQL poll/claim/dispatch/ack seam gives
  each row at most one concurrent claim owner through an atomic recoverable database lease/claim, not
  a plain select followed by later acknowledgement. Preserve the current at-least-once contract:
  crash after handler effect but before acknowledgement expires/releases the claim for redelivery,
  and handler/idempotency keys absorb that replay without losing the row or claiming exactly-once
  effects. `global` work remains singleton; `vault_bound` ownership is binding-scoped. Exact-SHA CI
  races concurrent workers and injects crash-after-effect; missing PostgreSQL/claim semantics errors,
  never skips.
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

## Bounded implementation issue decomposition

This specification maps to four serial implementation issues and must never be filed as one child.
Each extracted issue copies a complete canonical Issue contract/SBS block and carries only the
acceptance criteria prefixed with its ID:

1. **MVR-06A — intent and service authority:** durable compatibility/explicit intent schema,
   staged admin service/read surface, explicit-empty semantics, delegated background-runtime role,
   producer migrations/fixtures/preflight, the MVR-06 minimum-runtime floor, and security/governed-
   write plus deployment/release-channel owner-doc updates. All intent-changing admin commands
   remain capability-gated until 06B.
   Depends on MVR-05D.
2. **MVR-06B — compatibility bridge handoff:** atomic #3163 watcher bridge retirement plus drain and
   replacement of the MVR-05 scalar worker with a versioned explicit single-binding handoff, durable picker
   and default-driven compatibility binding, preserved mutation-gate/final-scan/quiesce → commit →
   resume semantics, Settings Spine drain/rebind, and
   activation only of governed singleton/explicit-empty transitions after the supervisor can honor
   them. The first mutation atomically snapshots the effective compatibility singleton before
   applying add/remove, so it cannot silently drop the running binding. Before any singleton
   activation it proves the exact channel/root ownership lease, binding
   revision, and auth epoch; continuously reconciles their durable changes; and holds the shared
   per-binding effect lease through every watcher/worker/settings I/O, dispatch/ack, and receipt.
   Existing GOV-revocation producers take the matching exclusive lease. Only after those background
   leases and the already-merged MVR-05 foreground leases are proven does 06B activate MVR-01B
   registration removal through its recoverable drain/commit/release path. A second enrollment and
   every many-binding transition remain capability-gated through 06C
   and until 06D atomically enables the matching queue-dispatch contract.
   It updates the vault/settings and Settings Spine owners. Depends on 06A and #3163.
3. **MVR-06C — isolated lifecycle supervision:** generalize the already-fenced singleton into a
   zero/one/many-capable per-binding watcher/worker/settings supervisor, prove independent ownership/
   revision/auth reconciliation and truthful gated health, activate the MVR-01B exclusive relocation
   path only after all foreground/background consumers share the lock order, and add cross-process
   ActiveContextSet handoff. An internal capability-gated harness starts two isolated bindings through
   the real supervisor and proves independent reconciliation/health while the production enrollment
   and dispatch gates remain sealed; multi-binding activation remains dormant. Depends on 06B.
4. **MVR-06D — queued-work convergence and aggregate proof:** validate MVR-05 classification, preserve or
   quarantine pending rows under current authority/binding, atomically activate many-binding
   enrollment/start plus its matching dispatch contract, write environment/health truth, and prove
   aggregate zero/one/many behavior. Depends on 06C and closes MVR-06.

Four distinct merged receipts are required on #2143; no child recreates #3163 or #3156.

Partial-delivery gates are explicit: after 06A, durable intent/auth schema exists but the legacy
single-watcher bridge remains authoritative and every add/remove or other intent-changing command
returns `capability_not_ready`; list/inspect is read-only. 06B atomically replaces the bridge with the revision-reconciling single-binding
compatibility supervisor and permits only empty/singleton intent; a second binding is rejected.
The 06B cutover enables intent mutation only after both watcher/settings and the old scalar worker
have drained and the replacement consumes the same durable singleton/empty state under current
ownership/revision/authorization plus the shared effect lease. 06C generalizes that safe singleton and
proves the dormant multi-binding supervisor but keeps second/many-binding
enrollment/start sealed; 06D atomically enables many-binding enrollment/start and its matching queued
dispatch only after the MVR-05 classification receipt and current
binding/authority checks pass. A later stage never becomes observable before its producer,
migration, preflight, and fail-loud gate merge together.

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
- Authority impact: lifecycle creation uses a distinct least-privilege GOV role delegated from the
  local operator role; no authority expansion or supervisor-minted identity
- Persistence impact: durable instance-local background-binding intent and private versioned
  background-role/delegation state, plus global/vault-bound routing, binding/context schema
  migration, and classification for pending queue/outbox rows
- Derived/rebuildable impact: worker/watch instances and health projections are rebuildable
- Human knowledge impact: background writes preserve target vault attribution
- Memory impact: background indexing never mixes vault contexts
- Retrieval/context impact: indexes/queues carry the full ActiveContextSet identity and binding provenance
- Sync/deployment impact: replaces frozen env snapshot with explicit cross-process binding truth
- External boundary impact: env remains bootstrap adapter only
- New or changed contract: per-binding lifecycle supervision through ActiveContextSet and truthful state transitions
- Owner-doc impact: each owning child updates in its PR: 06A security/governed-write plus
  deployment/release-channel floor truth; 06B vault/settings, Settings Spine, environment, and
  health for the safe singleton/empty supervisor; 06C documents dormant multi-binding and safe relocation;
  06D writes the completed zero/one/many runtime-control and health truth, including many-binding activation
- Transition debt impact: reduces D13/D14; residual adapters remain for task 07
- Fitness rule impact: strengthens lifecycle isolation and truthful health

## Constraints

- #3163 must be merged and its single-binding production event path reused.
- Registry membership and request/session activity are not background intent. The durable set is
  deduplicated by `vault_binding_id`; every member is re-authorized after restart and generation
  change.
- Compatibility-uninitialized and explicit-empty are different states. Removing the last explicit
  member survives restart as zero bindings and cannot reactivate the compatibility default.
- A selection-only rebind may let non-mutating in-flight work complete against its captured binding;
  authority revocation/removal requires pre-operation revalidation and blocks/drains stale work.
- One failed binding does not masquerade as healthy or silently redirect to another.
- Never log or expose host paths, secrets, or binding payloads beyond the repository's redaction
  contract in receipts.

## Acceptance Criteria

- [ ] **MVR-06B:** MVR-06 atomically imports the live MVR-05/#3163 compatibility watcher binding, starts the
  revision-reconciling supervisor, and retires the legacy picker bridge; injected failure leaves
  the old bridge authoritative and never enables two or zero watcher owners.
  - Verify: `tests/integration/test_multi_vault_background_lifecycle.py::test_settings_spine_bridge_handoff_is_atomic`
- [ ] **MVR-06B:** The imported live compatibility binding survives restart even when it differs from the
  instance default; a later legacy choose/open picker event or explicit default set/clear changes it
  while compatibility mode remains active, and governed background administration enters explicit mode.
  - Verify: `tests/runtime/test_background_binding_handoff.py::test_compatibility_handoff_binding_survives_restart_without_default_fallback`
- [ ] **MVR-06B:** An existing headless one-vault install with only `VAULT_ROOT` or
  `WATCHER_VAULT_PATH`, no live picker bridge binding, and no explicit instance default migrates that
  already-enrolled MVR-01B legacy bootstrap to exactly one durable compatibility binding; restart
  keeps its watcher active instead of persisting no-vault, and MVR-06 never creates a binding itself.
  - Verify: `tests/runtime/test_background_binding_handoff.py::test_env_only_single_vault_upgrade_preserves_compatibility_watcher`
- [ ] **MVR-06B:** After bridge retirement, a legacy choose/open picker change still atomically updates the
  compatibility binding through the same mutation-gate → old-root pre-commit scan/buffer/quiescent
  ack → commit → old-root post-commit scan/buffer drain → resume transaction and drains/rebinds the
  supervisor; generic scoped selection and every picker
  event after explicit-mode transition leave background intent unchanged.
  - Verify: `tests/integration/test_multi_vault_background_lifecycle.py::test_picker_rebinds_only_compatibility_mode_after_bridge_handoff`
- [ ] **MVR-06B:** After bridge retirement, injected faults at mutation-gate, prepare, old-root final
  scans, quiescent acknowledgement, commit, buffer drain, and resume never strand an accepted
  old-binding write or
  let the supervisor perform a candidate-binding effect before commit. Pre-commit recovery resumes
  the old binding; post-commit recovery rolls forward, including when every wake-up hint is lost.
  - Verify: `tests/integration/test_multi_vault_background_lifecycle.py::test_post_handoff_picker_rebind_preserves_two_phase_failure_atomicity`
- [ ] **MVR-06B:** A direct-filesystem write to A after its pre-commit reconciliation scan but before
  compatibility commit is captured by the durable handoff buffer or post-commit old-root scan and is
  receipted under A before B can load, including when the filesystem event hint is dropped.
  - Verify: `tests/integration/test_multi_vault_background_lifecycle.py::test_handoff_buffers_direct_filesystem_write_through_commit`
- [ ] **MVR-06D:** The production supervisor runs independent watcher/worker lifecycles for two bindings and
  attributes ingest, queues, settings, health, and receipts to the correct immutable
  ActiveContextSet/vault/generation.
  - Verify: `tests/integration/test_multi_vault_background_lifecycle.py::test_two_bindings_run_isolated_lifecycles`
- [ ] **MVR-06B:** Lifecycle start/rebind refuses a binding whose physical root is leased or pending in another
  release channel, including after relocation and restart.
  - Verify: `tests/integration/test_multi_vault_background_lifecycle.py::test_lifecycle_requires_matching_channel_ownership_lease`
- [ ] **MVR-06A:** Existing-install migration, channel/native bootstrap, and fixtures persist one distinct
  least-privilege background runtime role delegated from the local operator role before lifecycle
  startup; missing, stale, ambiguous, or over-broad delegation fails preflight and cannot dispatch.
  - Verify: `tests/integration/test_multi_vault_background_lifecycle.py::test_background_service_role_is_bootstrapped_delegated_and_least_privilege`
- [ ] **MVR-06A:** Request/session selection cannot mutate staged durable background intent; list/inspect
  remains read-only until the 06B supervisor handoff.
  - Verify: `tests/api/test_background_binding_admin.py::test_mvr06a_selection_cannot_mutate_staged_intent`
- [ ] **MVR-06B:** Governed production API and CLI add/remove/list operations are the tested producers of
  singleton or explicit-empty background intent, reject unknown/unauthorized or second bindings,
  atomically commit a durable revision, and publish an idempotent wake-up event for that revision.
  - Verify: `tests/api/test_background_binding_admin.py::test_mvr06b_commands_allow_only_singleton_or_empty_intent`
- [ ] **MVR-06B:** The first governed add/remove while in compatibility mode atomically snapshots the
  effective compatibility singleton (or truthful no-vault empty set) before applying the operation:
  remove-current yields explicit-empty, add-current/remove-nonmember preserves the singleton, and
  add-different is rejected as a gated second enrollment without changing mode or stopping the
  compatibility lifecycle.
  - Verify: `tests/api/test_background_binding_admin.py::test_first_explicit_mutation_snapshots_compatibility_singleton_before_apply`
- [ ] **MVR-06B:** Instance-authorized removal clears stale stored intent idempotently even after its registry
  entry disappears or content authority is lost; add still requires live membership and authority.
  - Verify: `tests/api/test_background_binding_admin.py::test_stale_binding_intent_can_be_removed_without_content_authority`
- [ ] **MVR-06B:** Removing the final explicit member persists explicit-empty intent; restart and list remain
  empty/idle and never re-enrol the instance default.
  - Verify: `tests/runtime/test_background_binding_handoff.py::test_remove_last_then_restart_preserves_explicit_empty_intent`
- [ ] **MVR-06B:** After the handoff, restart reconstructs only the durable, re-authorized
  compatibility/singleton/explicit-empty state; request/session selection cannot alter it.
  - Verify: `tests/runtime/test_background_binding_handoff.py::test_mvr06b_restart_uses_only_durable_authorized_singleton_or_empty_intent`
- [ ] **MVR-06A:** Before the 06B supervisor handoff, production list/inspect may read staged intent
  state but every add/remove or other intent-changing API/CLI command fails capability-not-ready and
  cannot diverge durable intent from the still-authoritative legacy watcher.
  - Verify: `tests/api/test_background_binding_admin.py::test_mvr06a_rejects_all_intent_mutations_until_supervisor_handoff`
- [ ] **MVR-06B:** Replacing or clearing the instance default through MVR-02's production API/CLI uses
  the full prepare/quiesce/commit/resume protocol before later work, but does not rebind explicit
  intent; clearing falls back to a registered legacy bootstrap before truthful no-vault so foreground
  and background resolution remain identical.
  - Verify: `tests/integration/test_multi_vault_background_lifecycle.py::test_default_mutation_rebinds_only_compatibility_lifecycle`
- [ ] **MVR-06B:** Rebind drains in-flight work on the old generation and routes later work to the new one using
  #3163's production event/reload path.
  - Verify: `tests/integration/test_multi_vault_background_lifecycle.py::test_rebind_reuses_settings_spine_and_is_generation_clean`
- [ ] **MVR-06B:** Removing a registered binding or changing authority-relevant provenance rotates
  every affected running lifecycle through drain, re-resolution, and re-authorization; a producer
  crash after registry commit but before event publication still converges from the durable
  revision cursor without accepting later work on the stale binding.
  - Verify: `tests/integration/test_multi_vault_background_lifecycle.py::test_registry_revision_rebinds_and_closes_event_crash_window`
- [ ] **MVR-06B:** Active registration removal becomes available only after every production
  foreground and background consumer participates in the shared/exclusive binding-effect protocol.
  It blocks new acquisition, drains all holders, replaces the live registration with the immutable
  MVR-01B removal tombstone, and only then releases ownership; crash injection at each phase yields
  neither continued legacy access, dual ownership, nor a stranded lease. Later same-channel
  reactivation or cross-channel rehome must preserve predecessor/successor lineage so historical
  receipts/outbox rows remain attributable; ordinary registration cannot silently mint around it.
  - Verify: `tests/integration/test_multi_vault_background_lifecycle.py::test_registration_removal_activates_after_all_consumer_floors`
  - Verify: `tests/integration/test_multi_vault_background_lifecycle.py::test_removed_binding_rehome_preserves_historical_receipt_audit`
- [ ] **MVR-06B:** A pure GOV verdict/role revocation with no registry mutation advances the auth epoch, drains the
  affected lifecycle through the ownership-fence → exclusive binding-lease order. Every background
  operation holds the matching shared lease from final validation through I/O, dispatch/ack, and
  receipt, so a racing revocation either waits for an authorized effect or blocks it before effect.
  - Verify: `tests/integration/test_multi_vault_background_lifecycle.py::test_background_effect_fence_closes_authorization_race_window`
- [ ] **MVR-06C:** After every foreground and background consumer uses the shared-effect lock order,
  the production relocation command activates and takes the ownership fence plus exclusive binding
  lease; it waits for prior authorized effects, commits the new root/revision, and no later effect can
  touch the old root.
  - Verify: `tests/integration/test_multi_vault_background_lifecycle.py::test_relocation_activates_only_after_all_consumer_effect_leases`
- [ ] **MVR-06C:** Once activated, production relocation racing after request resolution or lifecycle
  validation cannot cross any foreground read, governed-write, or background effect window: the
  exclusive relocation waits for an authorized shared effect or advances the locator revision before
  a stale effect can touch either root.
  - Verify: `tests/integration/test_multi_vault_write_effect_fence.py::test_relocation_cannot_cross_foreground_or_background_effect_windows_after_activation`
- [ ] **MVR-06C:** Activated production relocation advances the binding revision so the next
  production request resolves a new ActiveContextSet generation and invalidates affected cache
  entries before data from the old root can be reused.
  - Verify: `tests/integration/test_multi_vault_request_isolation.py::test_binding_revision_rotates_context_and_cache_before_next_request`
- [ ] **MVR-06D:** Zero bindings idle truthfully; one binding preserves current behavior; a failed member is
  loud and cannot redirect or mark the whole set healthy.
  - Verify: `tests/integration/test_multi_vault_background_lifecycle.py::test_zero_one_many_and_partial_failure_are_truthful`
- [ ] **MVR-06C:** The implemented multi-binding supervisor remains dormant: production enrollment/start
  rejects a second binding until 06D atomically enables its matching queue-dispatch contract, while
  an internal capability-gated production-supervisor harness runs two isolated bindings and proves
  independent revision/auth reconciliation, failure containment, context handoff, and health without
  enabling production enrollment or queue dispatch.
  - Verify: `tests/api/test_background_binding_admin.py::test_mvr06c_rejects_many_until_mvr06d_dispatch_gate`
  - Verify: `tests/integration/test_multi_vault_background_lifecycle.py::test_mvr06c_dormant_supervisor_isolates_two_internal_bindings`
- [ ] **MVR-06D:** Governed production enrollment may first persist and start a two-or-more binding explicit
  set only when the matching multi-binding queue-dispatch contract is enabled; restart reconstructs
  exactly that deduplicated, re-authorized set.
  - Verify: `tests/api/test_background_binding_admin.py::test_mvr06d_enrollment_enables_many_with_dispatch`
- [ ] **MVR-06D:** The parent lifecycle-and-dimension acceptance target composes the MVR-04 dimension authority
  contract with isolated zero/one/many watcher and worker behavior before MVR-06 merges.
  - Verify: `tests/integration/test_multi_vault_lifecycle_and_dimension.py::test_parent_dimension_background_acceptance`
- [ ] **MVR-06B:** Before singleton/explicit-empty intent mutation becomes available, the MVR-05 scalar
  worker is drained and replaced atomically with a worker consuming explicit versioned binding state
  resolved to the full background ActiveContextSet. Failure leaves the old worker/bridge authoritative
  and intent mutation sealed; it never leaves duplicate workers or a worker on the prior binding.
  - Verify: `tests/runtime/test_background_binding_handoff.py::test_scalar_worker_handoff_is_atomic_versioned_and_intent_gated`
- [ ] **MVR-06B:** Every production watcher/worker/settings lifecycle receives a full background
  ActiveContextSet with typed `no_workspace` and a server-derived, domain-separated non-reversible
  background capability digest bound to instance, durable intent revision, binding, and generation;
  it carries no bearer selection and cannot use the digest as authority.
  - Verify: `tests/runtime/test_background_binding_handoff.py::test_background_context_has_explicit_workspace_and_capability_identity`
- [ ] **MVR-06D:** MVR-06 validates MVR-05's legacy classification/coalescing receipt before multi-binding start:
  global topics retain one canonical row lineage and at-least-once dispatch, scoped vault-bound rows
  retain one canonical lineage, and unknown/ambiguous rows remain quarantined without dispatch or
  acknowledgement.
  - Verify: `tests/migrations/test_multi_vault_outbox_upgrade.py::test_mvr06_requires_complete_mvr05_classification_receipt`
- [ ] **MVR-06D:** Independent production workers racing the PostgreSQL poll/claim/dispatch/ack path
  acquire at most one concurrent recoverable claim owner for each global or vault-bound row. A crash
  after handler effect but before acknowledgement redelivers under the existing at-least-once and
  idempotency contract without permanent claim/lost work; the test fails rather than skips without
  PostgreSQL or required lease constraints.
  - Verify: `tests/integration/test_multi_vault_outbox_pg_claims.py::test_concurrent_claim_owner_and_crash_redelivery_preserve_at_least_once` +
    successful exact-SHA `integration-nightly / pg-contracts` workflow receipt on #2143
- [ ] **MVR-06A:** The MVR-06 minimum-runtime floor commits before the first background-role,
  delegation, intent, or compatibility field and blocks every older API/watcher/worker before
  registry/auth access; fault injection leaves either untouched MVR-05/MVR-03 state or one complete
  MVR-06-compatible role and intent lineage.
  - Verify: `tests/migrations/test_multi_vault_background_intent_upgrade.py::test_background_role_and_intent_set_mvr06_floor_before_first_write`
- [ ] **MVR-06A:** Deployment and release-channel owner docs record the shipped MVR-06 floor,
  compatible rollback/roll-forward images, recovery path, and operator preflight in the same PR that
  advances the floor.
  - Verify: doc writeback at `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md :: Deployment and Environments` +
    doc writeback at `docs/RELEASE_CHANNELS/README.md :: Release Channels Specification`
- [ ] **MVR-06D:** Pending vault-bound rows are revalidated before dispatch; lifecycle removal, lost authority,
  or incompatible binding/locator change quarantines them durably without dispatch/ack, and governed reissue can
  target only the same re-authorized stable binding with lineage/idempotency preserved.
  - Verify: `tests/integration/test_multi_vault_background_lifecycle.py::test_pending_rows_quarantine_across_removal_and_rebind`
- [ ] **MVR-06D:** A routine supervisor restart or generation rotation preserves valid pending rows for the same
  authorized binding, links fresh consumer context to immutable producer provenance, and does not
  quarantine or retarget them.
  - Verify: `tests/integration/test_multi_vault_background_lifecycle.py::test_pending_rows_survive_compatible_restart_generation`
- [ ] **MVR-06D:** Production watcher/worker/settings callers consume ActiveContextSet outside named bootstrap
  adapters; no parallel lifecycle context type remains.
  - Verify: `tests/architecture/test_multi_vault_context_boundaries.py::test_background_consumers_use_lifecycle_seam`
- [ ] **MVR-06A:** Security and governed-write owner contracts describe the shipped delegated
  background-role producer, least-privilege scope, durable authority state, startup preflight, and
  auth-epoch revocation behavior in the same PR.
  - Verify: doc writeback at `docs/SECURITY.md :: Auth And Rate Limiting` + doc writeback at
    `docs/contracts/GOVERNED_WRITE_PROTOCOL.md :: Invariants`
- [ ] **MVR-06B:** Vault/settings and Settings Spine owner contracts describe the shipped durable
  compatibility intent, two-phase picker/default rebind, bridge retirement, and drain/rebind
  behavior in the same PR. Environment and health owners describe the shipped ownership-checked,
  revision/auth-reconciling, effect-leased singleton/empty supervisor without claiming multi-binding.
  - Verify: doc writeback at `docs/CONCEPTS/VAULT_AND_SETTINGS_CONTEXT.md :: Service Gating` + doc
    writeback at `docs/SETTINGS_SPINE/REBIND_ON_VAULT_SELECTION.md :: What This Task Does` + doc
    writeback at `docs/ENVIRONMENTS.md :: Runtime Control Surface` + doc writeback at
    `docs/HEALTH.md :: Runtime health`
- [ ] **MVR-06C:** The environment owner contract describes the generalized but dormant,
  capability-gated multi-binding supervisor and newly activated safe relocation path, including
  truthful health and cross-process binding state; it does not claim many-binding activation.
  - Verify: doc writeback at `docs/ENVIRONMENTS.md :: Runtime Control Surface` + doc writeback at
    `docs/HEALTH.md :: Runtime health`
- [ ] **MVR-06D:** Environment and health owner contracts describe the completed zero/one/many
  lifecycle posture, including newly activated many-binding controls, only after queued binding
  classification and current authority checks succeed.
  - Verify: doc writeback at `docs/ENVIRONMENTS.md :: Runtime Control Surface` + doc writeback at
    `docs/HEALTH.md :: Runtime health`

## Out of Scope

- Reimplementing #3163, UI, scheduling policy/resource quotas, distributed orchestration, or
  changing ADR-0055 multi-writer semantics.

## How to Verify (Pre-Merge)

Issue extraction copies only the matching child subsection plus the shared gates. The exact-SHA
PostgreSQL receipt belongs only to 06D.

### MVR-06A validation

- `pytest -q tests/integration/test_multi_vault_background_lifecycle.py::test_background_service_role_is_bootstrapped_delegated_and_least_privilege tests/api/test_background_binding_admin.py::test_mvr06a_selection_cannot_mutate_staged_intent tests/api/test_background_binding_admin.py::test_mvr06a_rejects_all_intent_mutations_until_supervisor_handoff tests/migrations/test_multi_vault_background_intent_upgrade.py::test_background_role_and_intent_set_mvr06_floor_before_first_write`
- Verify the 06A PR diff contains its mapped deployment, release, security, and governed-write
  owner-doc targets.

### MVR-06B validation

- `RUN_INTEGRATED_RUNTIME_UAT=1 pytest -q tests/integration/test_multi_vault_background_lifecycle.py::test_settings_spine_bridge_handoff_is_atomic tests/integration/test_multi_vault_background_lifecycle.py::test_picker_rebinds_only_compatibility_mode_after_bridge_handoff tests/integration/test_multi_vault_background_lifecycle.py::test_post_handoff_picker_rebind_preserves_two_phase_failure_atomicity tests/integration/test_multi_vault_background_lifecycle.py::test_default_mutation_rebinds_only_compatibility_lifecycle tests/integration/test_multi_vault_background_lifecycle.py::test_rebind_reuses_settings_spine_and_is_generation_clean tests/integration/test_multi_vault_background_lifecycle.py::test_lifecycle_requires_matching_channel_ownership_lease tests/integration/test_multi_vault_background_lifecycle.py::test_registry_revision_rebinds_and_closes_event_crash_window tests/integration/test_multi_vault_background_lifecycle.py::test_registration_removal_activates_after_all_consumer_floors tests/integration/test_multi_vault_background_lifecycle.py::test_removed_binding_rehome_preserves_historical_receipt_audit tests/integration/test_multi_vault_background_lifecycle.py::test_background_effect_fence_closes_authorization_race_window tests/runtime/test_background_binding_handoff.py::test_compatibility_handoff_binding_survives_restart_without_default_fallback tests/runtime/test_background_binding_handoff.py::test_env_only_single_vault_upgrade_preserves_compatibility_watcher tests/runtime/test_background_binding_handoff.py::test_remove_last_then_restart_preserves_explicit_empty_intent tests/runtime/test_background_binding_handoff.py::test_mvr06b_restart_uses_only_durable_authorized_singleton_or_empty_intent tests/runtime/test_background_binding_handoff.py::test_scalar_worker_handoff_is_atomic_versioned_and_intent_gated tests/runtime/test_background_binding_handoff.py::test_background_context_has_explicit_workspace_and_capability_identity tests/api/test_background_binding_admin.py::test_mvr06b_commands_allow_only_singleton_or_empty_intent tests/api/test_background_binding_admin.py::test_first_explicit_mutation_snapshots_compatibility_singleton_before_apply tests/api/test_background_binding_admin.py::test_stale_binding_intent_can_be_removed_without_content_authority`
- `RUN_INTEGRATED_RUNTIME_UAT=1 pytest -q tests/integration/test_multi_vault_background_lifecycle.py::test_handoff_buffers_direct_filesystem_write_through_commit`
- Verify the 06B PR diff contains its mapped vault/settings, Settings Spine, environment, and health
  owner-doc targets.

### MVR-06C validation

- `RUN_INTEGRATED_RUNTIME_UAT=1 pytest -q tests/integration/test_multi_vault_background_lifecycle.py::test_relocation_activates_only_after_all_consumer_effect_leases tests/integration/test_multi_vault_write_effect_fence.py::test_relocation_cannot_cross_foreground_or_background_effect_windows_after_activation tests/integration/test_multi_vault_request_isolation.py::test_binding_revision_rotates_context_and_cache_before_next_request tests/api/test_background_binding_admin.py::test_mvr06c_rejects_many_until_mvr06d_dispatch_gate tests/integration/test_multi_vault_background_lifecycle.py::test_mvr06c_dormant_supervisor_isolates_two_internal_bindings`
- Verify the 06C PR diff contains its mapped `docs/ENVIRONMENTS.md` and `docs/HEALTH.md` dormant-
  supervisor writebacks.

### MVR-06D validation

- `RUN_INTEGRATED_RUNTIME_UAT=1 pytest -q tests/integration/test_multi_vault_background_lifecycle.py::test_two_bindings_run_isolated_lifecycles tests/integration/test_multi_vault_background_lifecycle.py::test_zero_one_many_and_partial_failure_are_truthful tests/api/test_background_binding_admin.py::test_mvr06d_enrollment_enables_many_with_dispatch tests/integration/test_multi_vault_lifecycle_and_dimension.py::test_parent_dimension_background_acceptance tests/migrations/test_multi_vault_outbox_upgrade.py::test_mvr06_requires_complete_mvr05_classification_receipt tests/integration/test_multi_vault_background_lifecycle.py::test_pending_rows_quarantine_across_removal_and_rebind tests/integration/test_multi_vault_background_lifecycle.py::test_pending_rows_survive_compatible_restart_generation tests/architecture/test_multi_vault_context_boundaries.py::test_background_consumers_use_lifecycle_seam`
- Dispatch exact-head `integration-nightly / pg-contracts` for
  `tests/integration/test_multi_vault_outbox_pg_claims.py::test_concurrent_claim_owner_and_crash_redelivery_preserve_at_least_once`;
  missing PostgreSQL or claim constraints is an error, never a skip, and the successful URL/SHA is
  attached to #2143.
- Verify the 06D PR diff contains its mapped activated `docs/ENVIRONMENTS.md` and `docs/HEALTH.md`
  writebacks.

Every child also runs `mypy app`, `pytest -q -m "not pg"`, `ruff check app tests`, and
`python3 scripts/docs_guard.py` as shared repo gates; those gates do not substitute for its exact
mapped selectors above.

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

Create the four serial children in `Bounded implementation issue decomposition` under #2143 only
after their named dependencies merge. Use Sol/xhigh for authority, watcher concurrency,
cross-process binding, queue migration, and settings reload; bounded mechanical adapters may use
Terra/high only after the governing contract is frozen. Do not recreate #3163 or its Settings Spine
parent #3156.
