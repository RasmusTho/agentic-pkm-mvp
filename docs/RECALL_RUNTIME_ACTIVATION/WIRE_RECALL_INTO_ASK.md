---
name: Wire Recall Into ASK
description: An ASK-graph node that activates guarded recall for the retrieved promoted memories and threads the recalled awareness to the answer step.
task_id: RECALL_RUNTIME-02
source_anchor: docs/RECALL_RUNTIME_ACTIVATION/README.md :: Capability Boundary
parent_capability: Recall Runtime Activation
prerequisites: [RECALL_RUNTIME-01]
depends_on: [RETRIEVE_RELEVANT_PROMOTED_MEMORY.md]
can_parallelize_with: []
---

# Wire Recall Into ASK

## Purpose

This is the slice that closes the dormancy: it makes `activate_guarded_recall` actually run during an
ASK reasoning pass. Today `app/agents/ask/graph.py` is retrieve → rerank → answer and never imports
`agent_memory`.

## What This Task Does

- Adds a `recall` node to the ASK graph (between `rerank` and `answer`) that, for each candidate from
  `RETRIEVE_RELEVANT_PROMOTED_MEMORY`, calls
  `app/agent_memory/recall_activation.py::activate_guarded_recall` with a read-only use-right
  (`ACTIVATABLE`/answer, never action-authorizing), an activation reason, and a `why_now`.
- Threads the resulting `GuardedRecall.explanation` into `AgentState` so the `answer` node can use it
  as read-only awareness alongside retrieval hits.
- Emits the recall receipt that `activate_guarded_recall` already produces; records the recall on the
  reasoning trace.
- Is governed by construction: read-only; no memory→mutation path; honors the authority guard
  (`may_write` is never used to write); degrades cleanly to "no recall" when retrieval is empty.

## Concretely

```
ASK graph: START -> retrieve -> rerank -> recall -> answer -> END
recall node: candidates = retrieve_relevant_promoted(state.query, k)
             for c in candidates: gr = activate_guarded_recall(c.promoted, use_right=ACTIVATABLE, ...)
             state.recalled = [gr.explanation ...]   # read-only awareness, with receipts
```

## Why This Matters

This is the difference between "recall exists in the codebase" and "recall happens when the system
reasons." It is the AC the architecture-verification fence asserts.

## Acceptance Criteria

- [ ] A real ASK run with relevant promoted memory invokes `activate_guarded_recall` and threads the
  recalled explanation into the answer context, with a recall receipt.
  - Verify: `tests/agent_memory/test_recall_in_ask.py::test_ask_run_invokes_guarded_recall_with_receipt`
- [ ] Recall is read-only: no mutation occurs and the authority guard's `may_write` is never exercised.
  - Verify: `tests/agent_memory/test_recall_in_ask.py::test_recall_is_read_only`
- [ ] The anti-dormancy guard passes (a runtime path imports/invokes the recall path).
  - Verify: `tests/agent_memory/test_arch_recall_wiring.py::test_guarded_recall_is_invoked_by_an_agent` (existing xfail flips to pass)
- [ ] An ASK run with no relevant promoted memory still answers normally (recall degrades to none).
  - Verify: `tests/agent_memory/test_recall_in_ask.py::test_no_recall_when_no_relevant_memory`

## How to Verify (Pre-Merge)

- `pytest -q tests/agent_memory/test_recall_in_ask.py tests/agent_memory/test_arch_recall_wiring.py`
- `ruff check app tests` and `mypy app`

## Out of Scope

- The user-facing surfacing/attribution treatment (that is `SURFACE_RECALL_IN_ANSWER`).
- PanelAgent/Planner recall (later slice once ASK is proven).

## Related Docs

- `docs/RECALL_RUNTIME_ACTIVATION/README.md`
- `app/agents/ask/graph.py`, `app/agents/ask/state.py`, `app/agent_memory/recall_activation.py`
- `tests/agent_memory/test_arch_recall_wiring.py`

## Related GitHub Issues

One issue: `[Recall Runtime] wire-recall-into-ask: activate guarded recall in the ASK graph`. Blocked
on RECALL_RUNTIME-01. Implements RECALL_RUNTIME_ACTIVATION/WIRE_RECALL_INTO_ASK.
