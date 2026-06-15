---
name: Surface Recall In Answer
description: Decide and implement how recalled memory is shown and attributed when it participates in an ASK answer.
task_id: RECALL_RUNTIME-03
source_anchor: docs/RECALL_RUNTIME_ACTIVATION/README.md :: Capability Boundary
parent_capability: Recall Runtime Activation
prerequisites: [RECALL_RUNTIME-02]
depends_on: [WIRE_RECALL_INTO_ASK.md]
can_parallelize_with: []
---

# Surface Recall In Answer

## Purpose

Once recall participates in reasoning (RECALL_RUNTIME-02), the human needs to know *that it did* and
*from which memory* — recall that silently shapes answers is untrustworthy. This task decides the
surfacing treatment and implements it.

## What This Task Does

- Implements the owner-ratified surfacing treatment for recalled memory in an ASK answer. Candidate
  treatments (the owner picks one before build):
  - **A — attribution footer:** the answer carries a "recalled from: <memory>" note with the recall
    explanation/receipt id, always shown when recall fired.
  - **B — provenance field only:** recall stays out of the answer prose but is exposed as a structured
    `recalled: [...]` field on the response for the UI to render.
  - **C — confidence-gated inline:** recall is woven into the answer only above a relevance threshold,
    with a provenance field always present.
- Surfaces the recall explanation (already produced by `activate_guarded_recall`) using the
  human-readable `recall_explanation` output; never invents attribution.

## Concretely

The ASK response exposes recalled memory per the chosen treatment, e.g. a `recalled` list of
`{memory_id, why_now, receipt_id}` and/or an answer-attached attribution line. The Companion UI can
then render it (UI rendering itself may be a thin follow-up).

## Why This Matters

Unattributed recall is a trust and governance hazard: the human cannot tell why the system said what
it said. Attribution is what keeps recall an honest, auditable awareness signal.

## Acceptance Criteria

- [ ] The surfacing treatment is owner-ratified and recorded before build.
  - Verify: decision recorded in this file's `## Decision` section and on issue #1959 (or its child)
- [ ] When recall fires, the ASK response exposes the recalled memory per the chosen treatment, keyed
  to its receipt; when recall does not fire, no attribution is shown.
  - Verify: `tests/agent_memory/test_recall_surfacing.py::test_response_surfaces_recall_with_receipt`
- [ ] Owner-doc promotion: the recall runtime is recorded in current-state docs and a runtime-map row.
  - Verify: doc writeback at `docs/STATUS.md` and `docs/HUMAN_FLOW_TO_RUNTIME_MAP.md :: Mapping`

## Decision

**Treatment A — attribution footer** (owner-ratified 2026-06-15; #1972). When guarded recall fires in
the ASK path, the answer carries a short footer — `Recalled from: <memory> · receipt <id>` — below the
answer body, keyed to the recall receipt (`RecallExplanation.receipt_reference`). It is always
human-visible, source-linked, and lives **outside** the answer prose so the agent's voice is
preserved. The same provenance is also exposed in structured form on the ASK response
(`recalled: [{memory_id, title, why_now, receipt_id}]`) for the UI. No footer is shown when recall did
not fire, and attribution is never invented. Treatments **B** (structured provenance field only) and
**C** (confidence-gated inline + field) were considered and not chosen — B leaves a human reading the
answer with no visible attribution; C injects into the answer prose and adds a confidence gate.

Implementation: `app/agent_memory/recall_explanation.py::render_recall_footer`, applied in
`app/agents/ask/graph.py::_answer_node`; structured field in `app/api/routes/ask.py::AskResponse`.

## How to Verify (Pre-Merge)

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/agent_memory/test_recall_surfacing.py`
- `ruff check app tests`

## Out of Scope

- Deep Companion UI visual design beyond exposing the recall provenance (thin follow-up if needed).
- Non-ASK agents.

## Related Docs

- `docs/RECALL_RUNTIME_ACTIVATION/README.md`
- `app/agent_memory/recall_explanation.py`
- `docs/STATUS.md`, `docs/HUMAN_FLOW_TO_RUNTIME_MAP.md`

## Related GitHub Issues

One issue: `[Recall Runtime] surface-recall-in-answer: attribute recalled memory in ASK answers`.
`agent:needs-human` until the surfacing treatment (A/B/C) is ratified. Carries the parent-closure +
owner-doc promotion handoff. Implements RECALL_RUNTIME_ACTIVATION/SURFACE_RECALL_IN_ANSWER.
