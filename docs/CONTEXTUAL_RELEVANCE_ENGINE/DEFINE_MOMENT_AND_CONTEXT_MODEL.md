---
name: Define Moment Artifact and Context/Interruptibility Model
description: Concept contracts for the "moment" as a first-class vault-native artifact and for the interruptibility/cognitive-load dimension of the context model.
task_id: CRE-01
source_anchor: docs/plans/CONTEXTUAL_RELEVANCE_ENGINE.md :: 3. Shape of the engine
parent_capability: Contextual Relevance Engine
prerequisites: []
depends_on: []
can_parallelize_with: []
---

# Define Moment Artifact and Context/Interruptibility Model

## Purpose

The engine produces **moments** (the right thing surfaced at the right time) by reading a **context
model**. Neither is defined yet. This task writes the two foundational concept contracts the rest of
the capability builds on, with no runtime change.

## What This Task Does

- Defines the **moment** as a first-class, vault-native artifact: its Markdown home in the vault, its
  schema (trigger, the need served, surfaced references with provenance, urgency, lifecycle), its
  receipt, and its non-authoritative projection into the companion UI. A moment is a projection /
  proposal, never silent truth.
- Extends the **context model** with an **interruptibility / cognitive-load** dimension: how
  interruptible the human is right now (e.g., home / focus / 1-1 meeting / sleep). It grounds this in
  the existing cognitive-load surface rather than inventing a parallel one, and names the
  zero-tolerance states (sleep / declared do-not-disturb).
- Establishes that **one context model feeds two consumers**: relevance (what to surface) and
  interruptibility (whether/how to reach out).

## Concretely

New / extended concept contracts under `docs/CONCEPTS/` (exact filenames decided in review), e.g.:

- `docs/CONCEPTS/MOMENT_ARTIFACT_CONTRACT.md` — schema, vault home, provenance, receipt, projection.
- An interruptibility section added to the context-model contracts
  (`docs/CONCEPTS/CONTEXT_AND_ARTIFACT_DIMENSIONS.md` / `COGNITIVE_AXES_AND_SPHERES.md`) that
  references `docs/COGNITIVE_LOAD_PROJECTION_LAYER.md`.

A small schema fixture/example of a moment artifact accompanies the contract so downstream tasks have
a concrete shape to build against.

## Why This Matters

If the moment artifact and the interruptibility dimension are not defined first, the relevance
evaluator and the scarcity gate (task 2) and both implementation slices (tasks 3–4) have nothing
concrete to produce or read. Getting the vault-native home and provenance right here is what keeps the
capability vault-first and non-authoritative.

## Acceptance Criteria

- [ ] A moment-artifact concept contract exists defining vault home, schema, provenance, receipt, and companion-UI projection, with a worked example.
  - Verify: doc writeback at `docs/CONCEPTS/MOMENT_ARTIFACT_CONTRACT.md :: Schema` (+ example fixture committed alongside).
- [ ] The context model carries an explicit interruptibility / cognitive-load dimension, grounded in the cognitive-load projection layer, naming the zero-tolerance states.
  - Verify: doc writeback at `docs/CONCEPTS/CONTEXT_AND_ARTIFACT_DIMENSIONS.md :: Interruptibility` referencing `docs/COGNITIVE_LOAD_PROJECTION_LAYER.md`.
- [ ] The contracts state the non-authoritative, vault-first, provenance-preserving posture explicitly (a moment is a proposal/projection, never silent truth).
  - Verify: doc writeback at `docs/CONCEPTS/MOMENT_ARTIFACT_CONTRACT.md :: Authority posture`.

## How to Verify (Pre-Merge)

- `python3 scripts/docs_guard.py` and `pytest tests/architecture/test_docs_index.py -q` pass (new docs carry State/frontmatter and are indexed).
- Owner ratifies the contracts in PR review (this is the design control point).
- `rg -n "Interruptibility|moment artifact|zero-tolerance" docs/CONCEPTS/` shows the new anchors.

## Out of Scope

- Any runtime implementation, evaluator, gate, or UI.
- External calendar/email/location sources (deferred connector slice).
- The relevance evaluator and reach-out/scarcity contracts (task 2).

## Related Docs

- `docs/plans/CONTEXTUAL_RELEVANCE_ENGINE.md` (brief, §3)
- `docs/CONCEPTS/SALIENCE_AND_ATTENTIONAL_RELEVANCE_CONTRACT.md`
- `docs/COGNITIVE_LOAD_PROJECTION_LAYER.md`
- `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md`

## Related GitHub Issues

Filed as one `agent:ready` issue (design/concept-contract task). The owner shapes the contracts in PR
review; do not over-split — one coherent design pass produces both contracts.
