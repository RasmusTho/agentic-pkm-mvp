State: Concept contract companion (representation posture for context semantics; flexible enough for future schema change).

# Context Representation Posture

## Purpose

This document defines how the context model should be represented in principle before we harden:
- metadata fields,
- relation stores,
- retrieval filters,
- path projections,
- or architecture assumptions.

It exists to answer one narrow question:
- for each context primitive, should it usually be represented as a durable marker, an explicit
  relation, a situational projection, or a bounded permission object?

This is not yet a final schema contract.
It is the representation posture that should guide later schema and architecture work.

Read this after:
- `docs/CONCEPTS/CONTEXT_TERMINOLOGY_CONTRACT.md`
- `docs/CONCEPTS/CONTEXT_AND_ARTIFACT_DIMENSIONS.md`
- `docs/CONCEPTS/COGNITIVE_ONTOLOGY.md`

Read this before:
- schema hardening,
- retrieval policy hardening,
- and architecture/system-design review.

## Core claim

The context model should not be represented as one flat metadata bundle.

At minimum, the repo needs to distinguish between:
1. durable working boundaries,
2. contextual relations,
3. situational activations or projections,
4. and explicit permission structures.

If those are collapsed, the runtime will either:
- overfit to one narrow scope model,
- or mistake temporary context for durable truth.

## Representation classes

### 1. Durable markers

These are explicit, persistent markers that the runtime may safely depend on for routine behavior.

They are appropriate when:
- safety or accountability depends on them,
- stable default behavior depends on them,
- or the meaning is narrow and durable enough to justify field-like persistence.

### 2. Explicit relations

These are meaningful links between artifacts, commitments, spheres, or roles.

They are appropriate when:
- the meaning is many-to-many,
- one thing may legitimately participate in several contexts,
- or a single-value field would falsely flatten the semantics.

### 3. Situational activations or projections

These are current, contextual, or derived states.

They are appropriate when:
- relevance depends on the current moment,
- the meaning is partly inferred or temporary,
- or storing it as durable artifact essence would mislead later interpretation.

### 4. Explicit permission objects

These are bounded, auditable structures that authorize repeated crossing of an operational
boundary.

They are appropriate when:
- the runtime needs a durable standing permission,
- the human should be able to inspect or revoke it,
- and accidental crossing would be unacceptable.

## Posture by context primitive

### Sphere

Default posture:
- explicit relation or declared membership

Why:
- a sphere is overlapping lived belonging,
- and it is often many-to-many rather than a good single-value field.

What is acceptable:
- explicit sphere memberships on artifacts, commitments, or collections when the human wants them
  represented,
- sphere relations stored separately from the artifact's primary path,
- partial or absent sphere representation when the artifact still remains understandable.

What to avoid:
- requiring every artifact to declare exactly one sphere,
- treating sphere as the same thing as path home or operational scope,
- or assuming lack of an explicit sphere marker means lack of human relevance.

### Situated Role Identity

Default posture:
- relation or situational activation

Why:
- role identity is often active in a situation rather than intrinsic to the artifact itself.

What is acceptable:
- explicit declaration where the human intentionally marks voice, responsibility, or stance,
- contextual activation during retrieval, drafting, or review,
- optional representation in artifacts or receipts when it materially affects interpretation.

What to avoid:
- making role identity a required field on every artifact,
- treating it as a bucket or folder,
- or building a heavy identity engine before the human need is proven.

### Context

Default posture:
- situational activation, derived composition, or lightweight runtime object

Why:
- context is temporal and situational,
- and often combines spheres, role identity, purpose, commitments, and current constraints.

What is acceptable:
- ephemeral context objects in runtime,
- receipt-level recording of context for explainability,
- partial reconstruction of context from active scope, task, and artifact relations.

What to avoid:
- forcing every artifact to carry one canonical full context object,
- or pretending context is as durable as sphere membership or operational scope.

### Shared Participation

Default posture:
- explicit relation

Why:
- this is the core overlap relation,
- and overlap should not be forced into a single-value field or one-home fiction.

What is acceptable:
- explicit shared-participation relations when overlap matters for retrieval, explanation, or
  protection of meaning,
- partial representation where only some overlaps are worth making durable,
- human-declared or curated relations that later inform bounded runtime behavior.

What to avoid:
- replacing shared participation with only a permission object,
- treating overlap as exceptional,
- or inferring exclusive belonging from one current path or one current scope.

### Operational Scope

Default posture:
- durable explicit marker where runtime behavior depends on it

Why:
- retrieval, action gating, path defaults, and conservative safety behavior need a narrower and more
  stable boundary than lived context alone provides.

What is acceptable:
- one active operational scope per runtime operation,
- explicit scope markers on artifacts when the system needs them for routine handling,
- `unknown`, `unscoped`, or similarly conservative states where classification is incomplete.

What to avoid:
- making operational scope carry the whole human meaning model,
- assuming one operational scope means one total sphere membership,
- or silently inferring persistent scope crossings from ordinary overlap.

### Explicit Cross-Scope Allowance

Default posture:
- durable explicit permission object

Why:
- this is a bounded runtime authorization, not just a semantic relation.

What is acceptable:
- an auditable record with purpose, bounds, permitted uses, authorization, and revocation semantics,
- persistent reuse of the same allowance across repeated runtime actions,
- human-legible receipts for creation, use, and removal.

What to avoid:
- inferring an allowance from shared participation alone,
- treating every overlap as requiring one,
- or hiding it inside path/layout conventions instead of making it inspectable.

## Safe representation rules

1. An artifact may have one primary operational scope and several contextual relations.
2. An artifact may have no explicit sphere membership and still remain meaningful.
3. Shared participation may be represented for some overlaps and absent for others without implying
   exclusivity.
4. Context may be recorded for a specific operation or receipt without becoming durable artifact
   essence.
5. An explicit cross-scope allowance must never be inferred merely because overlap exists.
6. Unknown or partial context must be a legal state; the system should degrade conservatively rather
   than fabricate certainty.

## Minimal architecture-safe assumptions

The architecture may safely assume:
- one active operational scope per retrieval/action invocation,
- artifacts may have multiple sphere memberships or none,
- shared participation may exist independently of explicit cross-scope allowances,
- role identity may matter even when not stored as a durable artifact field,
- and context may be partly reconstructed rather than fully stored.

The architecture should not assume:
- that every artifact has one final semantic context,
- that path alone determines context,
- that an allowance object is the ontology of overlap,
- or that missing context metadata means no meaningful relation exists.

## Path and filesystem implications

This posture is compatible with:
- one primary stored location,
- a MECE tree,
- local-first multi-device use,
- and eventual sync.

Because:
- path may project a primary operational scope or broad storage family,
- while richer spheres, shared participation, and context remain above path level.

## Why this keeps the system flexible

This posture protects flexibility in two directions:
- we can add richer relation models later without breaking early artifacts,
- and we can keep the runtime conservative now without pretending the early runtime boundary model
  is the whole human ontology.

That is the main design goal at this stage.

## Related documents

- `docs/CONCEPTS/CONTEXT_TERMINOLOGY_CONTRACT.md`
- `docs/CONCEPTS/CONTEXT_AND_ARTIFACT_DIMENSIONS.md`
- `docs/CONCEPTS/COGNITIVE_AXES_AND_SPHERES.md`
- `docs/CONCEPTS/COGNITIVE_ONTOLOGY.md`
- `docs/CONCEPTS/LAYERING_MODEL.md`
- `docs/plans/ARCHITECTURE_REVIEW_READINESS.md`
