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
- eventual sync,
- partial replicas,
- and rebuildable derived layers.

Implication:
- central artifacts must stay durable and understandable even when relation layers or derived views
  are incomplete on a given device.

## Likely v6.0 architecture themes

These are not yet commitments, but they are the most plausible themes the review should test
against the current runtime:

- a more explicit separation between artifact identity, context relations, and runtime scope
- cleaner runtime handling of shared participation vs cross-scope allowance
- retrieval that can reason over relation-bearing context instead of a single flattened scope model
- a reduced tendency for watcher/path/layout assumptions to act as domain truth
- clearer seams between human-facing artifacts, mirror surfaces, receipt surfaces, and execution
  surfaces
- architecture that treats local-first multi-device use as part of normal operation rather than a
  later bolt-on

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
- `docs/plans/ARCHITECTURE_REVIEW_READINESS.md`
- `docs/PROJECT_KERNEL.md`
- `docs/HUMAN-FLOWS.md`
- `docs/CONCEPTS/COGNITIVE_ONTOLOGY.md`
- `docs/CONCEPTS/CONTEXT_TERMINOLOGY_CONTRACT.md`
- `docs/CONCEPTS/CONTEXT_REPRESENTATION_POSTURE.md`
