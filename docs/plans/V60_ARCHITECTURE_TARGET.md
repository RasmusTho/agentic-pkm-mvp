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

### 4. Retrieval should combine scope, relations, and provenance rather than overloading one boundary

Wanted state:
- retrieval defaults remain conservative,
- but can draw on explicit relations, retained artifacts, and overlap structures without pretending
  the path tree or one domain field is the full truth.

Implication:
- retrieval architecture should be reviewed for places where it is too flat, too scope-only, or too
  path-derived.

### 5. Filesystem and path stay projections, not master ontology

Wanted state:
- one primary stored location remains compatible with richer context relations,
- and path/layout choices remain pragmatically useful without deciding too much of the domain model.

Implication:
- architecture should not force path family, vault root, or folder placement to become the main
  semantic engine.

### 6. Accountability and explainability remain architecture-level invariants

Wanted state:
- cross-scope allowances, retrieval context, agent actions, and durable changes remain inspectable
  and receipt-bearing.

Implication:
- richer semantics must not come at the cost of legibility or trust.

### 7. Local-first multi-device operation is designed as an architecture property, not an afterthought

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

### 8. Salience and resurfacing are architecture concerns, not hidden ranking side effects

Wanted state:
- retrieval and resurfacing are treated as related but distinct architecture concerns,
- attentional salience and surfacing need can influence runtime behavior without becoming hidden
  control semantics,
- and `zone` remains a derived overlay rather than the de facto ontology of what matters.

Implication:
- future architecture should expose how resurfacing works, what signals it may use, and why it does
  not override trust, scope, or provenance boundaries.

### 9. Creative-process support is preserved as a first-class architecture concern

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
- retrieval that can reason over relation-bearing context instead of a single flattened scope model
- a reduced tendency for watcher/path/layout assumptions to act as domain truth
- clearer seams between human-facing artifacts, mirror surfaces, receipt surfaces, and execution
  surfaces
- architecture that treats local-first multi-device use and eventual consistency as part of normal
  operation rather than a later bolt-on
- architecture that treats resurfacing as distinct from retrieval and keeps `zone` derived
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

### 4. From scope-only retrieval to relation-aware retrieval

Current tendency:
- retrieval remains largely governed by scope filters, path hints, and flattened runtime metadata,
- even when richer context and provenance semantics exist elsewhere in the repo.

Wanted delta:
- retrieval remains conservative by default,
- but can reason over scope, explicit relations, provenance, retained artifacts, and overlap
  structures together,
- without pretending that path or one scope field is the whole semantic model.

Architectural consequence:
- retrieval architecture should evolve toward combining multiple bounded signals rather than
  overloading one boundary mechanism.

### 5. From filesystem as semantic engine to filesystem as projection

Current tendency:
- path, folder family, and storage location still risk carrying too much semantic weight in runtime
  interpretation.

Wanted delta:
- filesystem layout remains useful, pragmatic, portable, and human-scannable,
- but acts as a projection of primary placement rather than as the full ontology.

Architectural consequence:
- one primary stored location must remain compatible with richer relations, overlapping spheres, and
  later schema evolution.

### 6. From single-runtime assumptions to distributed local-first continuity

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
  delayed convergence without making central artifacts unintelligible or unsafe.

### 7. From architecture-by-implementation-seam to architecture-by-human invariant

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

### 8. From hidden salience heuristics to explicit resurfacing architecture

Current tendency:
- attentional relevance is easy to leave implicit inside ranking, recency, or `zone`-like overlays.

Wanted delta:
- resurfacing is treated as a deliberate architectural capability distinct from retrieval,
- salience remains derived and explainable,
- and `zone` stays a bounded overlay rather than a hidden source of semantic authority.

Architectural consequence:
- future runtime design should separate findability from resurfacing need and preserve explanations
  for why something came back into view.

### 9. From generic artifact handling to creative-process-aware runtime support

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

## Architecture review findings (2026-03-25)

This section records the first pass of concrete runtime findings classified against the accepted
concept contracts. The exit condition in this document has been triggered: findings are now
classified, and sequencing can begin.

### Current-state bugs (violate already accepted contracts — fix in v5.x)

**Finding 1: Domain inferred from path as fallback**
- Location: `app/retrieval/hybrid.py` lines 135-145, `_extract_domain()`
- Contract violated: `LAYERING_MODEL.md` §Missing or unknown domain — unclassified content must
  not be assumed to belong to the active domain. `CONTEXT_REPRESENTATION_POSTURE.md` — domain is
  a durable marker the runtime depends on, not a silent derivation.
- Current behavior: if `payload["domain"]` is absent, falls back to `path.parts[0]` — making
  moving a note between folders silently change its domain.
- Fix: treat missing domain as `unscoped`; remove path-based inference.

**Finding 2: Zone read from artifact payload as if stored**
- Location: `app/agents/ask/graph.py:22`, `app/agents/ask/utils.py:38,70`, `app/api/routes/ask.py:91-92`
- Contract violated: `LAYERING_MODEL.md` §Zone is derived, not a gate — zone affects
  prioritization, not permission; it is not a stored artifact field.
- Current behavior: zone is read from payload at retrieval time but is never written during ingest
  (`app/ingest/vault_alpha.py` has no zone assignment). All reads will silently return `None`.
- Fix: remove zone reads from artifact payloads; compute zone dynamically at retrieval time from
  recency/relations/usage signals.

**Finding 3: Domain not validated or recorded at write boundary**
- Location: `app/ingest/vault_alpha.py:501-544` (ingest never sets domain), `app/store/object_store.py`
  (accepts any payload without domain validation), `app/retrieval/hybrid.py:158-164`
- Contract violated: `LAYERING_MODEL.md` §Contract rules — "Every boundary crossing is
  explainable." and "Domain is the primary boundary."
- Current behavior: artifacts without domain are neither rejected nor marked `unscoped`; no audit
  trail of domain assignment exists.
- Fix: validate domain at `store.put()` time; mark missing as `unscoped`; emit ingest event
  recording assigned domain; update `_doc_in_scope()` to treat missing domain as `False`
  (conservative, not permissive).

### Enabling changes (reduce coupling, prepare path — may land in v5.x)

**Finding 4: Mirror conflates artifact identity with audit log**
- Location: `app/ingest/vault_alpha.py:331-363` (`_write_mirror()`), `app/services/note_log.py:6-19`
- Context: mirror at `System/Metadata/VaultMirror/<path>/<uuid>.md` mixes frontmatter (identity
  fields: uuid, title, review_state, maturity) with audit markers (ingest_fingerprint).
- `ARCHITECTURE.md` acknowledges this is provisional: "It should not be interpreted as the full
  canonical receipt model."
- Enablement: separate mirror writing into (a) minimal projection (identity fields only) and (b)
  receipt/audit log written separately. Ensure mirror path is in ingest ignore list.

**Finding 5: Promotion mutates artifact state without a clear transition record**
- Location: `app/promotion/consumer.py:66-91`, `app/services/note_update.py:36-88`
- Context: promotion writes `review_state` and `maturity` into both ObjectStore payload and vault
  frontmatter. No durable receipt records who authorized the promotion or when.
- `ONTOLOGY_VOCABULARY.md` flags this as an open seam: "promotion currently resolves into
  review_state mutation in both vault frontmatter and store payload."
- Enablement: emit a distinct promotion event (not just a state mutation); record a human-legible
  receipt artifact per promotion. The dual-write (store + vault) can remain for now; the receipt
  is the prep work.

### v6.0 target-state changes (larger semantic moves — describe here, sequence later)

**Finding 6: Single `domain` field represents all of human context**
- Directly maps to V60 pillar §1 (context model is layered, not flattened).
- Current runtime uses one flat string `domain` and `bridge_domains` list where the terminology
  contracts call for `sphere`, `situated role identity`, `context`, and `shared participation`
  as distinct semantic dimensions.
- Runtime locations: `app/retrieval/hybrid.py:148-155, 158-164`, `app/promotion/consumer.py:66-91`
- v6.0 action: introduce richer context relation model with explicit fields and relations.
  `domain` field becomes strictly `operational_scope`.

**Finding 7: `kind` is hardcoded to `"note"` for all ingested artifacts**
- Location: `app/ingest/vault_alpha.py:350, 512, 542, 562`
- Contract referenced: `docs/NOTE_KIND_POLICIES.md` — kind routes policy and does not define
  structure. `ARCHITECTURE.md` §Note Kind Policies — different artifact classes (vault note,
  source artifact, reflective artifact, creative artifact, system artifact) should activate
  different metadata axes.
- v6.0 action: introduce artifact kind determination at ingest time; each kind routes to a policy
  profile. Current hardcode stays as `vault_note` until the routing table is defined.

---

## Related documents

- `docs/ARCHITECTURE.md`
- `docs/plans/ARCHITECTURE_REVIEW_READINESS.md`
- `docs/adr/ADR-0006-deepagents-harness.md`
- `docs/PROJECT_KERNEL.md`
- `docs/HUMAN-FLOWS.md`
- `docs/CONCEPTS/COGNITIVE_ONTOLOGY.md`
- `docs/CONCEPTS/CONTEXT_TERMINOLOGY_CONTRACT.md`
- `docs/CONCEPTS/CONTEXT_REPRESENTATION_POSTURE.md`
