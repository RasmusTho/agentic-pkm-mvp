State: Proposed target state (wanted-state architecture for v6.0; not current runtime truth).
# SoT v6.0 Architecture Target

## Purpose

This document describes the wanted-state architecture for a future `v6.0` line.

It exists so the repo can:
- review the current architecture critically,
- define larger architectural changes without pretending they already exist,
- and separate current-state truth from desired-state direction.

This document is not authoritative for the current runtime.
For current-state questions, `docs/ARCHITECTURE.md` still wins.
`docs/STATUS.md` remains the current operational baseline posture.

This document should be read together with:
- `docs/ARCHITECTURE.md` for current runtime truth,
- `docs/DESIGN_PRINCIPLES.md` for stable design rules,
- `docs/ROADMAP.md` for sequencing,
- `docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md` for capability and bounded-agent evolution.

## Why this document must be baseline-aware

The current repo does not lack architecture.
It already has a concrete runtime shape:
- the Obsidian vault is the canonical human writing and reading surface,
- the current runtime boundary includes watcher, ingest, panel, ASK, promotion, worker, and store-facing code,
- Postgres/pgvector provides canonical store persistence and DB outbox,
- registry watcher is the runtime default,
- the DB outbox is the canonical queue for runtime side effects,
- vault note + companion note are the portable file-based continuity set,
- runtime DB/index state is rebuildable from that set.

That means `v6.0` should not be read as a greenfield replacement.
It should be read as a controlled re-architecture of an existing vault-first, outbox-driven, local runtime.

The practical question for `v6.0` is therefore not "what components should exist?"
It is "where should semantic authority live, and which current seams must stop carrying more meaning than they should?"

## Usage rule

Architecture review findings must be classified into exactly one of these buckets.

### 1. Current-state mismatch or bug

Meaning:
- the current runtime or current architecture doc violates an already accepted contract.

Action:
- fix in current runtime or current docs,
- keep the fix in the `v5.x` line if it is small enough and low-risk enough.

### 2. Enabling change

Meaning:
- a small or medium change that does not itself realize the full target state,
- but reduces coupling or prepares the path toward it.

Action:
- may land in `v5.x`,
- but should be described as enablement, not as target state achieved.

### 3. v6.0 target-state change

Meaning:
- a larger architectural move that changes the intended shape of the runtime,
- depends on broader semantic alignment,
- or would be misleading to present as current-state architecture today.

Action:
- describe it here first,
- then sequence implementation under explicit rollout steps.

## Baseline inherited from v5.5

`v6.0` inherits the following baseline assumptions from the active current-state architecture.

### What stays true

- The vault remains the canonical human writing and reading surface.
- The current runtime remains vault-first rather than DB-first.
- Postgres/pgvector and the DB outbox remain core runtime infrastructure.
- Registry watcher remains the default runtime ingress until replaced by an explicitly adopted successor.
- Companion note + vault note remain the portable continuity set.
- Runtime DB/index state remains rebuildable and therefore secondary rather than semantically primary.
- Local-first multi-device operation remains a first-class concern.
- Bounded observability, receipts, explainability, and idempotency remain architecture-level requirements.

### What v6.0 changes

`v6.0` is meant to change the *authority model* of the runtime more than the mere component list.

The intended deltas are:

- from watcher-near execution coupling to explicit execution contracts,
- from path/flat-scope/metadata seams carrying meaning to layered context and bounded operational scope,
- from projection-heavy semantics to artifact- and contract-aware semantics,
- from interaction surfaces that remain too close to mutation authority to clearer interaction/cognition/execution/governance separation,
- from loosely named surfaces to explicit surface authority rules,
- from conservative-but-flat retrieval to conservative relation/provenance-aware retrieval.

## Preconditions for v6.0

The following items are not themselves "the v6 architecture".
They are prerequisites or blocker-clearing corrections that should be treated as `v5.x` work unless sequencing forces otherwise.

### Current-state bug fixes that should not be deferred behind v6 branding

- `domain` must not be inferred from path when payload metadata is absent.
- `zone` must not be read as if it were a stored artifact field.
- `domain` must be validated or conservatively marked `unscoped` at the write boundary.
- missing boundary metadata must become explainable at ingest/store time rather than silently tolerated.

### Enabling changes that should prepare the path

- split mirror/projection concerns from receipt/audit concerns,
- introduce explicit promotion transition records rather than state mutation alone,
- keep machine-owned artifacts in clear write zones,
- reduce accidental semantic dependence on path family or legacy metadata labels.

`v6.0` should assume these are either already fixed, explicitly gated, or deliberately carried as temporary compatibility seams.

## Core architectural intention for v6.0

The `v6.0` target state is a baseline-aware operating model with four central moves:

1. **files remain the human canonical layer**
2. **contracts/events become the execution canonical layer**
3. **runtime stores remain derived and rebuildable**
4. **replication stays transport, not semantic authority**

Stated more operationally:

- primary human artifacts remain the meaning-bearing center,
- observation of a file change is not enough to authorize side effects,
- only explicit, versioned, replay-safe contracts may authorize execution,
- interaction surfaces may propose or declare intent but do not own execution authority,
- runtime projections, mirrors, indexes, and overlays support the system but do not silently become the semantic center.

## Target operating model

The intended operating model for `v6.0` should be read through six layers.

### A. Human canonical layer

This layer contains:
- vault notes,
- frontmatter and human-authored structure,
- human-editable continuity artifacts where explicitly intended.

Authority:
- human meaning,
- human reviewability,
- human diffability,
- human ownership of what was written.

Non-goal:
- direct execution authority merely because a file became visible to runtime.

### B. Replication layer

This layer contains:
- iCloud and equivalent authoring replication channels,
- Git-based promotion/export/recovery channels,
- replica-local transport and convergence behavior.

Authority:
- transport,
- replication,
- delayed availability,
- provenance of where an observation arrived from.

Non-goal:
- defining when the runtime is authorized to act.

### C. Observation layer

This layer contains:
- watcher signals,
- changed-file candidates,
- ingress observations,
- bounded runtime sensing of possibly changed material.

Authority:
- "something may have changed".

Non-goals:
- deciding full business meaning,
- deciding execution readiness,
- deciding that a single file event equals a complete human action.

### D. Normalization and contract layer

This is the critical new boundary in `v6.0`.

This layer contains:
- stable snapshot formation,
- identity reconciliation,
- schema/policy validation,
- context reconciliation,
- contract emission,
- dedupe/idempotency keys,
- causation/correlation data,
- policy verdicts,
- execution admission decisions.

Authority:
- deciding when observed change becomes a valid runtime contract.

This is where raw observations become:
- `NoteChangeObserved`,
- `NoteSnapshotNormalized`,
- `AutomationIntentDeclared`,
- `ExecutionRequestAdmitted`,
- `ExecutionApplied`,
or equivalent versioned contract families.

### E. Execution layer

This layer contains:
- side-effect-capable runtime actions,
- workers/executors,
- retries,
- concurrency checks,
- policy enforcement,
- execution receipts and traces.

Authority:
- carrying out only already-admitted execution requests.

Non-goal:
- reading watcher or path events as implicit permission to act.

### F. Derived machine layer

This layer contains:
- DB objects,
- vector index entries,
- relation/index projections,
- mirrors,
- ranking overlays,
- salience/zone-like derived aids,
- runtime summaries and other support structures.

Authority:
- operational support,
- retrieval support,
- ranking/orientation/resurfacing support,
- continuity and rebuild assistance.

Non-goal:
- replacing primary human artifacts or execution contracts as the real source of meaning.

## Execution boundary for v6.0

The most important architectural change in `v6.0` is an explicit execution boundary.

### Current baseline problem statement

The current runtime already improved beyond a naive "watcher directly executes" model.
However, too much semantic weight can still leak through these seams:

- watcher ingress,
- path/layout,
- flat `domain`,
- interaction-surface-near mutation flow,
- projection metadata that is convenient to read as authority.

### v6.0 execution rule

No side effect is authorized merely because:
- a file changed,
- a watcher saw the change,
- a panel parsed successfully,
- a projection row exists,
- a path implies a likely scope,
- or a replica delivered a file.

A side effect becomes eligible only when a versioned execution contract has passed normalization and admission.

### Admission gate

Between normalization and execution there should be an explicit admission gate.

The gate should be able to decide:
- whether the artifact is in an execution-relevant class,
- whether the snapshot is stable enough,
- whether the operational scope is valid,
- whether required provenance is present,
- whether policy allows execution,
- whether the request is duplicate/replay/stale,
- whether optimistic concurrency still holds,
- whether execution is direct, proposal-only, or blocked.

## Capability graph, not agent sprawl

`v6.0` should be written and implemented as a capability-centered architecture.

### Architectural roles

#### 1. Capabilities

Reusable functions such as:
- retrieval,
- reranking,
- orientation support,
- resurfacing support,
- reasoning support,
- mutation planning,
- promotion assessment,
- receipt writing,
- relation lookup,
- context assembly,
- contract normalization.

#### 2. Orchestrators / bounded agents

Decision-making components that:
- choose among capabilities,
- sequence bounded work,
- remain subject to governance and authority limits,
- do not become catch-all identities for every function.

#### 3. Pipelines

Deterministic or semi-deterministic flows that:
- transform one bounded input into one bounded output,
- remain preferable where they are safer and clearer than richer agent behavior.

#### 4. Execution substrate

The runtime machinery that:
- carries contracts/events,
- sequences work,
- invokes execution,
- records receipts and traces,
- maintains derived stores.

This distinction matters because the current repo already has a real substrate.
`v6.0` should refine authority placement on top of it, not describe every useful function as a new architectural agent.

## Surface authority matrix

The target architecture should preserve explicit authority boundaries across persistence and support surfaces.

### 1. Writing surface

Examples:
- vault notes,
- human-authored editable artifacts.

Authority:
- canonical human authorship,
- human review and revision,
- primary human-readable meaning.

### 2. Retention surface

Examples:
- retained external material,
- source-rich captured artifacts,
- archive/reference material kept for later retrieval and citation.

Authority:
- durable retained material and provenance.

Non-goal:
- implicit execution authority.

### 3. System surface

Examples:
- companion notes,
- receipts,
- mirrors,
- continuity/repair artifacts,
- bounded support artifacts.

Authority:
- continuity, explainability, portability support, accountability support.

Non-goal:
- silently becoming the only real semantic center.

### 4. Runtime surface

Examples:
- DB rows,
- chunks,
- embeddings,
- relation tables,
- execution queues,
- ephemeral operational projections.

Authority:
- local runtime support and rebuildable machine state.

Non-goal:
- human truth.

### 5. Execution records

Examples:
- admitted execution contracts,
- execution receipts,
- traces,
- audit rows,
- retry/replay evidence.

Authority:
- what the runtime was authorized to do,
- what it attempted,
- what it completed,
- why it did or did not proceed.

Non-goal:
- replacing human-authored artifacts as the full meaning model.

## Context model target

### Layered context, not one-field context

`v6.0` should stop pretending that one `domain` field fully represents human context.

The target model should separate at least:

- operational scope,
- broader sphere/context belonging,
- situated role or participation identity,
- explicit cross-scope allowance where bounded authorization is truly needed,
- provenance of where and how an artifact became visible to runtime.

`domain` may survive as a compatibility field only insofar as it means `operational_scope`.
It should not remain the whole context model.

### Relation-first overlap

When an artifact matters in more than one area of life or work, the primary interpretation should be shared participation or relation-bearing context.
Permission-like crossing remains important, but as bounded authorization, not as the main ontology of overlap.

## Retrieval migration path

`v6.0` should not replace conservative retrieval with uncontrolled semantic richness.
It should stage retrieval evolution carefully.

### Stage A — conservative baseline preserved

- operational scope remains the default boundary,
- retrieval continues to be conservative by default,
- missing context should fail closed rather than become permissive.

### Stage B — relations and provenance become additive signals

- explicit relations,
- retained-material provenance,
- broader belonging metadata,
- continuity artifacts,
can extend retrieval and ranking without replacing bounded operational scope.

### Stage C — retrieval/orientation/resurfacing are made explicit

The architecture should distinguish:
- retrieval: find and return bounded results,
- orientation: help the human regain situational understanding,
- resurfacing: bring things back into attention.

These are related but not identical capabilities.

### Stage D — operational scope remains narrow even when context grows richer

The richer context model should not erase the need for bounded runtime scope.
Instead it should prevent a narrow scope marker from pretending to be the whole human model.

## Multi-device and replication posture

`v6.0` must treat local-first multi-device operation as a normal runtime condition.

### Default posture

- multi-device authoring is normal,
- devices may have heterogeneous roles,
- replicas may be partial,
- sync may lag,
- convergence may be delayed,
- derived layers may be incomplete on a given node.

### Architectural rule

Replication does not define execution semantics.

That means:
- replica visibility does not equal execution authority,
- delayed arrival does not corrupt artifact identity,
- instance provenance remains distinct from artifact identity,
- duplicate observation and replay are expected realities rather than exceptions.

### Recommended default runtime posture

Unless a later architecture decision explicitly changes it, `v6.0` should continue to assume a single execution authority posture even in a multi-device authoring world.

This means:
- one runtime authority may admit and execute side effects,
- many devices may author, review, or query,
- replication remains asynchronous,
- execution contracts and receipts must tolerate lag, duplicate observation, and replay.

## Watcher posture in v6.0

Watchers should remain necessary but semantically narrower.

### Watcher responsibilities

- detect possible change,
- stabilize enough to form a candidate,
- emit observation data,
- preserve provenance,
- remain observable.

### Watcher non-responsibilities

- deciding complete human intent,
- deciding cross-scope meaning,
- deciding that an execution should happen,
- directly carrying business semantics that belong in normalization or governance.

The architecture should therefore treat watcher as sensor/ingress infrastructure, not the place where runtime meaning hardens.

## Interaction, cognition, governance, execution

The target architecture should separate these concerns more explicitly than the current baseline.

### Interaction

Examples:
- Panel,
- Chat,
- other future human-facing control surfaces.

Authority:
- gather human input,
- present proposals and results,
- request action,
- declare or surface intent.

### Cognition

Examples:
- reasoning,
- interpretation,
- summarization,
- context assembly,
- planning support.

Authority:
- produce bounded cognitive outputs,
- support human understanding or downstream contract formation.

### Governance

Examples:
- policy checks,
- allowlists,
- write/mutation authority,
- confidence/risk checks,
- execution admission,
- approval gates.

Authority:
- decide what may proceed.

### Execution

Examples:
- writes,
- promotions,
- external side effects,
- workflow transitions,
- other mutation-bearing acts.

Authority:
- carry out what governance has admitted.

The design point is simple:
interaction may surface or declare intent;
cognition may interpret;
governance decides;
execution acts.

## Commitments remain distinct

`v6.0` should preserve commitments as a distinct semantic family.

This means:
- projects,
- open loops,
- next actions,
- waiting states,
- execution accountability,
must not collapse into generic note lifecycle labels or generic execution-plan language.

This remains a target-state direction.
It does not require pretending that the full commitment runtime already exists in current runtime truth.

## Rollout model

`v6.0` should be sequenced as a migration, not as a one-shot rewrite.

### Phase 0 — blocker clearing in v5.x

- current-state bugs around domain/zone/boundary validation fixed,
- mirror/receipt split prepared,
- promotion transition receipt added,
- watcher/path semantic leakage reduced where possible.

### Phase 1 — explicit contracts and admission boundary

- introduce versioned normalization/execution contracts,
- make execution admission explicit,
- route mutation-capable flows through the contract boundary,
- preserve current substrate where possible.

### Phase 2 — surface authority hardening

- formalize writing/retention/system/runtime/execution-record authority rules,
- keep companion/receipt/mirror semantics distinct,
- reduce store/projection semantic drift.

### Phase 3 — retrieval broadening under conservative control

- additive relation/provenance-aware retrieval,
- explicit orientation/resurfacing distinction,
- operational scope stays bounded.

### Phase 4 — richer context and bounded capability graph

- operational scope separated from broader context model,
- capability graph clarified,
- bounded orchestrators introduced where useful,
- interaction/cognition/governance/execution seams become explicit in runtime.

## Exit condition

This target-state document becomes actionable when:
- the baseline it inherits is kept explicit,
- current-state bugs and enabling changes are not mislabeled as v6 accomplishments,
- execution boundary changes are specified in runtime-contract terms rather than only semantic aspirations,
- rollout work can be sequenced without corrupting `docs/ARCHITECTURE.md` as the current-state SoT.

## Architecture review findings (2026-03-25)

This section records the first pass of concrete runtime findings classified against accepted concept contracts.

### Current-state bugs (fix in v5.x)

**Finding 1: Domain inferred from path as fallback**
- Location: `app/retrieval/hybrid.py` lines 135-145, `_extract_domain()`
- Problem: moving a note between folders can silently change its runtime domain.
- Fix direction: remove path-based inference; treat missing domain as `unscoped`.

**Finding 2: Zone read from artifact payload as if stored**
- Location: `app/agents/ask/graph.py:22`, `app/agents/ask/utils.py:38,70`, `app/api/routes/ask.py:91-92`
- Problem: `zone` is treated as stored artifact data even though it is a derived overlay.
- Fix direction: compute dynamically at retrieval time from bounded signals.

**Finding 3: Domain not validated or recorded at write boundary**
- Location: `app/ingest/vault_alpha.py:501-544`, `app/store/object_store.py`, `app/retrieval/hybrid.py:158-164`
- Problem: missing boundary metadata is neither rejected nor explicitly explained.
- Fix direction: validate at write boundary; conservatively mark missing metadata; emit assignment/audit evidence.

### Enabling changes (may land in v5.x)

**Finding 4: Mirror conflates artifact identity with audit log**
- Location: `app/ingest/vault_alpha.py:331-363`, `app/services/note_log.py:6-19`
- Enablement direction: separate minimal projection from receipt/audit records and keep mirror paths in ignore/protection lists.

**Finding 5: Promotion mutates artifact state without a clear transition record**
- Location: `app/promotion/consumer.py:66-91`, `app/services/note_update.py:36-88`
- Enablement direction: emit explicit promotion transition records and human-legible receipts in addition to state mutation.

### v6.0 target-state changes

**Finding 6: Single `domain` field represents too much of human context**
- Target direction: layered context model where `domain` survives, if at all, only as `operational_scope`.

**Finding 7: `kind` is hardcoded too narrowly**
- Target direction: kind/policy routing becomes more explicit at ingest and normalization boundaries without collapsing into schema sprawl.

## Related documents

- `docs/ARCHITECTURE.md`
- `docs/STATUS.md`
- `docs/ROADMAP.md`
- `docs/DESIGN_PRINCIPLES.md`
- `docs/HUMAN-FLOWS.md`
- `docs/RETRIEVAL.md`
- `docs/PANEL_AGENT.md`
- `docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md`
- `docs/plans/ARTIFACT_MODEL_AND_LIFECYCLES.md`
- `docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md`
- `docs/CONCEPTS/MIRROR_RECEIPT_DECISION.md`
- `docs/CONCEPTS/INSTANCE_DEVICE_AND_REPLICA_CONTRACT.md`
- `docs/CONCEPTS/CONTEXT_REPRESENTATION_POSTURE.md`
- `docs/CONCEPTS/CONTEXT_TERMINOLOGY_CONTRACT.md`
