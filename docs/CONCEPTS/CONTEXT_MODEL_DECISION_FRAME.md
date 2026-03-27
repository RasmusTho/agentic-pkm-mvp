State: Concept decision record companion (context-model rationale, adopted posture, and residual open questions).

# Context Model Decision Frame

## Purpose

This document exists to record the decision pass that led to the current context-model posture before
it is silently baked into:
- metadata fields,
- retrieval behavior,
- path families,
- sync assumptions,
- or architecture boundaries.

It is not the final ontology.
It is the rationale and transition record behind the current terminology and representation contracts.

Read this after:
- `docs/HUMAN-FLOWS.md`
- `docs/CONCEPTS/COGNITIVE_AXES_AND_SPHERES.md`
- `docs/CONCEPTS/CONTEXT_AND_ARTIFACT_DIMENSIONS.md`

Use this alongside:
- `docs/CONCEPTS/CONTEXT_TERMINOLOGY_CONTRACT.md`
- `docs/CONCEPTS/CONTEXT_REPRESENTATION_POSTURE.md`
- architecture/system-design review that needs the reasoning behind the current posture.

## Why this needs to be explicit

The repo now has strong support for all of the following:
- contextual integrity matters,
- overlap between parts of life is normal,
- role-sensitive use matters,
- archive exposure must stay bounded,
- and operational scope should not silently replace the richer human context model.

The repo previously overloaded several key terms:
- `domain`
- `sphere`
- `context`
- `situated role identity`
- `shared participation`
- `bridge`

If their distinctions remain implicit, architecture will start making the choice for us through:
- indexes,
- watcher scope rules,
- retrieval filters,
- path structures,
- and event payloads.

That would be backwards.

## Current posture

The context model should be treated as layered, not flat.

The current adopted working layering is:

1. **Sphere**
   An overlapping region of life, concern, or practice.

2. **Situated role identity**
   The mode of self, responsibility, tone, and judgment that is active in a situation.

3. **Context**
   A current situated configuration of spheres, role identities, commitments, and purpose.

4. **Shared participation**
   The fact that artifacts, commitments, or concerns may legitimately belong to more than one
   sphere or context.

5. **Operational scope**
   A narrower working partition used by the system for retrieval, action gating, and path/default
   behavior.

6. **Explicit cross-scope allowance**
   A bounded runtime permission that makes recurring scope crossing intelligible when overlap needs
   a durable operational expression.

This remains revisitable as repo language, but it is the current coherent posture and is stronger
than using `domain` for all of these jobs at once.

## Candidate primitives and what they solve

### Sphere

What it solves:
- lived belonging,
- overlapping life areas,
- and non-MECE human reality.

Why it matters:
- work, learning, private life, creative practice, and RPG can overlap without collapsing into one
  mixed space.

Likely properties:
- many-to-many membership,
- stable enough to matter over time,
- not necessarily used directly as a storage path.

### Situated role identity

What it solves:
- why the same person thinks, judges, writes, and speaks differently in different settings.

Why it matters:
- the system is meant to support different ways of being and working, not merely different folders.

Likely properties:
- relational rather than file-defining,
- often active in context rather than baked into every artifact,
- may sometimes be declared explicitly, but not always.

### Context

What it solves:
- current situated use,
- current purpose,
- and the configuration that makes a given operation appropriate right now.

Why it matters:
- retrieval, proposals, and next-step help are often context-sensitive in the moment, not only
  sphere-sensitive in the abstract.

Likely properties:
- more temporal than sphere,
- may be partly derived,
- may not need a heavy persisted object model at first.

### Shared participation

What it solves:
- Venn-like overlap in lived meaning,
- recurring belonging across several parts of life,
- and reuse that is real before it becomes policy.

Why it matters:
- overlap is not just an exception that needs a bridge;
- it is often part of the human reality the system should preserve.

Likely properties:
- relational rather than bucket-like,
- may apply to artifacts, commitments, and concerns,
- should not require one exclusive home at the meaning layer.

### Operational scope

What it solves:
- what the system should include or exclude for a given retrieval or action surface.

Why it matters:
- architecture, watcher behavior, retrieval defaults, and action gating need a stricter concept than
  lived belonging.

Current note:
- the repo currently often uses `domain` for this.
- this may remain acceptable if `domain` is explicitly narrowed to this role.

### Explicit cross-scope allowance (`bridge` in current repo language)

What it solves:
- recurring operational crossing that should be explicit rather than accidental.

Why it matters:
- some cross-context reuse is normal and should not be forced into one-shot exceptions when the
  runtime needs a durable permission structure.

Likely properties:
- bounded,
- auditable,
- explicit about purpose and permitted uses.
- secondary to shared participation in the overall mental model.

## Residual open questions

### 1. How much longer should `domain` survive as repo language?

Current posture:
- `domain` is narrowed toward operational scope rather than carrying the whole human model.

Residual question:
- how aggressively should transition-era docs and code keep or retire the term?

### 2. How explicit should sphere representation become?

Current posture:
- spheres are first-class in the ontology and human-facing terminology.

Residual question:
- how much of that should become durable representation versus remain optional relation-level
  semantics?

### 3. How much shared participation should become durable?

Current posture:
- shared participation is first-class in the ontology because it best matches the human mental model
  and avoids making permission objects carry too much meaning.

Residual question:
- which overlaps are worth representing durably, and which should remain implicit or situational?

### 4. How often should situated role identity be made explicit?

Current posture:
- situated role identity remains first-class in the ontology, but without assuming a heavy runtime
  identity engine.

Residual question:
- when should it be user-declared, receipt-visible, or inferred contextually?

### 5. How much representation should be hardened now?

Current posture:
- the repo distinguishes explicit durable markers, explicit relations, situational/derived
  projections, and explicit permission objects.

Residual question:
- which of those should become concrete schema first, and which should remain flexible during the
  next implementation phase?

### 6. Which narrowed assumptions should architecture now take as given?

Current posture:
- runtime components may assume one active operational scope per invocation,
- artifacts may have multiple sphere memberships or none,
- shared participation may exist independently of explicit cross-scope allowances,
- and partial/unknown context is a legal state.

Residual question:
- which current components violate those assumptions or still flatten them?

## Evaluation criteria for the next decision pass

Any chosen context model should be judged against these questions:

### 1. Does it preserve contextual integrity?

Can it protect different ways of being and working so that:
- RPG does not bleed into work by accident,
- work does not colonize reflective or creative spaces,
- and the user can trust the system to support rather than flatten context?

### 2. Does it support normal overlap?

Can it express recurring overlap without pretending overlap is rare or pathological, and without
making one narrow permission object stand in for the whole phenomenon?

### 3. Does it avoid MECE pressure on lived meaning?

Can it allow richer belonging than the filesystem tree or default retrieval scope?

### 4. Does it support operational clarity?

Can the system still make clear decisions about:
- retrieval scope,
- action gating,
- archive exposure,
- and accountability?

### 5. Does it stay compatible with local files and future path projection?

Can it coexist with:
- one primary stored location,
- portable paths,
- eventual sync,
- and device-specific partial views?

### 6. Does it avoid overbuilding?

Can it support the user's actual needs without requiring:
- a large identity engine,
- brittle metadata burdens,
- or excessive manual classification?

## What architecture review should still not assume

Even with the current posture, architecture review should **not** assume:
- that `domain` is the final human context primitive,
- that context membership is exclusive,
- that every artifact has one final semantic scope,
- that path structure can fully encode context,
- or that current runtime scoping behavior already matches the intended human model.

## Context-model clarity now available for architecture/system-design review

The repo can now answer these questions clearly enough to support a serious architecture review:

1. The minimum context primitives the architecture must respect are `sphere`, `situated role identity`, `context`, `shared participation`, `operational scope`, and `explicit cross-scope allowance`.
2. Those do not belong to one flat metadata bundle; they split across relations, projections, durable markers, and permission objects.
3. `domain` is acceptable only as a narrowed operational or compatibility term.
4. Overlap is normal and must be first-class in retrieval/action design through shared participation rather than treated as pathology.
5. `bridge` may survive only as a narrow runtime label for persistent cross-scope permission, not as the main mental model.
6. Context meaning must remain partly path-independent even when files have one primary stored home.
7. Boundary crossing must remain explainable in human-legible terms.

## How to use this document now

Treat this document as rationale and transition record.

The current narrowed wording is captured in:
- `docs/CONCEPTS/CONTEXT_TERMINOLOGY_CONTRACT.md`

The current representation posture is captured in:
- `docs/CONCEPTS/CONTEXT_REPRESENTATION_POSTURE.md`

Architecture and schema work should follow those contracts directly and use this document only when
the reasoning behind them needs to be revisited.
