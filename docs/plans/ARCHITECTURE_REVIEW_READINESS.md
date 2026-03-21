State: Plan (entry criteria for architecture/system-design review).

# Architecture Review Readiness

## Purpose

This document defines what should be sufficiently clear before the repo spends significant effort on
a full architecture or system-design review.

The goal is to avoid reviewing architecture against a moving or under-specified human model.

## Why this gate exists

Architecture review is only useful if we know what the architecture is supposed to preserve.

At the current stage, the biggest remaining risk is not that the architecture is wrong in detail.
It is that we review it against an under-specified context model and therefore miss the real
misalignments.

## Readiness criteria

The following should be clear enough before a deeper architecture review:

### 1. Human function baseline

The repo should have a stable enough statement of:
- what the system is for,
- which human problems it solves,
- and which work modes must remain first-class.

Current sources:
- `docs/HUMAN-FLOWS.md`
- `docs/CONCEPTS/USER_NEEDS_MODEL.md`

Status:
- largely ready

### 2. Context model baseline

The repo should have a clear enough decision about:
- `sphere`
- `context`
- `domain` / operational scope
- `situated role identity`
- `shared participation`
- `bridge` / explicit cross-scope allowance

Current source:
- `docs/CONCEPTS/CONTEXT_MODEL_DECISION_FRAME.md`
- `docs/CONCEPTS/CONTEXT_TERMINOLOGY_CONTRACT.md`
- `docs/CONCEPTS/CONTEXT_REPRESENTATION_POSTURE.md`

Status:
- mostly ready in terminology and representation posture; concrete schema remains open

### 3. Artifact-dimension baseline

The repo should be clear enough on:
- what belongs in artifact class/function,
- what belongs in trust/provenance,
- what belongs in commitment relations,
- what belongs in context relations,
- and what remains derived.

Current sources:
- `docs/CONCEPTS/COGNITIVE_AXES_AND_SPHERES.md`
- `docs/CONCEPTS/CONTEXT_AND_ARTIFACT_DIMENSIONS.md`
- `docs/CONCEPTS/COGNITIVE_ONTOLOGY.md`
- `docs/CONCEPTS/SALIENCE_AND_ATTENTIONAL_RELEVANCE_CONTRACT.md`
- `docs/CONCEPTS/CREATIVE_PROCESS_CONTRACT.md`

Status:
- mostly ready for architecture-facing use, but review should explicitly preserve newer companion
  contracts around salience/resurfacing and creative process rather than flattening them back into
  retrieval, lifecycle, or task semantics

### 4. Catalog/path projection posture

The repo should know:
- what the filesystem tree is allowed to mean,
- what it must not be forced to mean,
- and which parts of semantics stay above path level.

Current sources:
- `docs/CONCEPTS/CATALOG_PROJECTION_PRINCIPLES.md`
- `docs/CONCEPTS/PORTABILITY_CONTRACT.md`

Status:
- good enough for provisional architecture review

### 5. Runtime-language caveats

The repo should know which runtime terms are legacy/provisional so architecture review does not
mistake them for settled ontology.

Current sources:
- `docs/CONCEPTS/ONTOLOGY_VOCABULARY.md`
- `docs/research/cognitive-semantics-literature-memo.md`

Status:
- ready enough

## What the next architecture review should examine

When the gate above is met, architecture review should focus on questions like:
- does runtime scope behavior reflect the intended context model,
- are retrieval defaults too narrow or too flat,
- does archive exposure preserve provenance and boundaries,
- are path/layout assumptions carrying too much meaning,
- do agent/event/store seams preserve artifact/projection distinctions,
- are derived signals being mistaken for durable truth,
- is resurfacing being confused with retrieval,
- and do creative/runtime surfaces preserve exploratory ambiguity and selective stabilization?

## Finding classification rule

The next architecture review should classify each meaningful finding into one of three buckets:

1. **Current-state mismatch / bug**
   Something in current runtime or `docs/ARCHITECTURE.md` conflicts with an already accepted
   contract and should be corrected in the active line.

2. **Enablement**
   A smaller change that prepares the architecture for better alignment without claiming the target
   state has already been reached.

3. **v6.0 target-state change**
   A larger architecture move that should be described first in:
   - `docs/plans/V60_ARCHITECTURE_TARGET.md`

This rule exists to keep `docs/ARCHITECTURE.md` trustworthy as current-state SoT.

## Not yet the right review questions

Before the context-model baseline is clearer, the repo should avoid spending energy on questions
like:
- exact service decomposition,
- exact graph/store topology,
- or detailed refactors of runtime boundaries

because those decisions may be downstream of unresolved semantics.

## Immediate next step

The next pass can move into architecture review, but with a narrow brief:
- test whether current runtime scope behavior matches the context terminology and representation
  posture,
- identify places where one-field `domain` assumptions still flatten richer context semantics,
- and check whether cross-scope permissions, retrieval defaults, and path assumptions are carrying
  too much ontological meaning.

Any substantial architecture changes discovered in that pass should be captured as wanted state in:
- `docs/plans/V60_ARCHITECTURE_TARGET.md`
rather than rewritten directly into current-state architecture docs.
