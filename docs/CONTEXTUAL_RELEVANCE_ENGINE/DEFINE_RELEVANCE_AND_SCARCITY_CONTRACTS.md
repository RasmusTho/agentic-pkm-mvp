---
name: Define Relevance Evaluator and Reach-out/Scarcity Gate Contracts
description: Concept contracts for the adaptive relevance evaluator and for the deterministic reach-out ladder + context-dependent interruption-threshold gate.
task_id: CRE-02
source_anchor: docs/plans/CONTEXTUAL_RELEVANCE_ENGINE.md :: 3.1 / 3.3
parent_capability: Contextual Relevance Engine
prerequisites: [CRE-01]
depends_on: [DEFINE_MOMENT_AND_CONTEXT_MODEL.md]
can_parallelize_with: []
---

# Define Relevance Evaluator and Reach-out/Scarcity Gate Contracts

## Purpose

Specify the two halves of the engine's core split: the **adaptive relevance evaluator** (the
intelligence — what does the human need now) and the **deterministic reach-out/scarcity gate** (the
discipline — whether and how to reach out). This is a docs/concept-contract task; no runtime change.

## What This Task Does

- **Relevance evaluator contract:** inputs (context model + declared patterns + learned signal),
  output (candidate moments with urgency, non-authoritative), the LLM-cognition posture, a
  deterministic fallback, and provenance/observability. Produces moments — does not enumerate them.
  Fits the `EMERGENT_FEATURES_MODEL` composition pattern and the
  `CAPABILITY_CONTRACT_MODEL` field set.
- **Reach-out / scarcity gate contract:** the graduated ladder (glance → in-app → OS push); the
  **context-dependent interruption threshold** driven by the interruptibility dimension (low load →
  lower bar, high load → higher bar); the **zero-tolerance floor** (sleep / declared DND → never
  push); **defer-not-drop** (suppressed moments degrade down the ladder and re-attempt); and the
  mapping of effects onto the #1881 governance tiers (Act / agent-review / ask-you).
- States the determinism boundary explicitly: adaptive in the relevance call; deterministic in the
  gate, the zero-tolerance floor, and receipts.

## Concretely

New concept contracts under `docs/CONCEPTS/` (filenames decided in review), e.g.
`RELEVANCE_EVALUATOR_CONTRACT.md` and `REACHOUT_AND_SCARCITY_GATE_CONTRACT.md`, cross-linked to the
moment + interruptibility contracts from task 1, the salience contract, and #1881.

## Why This Matters

These contracts are the boundary between "smart about what matters" and "disciplined about when it
intrudes." If the determinism boundary is fuzzy, the implementation risks either a firehose (gate too
soft) or a rule-locked engine (cognition too hard) — both violate the brief.

## Acceptance Criteria

- [ ] A relevance-evaluator contract exists: inputs, output (candidate moments + urgency), LLM-cognition posture, deterministic fallback, non-authoritative + provenance, against the capability-contract field set.
  - Verify: doc writeback at `docs/CONCEPTS/RELEVANCE_EVALUATOR_CONTRACT.md :: Contract`.
- [ ] A reach-out/scarcity gate contract exists: the ladder, the context-dependent interruption threshold, the zero-tolerance floor, defer-not-drop, and the #1881 tier mapping.
  - Verify: doc writeback at `docs/CONCEPTS/REACHOUT_AND_SCARCITY_GATE_CONTRACT.md :: Interruption threshold`.
- [ ] The adaptive-cognition / deterministic-gate boundary is stated, including that even a fast path emits a receipt and never triggers external execution without the trail.
  - Verify: doc writeback at `docs/CONCEPTS/REACHOUT_AND_SCARCITY_GATE_CONTRACT.md :: Determinism boundary`.

## How to Verify (Pre-Merge)

- `python3 scripts/docs_guard.py` and `pytest tests/architecture/test_docs_index.py -q` pass.
- Owner ratifies in PR review.
- `rg -n "interruption threshold|zero-tolerance|defer|Act / agent-review" docs/CONCEPTS/` shows the anchors.

## Out of Scope

- Runtime implementation (tasks 3–4).
- External connectors (deferred slice).
- The moment artifact + interruptibility dimension (task 1).

## Related Docs

- `docs/plans/CONTEXTUAL_RELEVANCE_ENGINE.md` (brief, §3.1, §3.3, §4)
- `docs/EMERGENT_FEATURES_MODEL.md`, `docs/CAPABILITY_CONTRACT_MODEL.md`
- `docs/CONCEPTS/RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md`
- GitHub #1881 (governance tiers)

## Related GitHub Issues

Filed as one `agent:blocked` issue (blocked on CRE-01). Becomes `agent:ready` when task 1's contracts
merge. Owner shapes the contracts in PR review.
