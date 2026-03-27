State: Concept contract (canonical state-axis semantics for artifact review posture and maturity).
Doc role: Core SoT
Authority: Canonical semantic contract for `review_state` and `maturity`; neighboring docs may constrain usage by policy, but must not redefine the meaning of these axes.

# State Axes Contract

## Purpose

This document defines the canonical semantics and value sets for the two primary artifact state
axes now established in the ontology-alignment work:
- `review_state`
- `maturity`

It exists to prevent these meanings from being silently collapsed back into one another.

Related docs:
- `docs/CONCEPTS/COGNITIVE_ONTOLOGY.md`
- `docs/CONCEPTS/ONTOLOGY_VOCABULARY.md`
- `docs/CONCEPTS/TEMPORAL_VALIDITY_AND_STALENESS_CONTRACT.md`
- `docs/CORE_CONTRACT.md`
- `docs/NOTE_KIND_POLICIES.md`
- `docs/FRONTMATTER.md`

## Contract boundary

These axes apply to artifact state, not to the full ontology.

They do not define:
- commitment structure,
- execution-plan state,
- event lifecycle,
- or every workflow/status field the system may eventually use.

They answer two narrower questions:
- `review_state`: what is the current review and mutation posture of this artifact?
- `maturity`: what is the current standing or development level of this artifact?

## Core rule

`review_state` and `maturity` are distinct semantic axes.

Therefore:
- `review_state` must not be used as the general sink for maturity outcomes,
- `maturity` must not be used as a proxy for mutation safety or review posture,
- and `promotion` must be treated as a transition family that may update one or both axes, not as
  a third synonym for either one.

## `review_state`

### Meaning

`review_state` describes review posture, mutation posture, or protection posture.

It answers:
- how safe is it to mutate this artifact automatically,
- and what level of review or protection has already been established?

### Canonical values

The canonical global value set for `review_state` is:
- `draft`
- `provisional`
- `reviewed`
- `protected`
- `archived`

### Value meanings

- `draft`
  - the artifact is still open to ordinary revision,
  - no stronger review or protection posture is being claimed.

- `provisional`
  - the artifact has some temporary or partial stabilization,
  - but remains open to further revision and should not be treated as fully settled.

- `reviewed`
  - the artifact has been reviewed to a level that should affect automation behavior,
  - ordinary mutation should now be more constrained and more attributable.

- `protected`
  - the artifact is intentionally guarded against routine mutation,
  - stronger intent, delegation, or explicit confirmation is required for change.

- `archived`
  - the artifact is no longer part of the active mutable working set,
  - mutation should normally be disallowed or treated as exceptional.

### Non-goals

`review_state` does not mean:
- inbox workflow stage,
- general task status,
- maturity or evergreen standing,
- or that a promotion transition has occurred.

## `maturity`

### Meaning

`maturity` describes the standing, development, or durability of an artifact in its domain role.

It answers:
- how developed is this artifact,
- how stabilized is it,
- and how enduring a standing does it currently have?

### Canonical values

The canonical global value set for `maturity` is:
- `raw`
- `draft`
- `developing`
- `stable`
- `evergreen`

### Value meanings

- `raw`
  - newly captured, minimally processed, or still highly unrefined.

- `draft`
  - meaningfully shaped enough to work with,
  - but not yet developed into a stable artifact.

- `developing`
  - actively being refined or consolidated,
  - with some structure but not yet durable enough to treat as settled.

- `stable`
  - sufficiently developed for reliable reuse or reference in normal work.

- `evergreen`
  - intentionally durable, reusable, and expected to retain standing over time.

### Non-goals

`maturity` does not mean:
- whether mutation is allowed,
- whether review has occurred,
- whether the artifact is active in an inbox/workflow,
- whether a transition intent has been emitted,
- or whether the artifact remains temporally current.

## Canonical relation between the axes

The axes are related but not reducible to one another.

Normalization rules:
- no maturity value implies one mandatory review state in the ontology,
- no review state implies one mandatory maturity value in the ontology,
- runtime compatibility layers may define mapping rules,
- but those mappings must be treated as implementation policy, not as semantic identity.

Current canonical compatibility policy:
- promotion to `maturity = evergreen` should map new writes toward `review_state = reviewed`
  rather than `review_state = evergreen`.
- `evergreen` should not be interpreted as permanently current; temporal validity and staleness are
  separate semantics.

## Legacy compatibility

The following values may still appear in runtime, notes, tests, or migration-era docs, but they are
not canonical global values for these axes:

### Legacy `review_state` values
- `evergreen`
- `promoted`
- `processed`
- `inbox`
- `logged`

Interpretation guidance:
- `evergreen` belongs on the `maturity` axis.
- `promoted` belongs to transition history or compatibility handling, not to a durable canonical
  state axis.
- `processed` is an implementation-era workflow/result marker, not a canonical review posture.
- `inbox` belongs to intake/workflow/status semantics, not to review posture.
- `logged` may be a kind-specific policy marker, but it is not part of the global canonical
  `review_state` contract.

Compatibility rule:
- readers may continue to accept these values during migration,
- writers should avoid producing new canonical data with them unless an explicit compatibility
  boundary requires it.

## Policy extension rule

`NOTE_KIND_POLICIES` may constrain:
- which axes are enabled,
- which values are allowed for a given kind,
- which defaults are applied,
- and which transitions require explicit confirmation.

However:
- policy may narrow the contract,
- policy may introduce tightly scoped kind-specific handling,
- but policy must not silently redefine the global meaning of the canonical values above.

## Migration direction

The intended migration direction is:
1. keep compatibility readers for legacy `review_state` values,
2. stop adding new writes that use legacy `review_state` values as semantic sinks,
3. write standing semantics to `maturity`,
4. keep review and mutation posture on `review_state`,
5. and move inbox/workflow semantics to a separate workflow/status layer over time.
