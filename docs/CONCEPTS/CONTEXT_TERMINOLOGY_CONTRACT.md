State: Concept contract companion (canonical context language and compatibility aliases; human-first and representation-cautious).

# Context Terminology Contract

## Purpose

This document narrows the context vocabulary enough to support further ontology, requirements, and
architecture work without prematurely freezing schema or metadata design.

It exists to answer:
- which context terms should be canonical in human-first docs,
- which older runtime terms may remain as compatibility language,
- and how human context language should stay distinct from narrower operational scope language.

This is a terminology and meaning contract, not a storage or schema contract.

Read this after:
- `docs/CONCEPTS/COGNITIVE_AXES_AND_SPHERES.md`
- `docs/CONCEPTS/CONTEXT_MODEL_DECISION_FRAME.md`

Read this before:
- `docs/CONCEPTS/CONTEXT_REPRESENTATION_POSTURE.md`
- `docs/CONCEPTS/COGNITIVE_ONTOLOGY.md`
- `docs/CONCEPTS/LAYERING_MODEL.md`
- architecture or schema discussions that depend on context words.

## Core claim

Human context should be described primarily through:
- `sphere`,
- `situated role identity`,
- `context`,
- and `shared participation`.

The system may still need:
- `operational scope` for retrieval/action gating,
- and `explicit cross-scope allowance` for durable runtime permissions.

These are not the same kind of thing.
The human model should not be flattened into the runtime permission model.

## Canonical terms

### Sphere

A sphere is an overlapping region of human life, concern, practice, or meaning.

Use `sphere` when the point is lived belonging or long-lived relevance.
Do not use it as if it implied MECE partitioning or one exclusive folder home.

Examples:
- work,
- private life,
- learning,
- creative practice,
- roleplaying/world-building,
- reflective/self-development work.

### Situated Role Identity

A situated role identity is the mode of self, responsibility, tone, and judgment that becomes
active in a situation.

Use this term when the distinction is not only what area of life something belongs to, but how the
human is oriented within that situation.

### Context

A context is a situated configuration of currently relevant spheres, role identities, purposes,
commitments, and constraints.

Use `context` when the point is what is relevant right now or in a specific situation.
Context is narrower and more temporal than sphere.

### Shared Participation

Shared participation is the relation by which an artifact, commitment, or concern meaningfully
belongs to more than one sphere or context.

Use this term as the primary way to talk about overlap.
This is the Venn-diagram layer of the model.

### Operational Scope

An operational scope is a narrower working boundary used by the system for retrieval, action
gating, path defaults, and similar runtime decisions.

Use this term when the discussion is about what the runtime includes, excludes, writes to, or acts
within by default.

### Explicit Cross-Scope Allowance

An explicit cross-scope allowance is a bounded, auditable permission for persistent or reusable
crossing between operational scopes.

Use this term when the runtime needs a durable permission object or policy surface for repeated
cross-scope reuse.

This is secondary to shared participation in the human model.

## Compatibility aliases and current repo language

### `domain`

Current repo language often uses `domain`.

Interpretation rule:
- when older or runtime-oriented docs say `domain`, read it as `operational scope` unless the text
  clearly means a broader human context.

Preferred posture going forward:
- use `sphere` or `context` for human meaning,
- use `operational scope` when the runtime boundary is what matters,
- keep `domain` mainly as compatibility language in code and transition-era docs.

### `bridge`

Current repo language sometimes uses `bridge`.

Interpretation rule:
- read `bridge` as a compatibility alias for `explicit cross-scope allowance`, not as the primary
  mental model of overlap.

Preferred posture going forward:
- use `shared participation` when describing overlap in human meaning,
- use `explicit cross-scope allowance` when describing durable runtime permission,
- keep `bridge` only where compatibility with existing code/docs still matters.

## Usage rules

1. Use `sphere`, `context`, and `shared participation` when describing the human problem space.
2. Use `operational scope` when describing retrieval boundaries, path defaults, action gating, or
   similar runtime behavior.
3. Do not treat overlap as something that only exists once an allowance/bridge has been created.
4. Do not force one path home or one active scope to imply one total meaning.
5. Do not assume that every relevant context relation needs a dedicated durable field immediately.
6. When in doubt, prefer richer human semantics over inherited runtime shorthand.

## Representation posture

Detailed guidance now lives in:
- `docs/CONCEPTS/CONTEXT_REPRESENTATION_POSTURE.md`

The current recommended posture is:

- `sphere`
  Usually a relation or declared membership, not necessarily a storage path.

- `situated role identity`
  Usually a relation or contextual activation, not a bucket.

- `context`
  Often situational or partly derived; not necessarily a heavy persisted object at first.

- `shared participation`
  Usually a relation, not a single-value field.

- `operational scope`
  Often explicit and durable enough to matter in runtime and policy.

- `explicit cross-scope allowance`
  Only needed when persistent crossing should be permitted, bounded, and auditable.

## What this does not decide yet

This contract does not yet decide:
- the exact schema shape for context metadata,
- whether every artifact should declare sphere membership explicitly,
- whether role identity is commonly user-declared or often inferred,
- or whether `bridge` survives long-term as a runtime label.

Those remain downstream design questions.

## Why this contract exists

Without this distinction, the repo keeps drifting between:
- human context as lived overlap,
- runtime scope as access boundary,
- and permission objects as if they were the ontology of overlap itself.

That would make later architecture review low-signal.

## Related documents

- `docs/CONCEPTS/COGNITIVE_AXES_AND_SPHERES.md`
- `docs/CONCEPTS/CONTEXT_MODEL_DECISION_FRAME.md`
- `docs/CONCEPTS/CONTEXT_REPRESENTATION_POSTURE.md`
- `docs/CONCEPTS/COGNITIVE_ONTOLOGY.md`
- `docs/CONCEPTS/LAYERING_MODEL.md`
- `docs/CONCEPTS/ONTOLOGY_VOCABULARY.md`
- `docs/CONCEPTS/CONTEXT_AND_ARTIFACT_DIMENSIONS.md`
