---
name: Retrieve Relevant Promoted Memory
description: A reader plus relevance selector that returns the promoted memories relevant to a query, as PromotedMemory objects.
task_id: RECALL_RUNTIME-01
source_anchor: docs/RECALL_RUNTIME_ACTIVATION/README.md :: Capability Boundary
parent_capability: Recall Runtime Activation
prerequisites: []
depends_on: []
can_parallelize_with: []
---

# Retrieve Relevant Promoted Memory

## Purpose

Recall cannot fire until something can answer "which promoted memories are relevant to *this* query?".
Today no runtime reader returns promoted memories for recall (only the unrelated
`app/fitness/relations._load_promoted`). This task adds that reader + relevance selector.

## What This Task Does

- Reads the durable promoted-memory set (the materialized promoted memories produced by
  `app/agent_memory/materialization.py` / the promotion flow) back into `PromotedMemory` objects.
- Selects the *relevant* subset for a query with a deterministic, explainable ranking (e.g. reuse the
  existing retrieval/scoring surface in `app/retrieval/capability.py` or a bounded equivalent), capped
  to a small top-k — scarcity is a feature, recall must not flood context.
- Returns an ordered list of `(PromotedMemory, relevance_reason)` with no side effects (pure read).

## Concretely

```python
from app.agent_memory.recall_retrieval import retrieve_relevant_promoted

results = retrieve_relevant_promoted(query="how did we decide the watcher default?", k=3)
# -> [RecallCandidate(promoted=PromotedMemory(...), score=..., reason="...")] , most-relevant first
```

Empty vault / no promoted memory → returns `[]` (never raises).

## Why This Matters

If retrieval returns everything (or nothing), recall is either noise or dead. The selectivity here is
what makes recall a scarce, trustworthy signal rather than a context dump.

## Acceptance Criteria

- [ ] A reader returns promoted memories as `PromotedMemory` objects from the durable set.
  - Verify: `tests/agent_memory/test_recall_retrieval.py::test_reads_promoted_memory_from_durable_set`
- [ ] Selection is relevance-ranked and top-k capped; an empty/unrelated query returns few or none.
  - Verify: `tests/agent_memory/test_recall_retrieval.py::test_selects_relevant_topk_and_caps`
- [ ] The reader is pure (no writes, no mutation) and never raises on an empty/missing memory set.
  - Verify: `tests/agent_memory/test_recall_retrieval.py::test_pure_and_safe_on_empty`

## How to Verify (Pre-Merge)

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/agent_memory/test_recall_retrieval.py`
- `ruff check app tests` and `mypy app`

## Out of Scope

- Calling `activate_guarded_recall` (that is `WIRE_RECALL_INTO_ASK`).
- Any ASK-graph change; any surfacing.
- Vector-DB infrastructure — reuse the existing retrieval/scoring surface or a bounded deterministic ranker.

## Related Docs

- `docs/RECALL_RUNTIME_ACTIVATION/README.md`
- `docs/DURABLE_MEMORY_AND_RECALL/README.md`
- `app/agent_memory/promotion.py`, `app/agent_memory/materialization.py`, `app/retrieval/capability.py`

## Related GitHub Issues

One issue: `[Recall Runtime] retrieve-relevant-promoted-memory: a selective reader for recall`. Ready
on creation (no upstream dependency). Implements RECALL_RUNTIME_ACTIVATION/RETRIEVE_RELEVANT_PROMOTED_MEMORY.
