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

This document should be read as a target-state consolidation of semantic directions that already
exist elsewhere in the repo.
It is not a license to rewrite the current runtime as if the target were already implemented.

## Why a separate target-state doc is needed

The current repo is in a transitional position:
- the human-function and ontology layers are now sharper,
- the current runtime still carries older flattened assumptions,
- and some meaningful architecture changes would be too large to describe as if they were merely
  small v5.x refactors.

If we mix those layers carelessly, two bad things happen:
- `docs/ARCHITECTURE.md` stops being trustworthy as current-state SoT,
- or the desired architecture never gets a clear home because it always looks "too future" for
  current docs.

`v6.0` is therefore the right place for architecture changes that are:
- semantically meaningful,
- structurally non-trivial,
- and not yet reflected in the actual baseline.

## Usage rule

Architecture review findings should be classified into exactly one of these buckets:

### 1. Current-state mismatch or bug

Meaning:
- the current runtime or architecture doc violates an already accepted contract.

Action:
- fix in current runtime or current docs,
- and keep the fix in the v5.x line if it is small enough and low-risk enough.

### 2. Enabling change

Meaning:
- a small or medium change that does not itself realize the full target state,
- but reduces coupling or prepares the path toward it.

Action:
- may land in v5.x,
- but should be described as enablement, not as target state achieved.

### 3. v6.0 target-state change

Meaning:
- a larger architecture move that changes the intended shape of the runtime,
- depends on broader semantic alignment,
- or would be misleading to present as current-state architecture today.

Action:
- describe it here first,
- then sequence implementation under explicit rollout steps.

## Core architectural intention for v6.0

The `v6.0` wanted state should move the runtime toward a cleaner match with the human-first model
that now exists in the concept documents.

The high-level direction is:
- richer human semantics above runtime storage boundaries,
- narrower operational scope in runtime,
- relation-first handling of overlap,
- cleaner distinction between primary human artifacts and projections,
- explicit separation between writing, retention, and system surfaces,
- clearer treatment of commitments as their own semantic family,
- clearer separation between retrieval, orientation, and resurfacing,
- and less accidental meaning carried by path, one-field scope, or old runtime terminology.

## Wanted-state pillars

### 1. Context model is layered in runtime, not flattened into one `domain` field

Wanted state:
- runtime treats `operational scope` as the narrow working boundary,
- while broader belonging and overlap can be represented through relations rather than being forced
  into one exclusive classification.

Implication:
- architecture should stop assuming that one scope field fully explains human context.

### 2. Overlap is represented as relation-first, not permission-first

Wanted state:
- shared participation is treated as the primary semantic reality,
- explicit cross-scope allowances are only used when repeated runtime crossing needs bounded
  authorization.

Implication:
- retrieval, path, and event design should not make `bridge`-like permission objects carry all
  overlap semantics.

### 3. Primary human artifacts remain central; projections stay secondary

Wanted state:
- runtime keeps primary human artifacts clearly distinct from mirrors, receipts, execution artifacts,
  indexes, and other projections,
- and architecture surfaces preserve that difference explicitly.

Implication:
- machine-side structures may assist, but they should not become the hidden center of meaning.

### 4. Persistence surfaces stay explicit rather than collapsing into one vague storage model

Wanted state:
- the architecture names and preserves three persistence surfaces:
  - a writing surface for human-authored editable artifacts,
  - a retention surface for retained source-rich artifacts kept for retrieval, citation, and later
    reuse,
  - and a system surface for mirrors, indexes, traces, receipts, execution artifacts, and runtime
    support structures,
- these surfaces may interact, but they should not be treated as one undifferentiated
  `notes/storage` layer.

Implication:
- future runtime design should make it easier to see which surface is carrying human-authored
  meaning, which surface is carrying retained material, and which surface exists for execution or
  accountability support.
- the system surface must not silently become the only real source of meaning simply because it is
  structurally convenient.

### 5. Commitments remain a distinct semantic family rather than generic note state

Wanted state:
- commitments are modeled as a distinct concern within the architecture,
- open loops, projects, next actions, waiting states, and execution accountability remain legible
  as commitment-oriented structures,
- and they are not flattened into generic artifact lifecycle labels, generic note state, or runtime
  execution-plan language.

Implication:
- future runtime design should distinguish commitments from:
  - artifacts and retained material,
  - execution plans and orchestration artifacts,
  - generic review or lifecycle labels used for notes or projections.
- this is a target-state semantic direction, not a claim that a full commitment runtime already
  exists.

### 6. Retrieval should combine scope, relations, and provenance rather than overloading one boundary

Wanted state:
- retrieval defaults remain conservative,
- but can draw on explicit relations, provenance, retained artifacts, and overlap structures
  without pretending the path tree or one domain field is the full truth.

Implication:
- retrieval architecture should be reviewed for places where it is too flat, too scope-only, or too
  path-derived.

### 7. Retrieval, orientation, and resurfacing stay related but distinct

Wanted state:
- retrieval, orientation, and resurfacing are treated as related but separate capabilities,
- retrieval is not treated as the whole solution to human re-orientation,
- resurfacing is not reduced to ranking or query-answer relevance,
- and salience may influence runtime behavior without becoming hidden semantic authority.

Implication:
- future architecture should expose these distinctions clearly enough that:
  - findability does not masquerade as orientation,
  - resurfacing does not masquerade as retrieval,
  - and derived overlays such as `zone` remain bounded runtime aids rather than the ontology of what
    matters.

### 8. Filesystem and path stay projections, not master ontology

Wanted state:
- one primary stored location remains compatible with richer context relations,
- and path/layout choices remain pragmatically useful without deciding too much of the domain model.

Implication:
- architecture should not force path family, vault root, or folder placement to become the main
  semantic engine.

### 9. Accountability and explainability remain architecture-level invariants

Wanted state:
- cross-scope allowances, retrieval context, agent actions, and durable changes remain inspectable
  and receipt-bearing.

Implication:
- richer semantics must not come at the cost of legibility or trust.

### 10. Surface, authority, and accountability distinctions stay explicit

Wanted state:
- the architecture keeps the distinctions between:
  - human-facing artifacts,
  - retained artifacts,
  - mirror artifacts,
  - receipt artifacts,
  - and execution/runtime traces,
  explicit enough that adjacent surfaces do not collapse into each other.

Implication:
- mirror artifacts should continue to mean projection/portability support rather than generic action
  history,
- receipt artifacts should continue to mean accountability surfaces rather than generic logs,
- and traces, audit rows, or event streams should remain supporting execution records rather than
  being treated as the full human-legible accountability model.

### 11. Local-first multi-device operation is designed as an architecture property, not an afterthought

Wanted state:
- architecture tolerates heterogeneous device roles,
- eventual consistency across devices and replicas rather than assuming one always-current global
  runtime view,
- eventual sync,
- partial replicas,
- and rebuildable derived layers.

Implication:
- central artifacts must stay durable and understandable even when relation layers or derived views
  are incomplete on a given device.
- sync, ingestion, and derived-state rebuild flows should be safe under lag, partial visibility, and
  delayed convergence rather than requiring strict immediate consistency.
- instance provenance and replica state should remain distinguishable from artifact identity.

### 12. Creative-process support is preserved as a first-class architecture concern

Wanted state:
- runtime surfaces can preserve fragments, alternatives, revision, world continuity, and selective
  stabilization without forcing everything into settled knowledge or task structures,
- and hobby/RPG use remains a legitimate validating case rather than an afterthought.

Implication:
- future retrieval, writing, mirror, and support surfaces should not erase exploratory ambiguity or
  partial canon-like stabilization merely because those are harder to model.

## Likely v6.0 architecture themes

These are not yet commitments, but they are the most plausible themes the review should test
against the current runtime:

- a more explicit separation between artifact identity, context relations, and runtime scope
- cleaner runtime handling of shared participation vs cross-scope allowance
- clearer architectural treatment of writing, retention, and system persistence surfaces
- commitment-first modeling that does not collapse projects, open loops, waiting states, and next
  actions into generic note lifecycle labels
- retrieval that can reason over relation-bearing context instead of a single flattened scope model
- explicit separation between retrieval, orientation, and resurfacing, with salience kept derived
  and inspectable
- a reduced tendency for watcher/path/layout assumptions to act as domain truth
- clearer seams between human-facing artifacts, mirror surfaces, receipt surfaces, and execution
  surfaces
- architecture that treats local-first multi-device use and eventual consistency as part of normal
  operation rather than a later bolt-on
- architecture that preserves creative-process semantics rather than flattening them into knowledge
  maturity or commitments

## Architectural delta from v5.5 to v6.0

This section summarizes the most important intended architectural shift from the current `v5.5`
baseline to the wanted `v6.0` line.

It does not mean every delta must land in one release-sized rewrite.
It exists so review, planning, and implementation can distinguish:
- what the current runtime still does,
- what direction the concept work now implies,
- and which changes are merely enabling steps versus true target-state moves.

### 1. From flattened context to layered context

Current tendency:
- runtime still carries significant meaning through one active scope field, path placement, and
  related filtering assumptions,
- and older terminology still encourages reading those boundaries as if they were the whole context
  model.

Wanted delta:
- runtime keeps `operational scope` as a narrow working boundary,
- while broader human meaning is carried through `sphere`, `context`, `situated role identity`, and
  `shared participation`,
- without assuming one runtime boundary fully explains human belonging.

Architectural consequence:
- context must be modeled in layers rather than collapsed into one field or one folder location.

### 2. From permission-first overlap to relation-first overlap

Current tendency:
- cross-context reuse is easy to read through bridge-like or allowance-like mechanics,
- especially where runtime needs explicit bounded crossing.

Wanted delta:
- overlap is first understood as shared participation in more than one sphere or context,
- while explicit cross-scope allowance is a narrower authorization mechanism for repeated runtime
  crossing.

Architectural consequence:
- relation-bearing context should become more primary than permission objects in retrieval,
  indexing, and future schema design.

### 3. From projection-centric runtime semantics to artifact-centric semantics

Current tendency:
- store projections, frontmatter projections, mirrors, indexes, and runtime overlays carry a large
  share of effective meaning in day-to-day architecture.

Wanted delta:
- primary human artifacts and retained artifacts remain the meaning-bearing center,
- while mirrors, receipts, execution artifacts, indexes, and overlays are treated as clearly
  secondary support structures.

Architectural consequence:
- runtime seams should make it harder for machine-side projections to silently become the real
  source of truth.

### 4. From vague storage language to explicit persistence surfaces

Current tendency:
- notes, storage, mirrors, retained material, and system metadata are still easy to read as one
  loosely unified persistence model.

Wanted delta:
- the architecture explicitly distinguishes:
  - writing surface,
  - retention surface,
  - system surface,
  without implying that all runtime hard-routing is already implemented.

Architectural consequence:
- future runtime contracts should make it harder for human-authored artifacts, retained artifacts,
  and system-plane execution/accountability records to collapse into one vague storage abstraction.
- the system surface may hold durable support structures, but it must not silently become the only
  real semantic center.

### 5. From flattened commitment handling to commitment-first semantics

Current tendency:
- open loops, projects, next actions, waiting states, and accountability-bearing execution concerns
  are still easy to flatten into generic note state, generic review labels, or execution-plan
  vocabulary.

Wanted delta:
- commitments are treated as a distinct semantic family,
- and architecture keeps them separate from:
  - human-facing artifacts,
  - retained artifacts,
  - execution plans,
  - and generic lifecycle labels.

Architectural consequence:
- future runtime design should preserve commitment semantics without pretending that the target-state
  commitment model is already implemented.

### 6. From scope-only retrieval to relation-aware retrieval

Current tendency:
- retrieval remains largely governed by scope filters, path hints, and flattened runtime metadata,
  even when richer context and provenance semantics exist elsewhere in the repo.

Wanted delta:
- retrieval remains conservative by default,
- but can reason over scope, explicit relations, provenance, retained artifacts, and overlap
  structures together,
- without pretending that path or one scope field is the whole semantic model.

Architectural consequence:
- retrieval architecture should evolve toward combining multiple bounded signals rather than
  overloading one boundary mechanism.

### 7. From retrieval-as-orientation to explicit retrieval/orientation/resurfacing separation

Current tendency:
- retrieval, orientation, resurfacing, ranking, recency, and `zone` overlays are easy to read as
  one blended concern.

Wanted delta:
- retrieval remains the find/return capability,
- orientation remains the help-the-human-regain-situational-understanding capability,
- resurfacing remains the bring-back-into-attention capability,
- and salience remains a derived influence rather than hidden semantic authority.

Architectural consequence:
- future runtime design should expose why something was found, why something was surfaced again, and
  why those are not always the same explanation.

### 8. From filesystem as semantic engine to filesystem as projection

Current tendency:
- path, folder family, and storage location still risk carrying too much semantic weight in runtime
  interpretation.

Wanted delta:
- filesystem layout remains useful, pragmatic, portable, and human-scannable,
- but acts as a projection of primary placement rather than as the full ontology.

Architectural consequence:
- one primary stored location must remain compatible with richer relations, overlapping spheres, and
  later schema evolution.

### 9. From collapsed support surfaces to explicit authority and accountability seams

Current tendency:
- mirrors, receipt-like note status, runtime traces, and execution artifacts are still easy to read
  as one blended family of support surfaces.

Wanted delta:
- architecture keeps human-facing artifacts, retained artifacts, mirror artifacts, receipt
  artifacts, and execution/runtime traces distinct enough that each can carry the right authority.

Architectural consequence:
- future runtime design should preserve projection/portability semantics for mirrors,
  accountability semantics for receipts, and trace semantics for runtime records without forcing
  them into one store-shaped meaning.

### 10. From single-runtime assumptions to distributed local-first continuity

Current tendency:
- parts of the architecture still implicitly assume one main runtime view with secondary sync or
  satellite behavior added later.

Wanted delta:
- local-first multi-device use is normal architecture,
- devices may have different roles and different partial views,
- and eventual consistency is expected across devices and replicas rather than strong immediate
  consistency.

Architectural consequence:
- sync, ingest, receipts, rebuild flows, and retrieval must tolerate lag, partial replicas, and
  delayed convergence without making central artifacts unintelligible or unsafe,
- while keeping instance provenance and replica-local state distinct from the underlying artifact's
  identity.

### 11. From architecture-by-implementation-seam to architecture-by-human invariant

Current tendency:
- runtime seams such as watcher logic, path assumptions, metadata projections, or legacy labels can
  still end up carrying more semantic authority than intended.

Wanted delta:
- the architecture should be led by stable human invariants:
  - central artifacts remain intelligible,
  - accountability remains inspectable,
  - context integrity remains protected,
  - and retained material remains usable without being collapsed into note semantics.

Architectural consequence:
- implementation seams remain important, but they should be judged by whether they preserve these
  invariants rather than by whether they are convenient internal boundaries.

### 12. From generic artifact handling to creative-process-aware runtime support

Current tendency:
- runtime design language is still strongest around knowledge, retrieval, commitments, and scope.

Wanted delta:
- runtime surfaces preserve creative fragments, threads, iteration, revision, world continuity, and
  selective stabilization,
- without forcing exploratory material into settled-note or task semantics too early.

Architectural consequence:
- future writing, retrieval, mirroring, and support surfaces should preserve exploratory ambiguity,
  alternatives, and partial stabilization as normal runtime realities.

## How to use this delta

When evaluating architecture findings or proposed changes:
- classify small contract-corrections as current-state fixes,
- classify coupling-reduction or seam-cleanup work as enablement,
- and classify changes that materially realize the deltas above as `v6.0` target-state work.

If a proposal makes runtime terminology, path placement, or store projection more semantically
authoritative than the human-first contracts allow, it is probably moving in the wrong direction
even if it simplifies implementation locally.

## Non-goals for this target doc

This document does not yet define:
- a concrete DB schema,
- a concrete graph schema,
- exact event payload redesigns,
- or a complete service decomposition.

Those should stay downstream of the review.

## Exit condition

This target-state doc becomes actionable when:
- the architecture review has identified which current assumptions conflict with the concept
  contracts,
- those findings have been classified into current bug, enablement, or `v6.0` target-state change,
- and the repo can sequence changes without corrupting `docs/ARCHITECTURE.md` as current-state SoT.

## Related documents

- `docs/ARCHITECTURE.md`
- `docs/STATUS.md`
- `docs/plans/ARCHITECTURE_REVIEW_READINESS.md`
- `docs/PROJECT_KERNEL.md`
- `docs/HUMAN-FLOWS.md`
- `docs/ROADMAP.md`
- `docs/ONTOLOGY_RUNTIME_BRIDGE.md`
- `docs/CONCEPTS/COGNITIVE_ONTOLOGY.md`
- `docs/CONCEPTS/ONTOLOGY_VOCABULARY.md`
- `docs/CONCEPTS/MIRROR_RECEIPT_DECISION.md`
- `docs/CONCEPTS/CONTEXT_TERMINOLOGY_CONTRACT.md`
- `docs/CONCEPTS/CONTEXT_REPRESENTATION_POSTURE.md`
