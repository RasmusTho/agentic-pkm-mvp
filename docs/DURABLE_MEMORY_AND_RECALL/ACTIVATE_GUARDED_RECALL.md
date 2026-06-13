---
name: Activate Guarded Recall
description: Wire the existing authority guard and recall explanation into a recall-activation consumer that emits a recall receipt; activation stays runtime-only.
task_id: DURABLE-MEMORY-04
source_anchor: docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md :: Authority rules
parent_capability: Durable Memory and Recall
prerequisites: [DURABLE-MEMORY-03]
depends_on: [MATERIALIZE_PROMOTED_MEMORY_TO_VAULT.md]
can_parallelize_with: []
---
State: Implemented. Delivery PR for issue #1907.

# ACTIVATE_GUARDED_RECALL

## Purpose

Give durable memory a consumer: a recall-activation path that brings promoted memory into reasoning /
answer / orientation context, running the existing authority guard and recall explanation, and
emitting a recall receipt. This closes the audit finding that
`app/agent_memory/authority_guard.py` and `app/agent_memory/recall_explanation.py` have zero
production call sites — they are dormant only because no consumer exists.

## What This Task Does

Introduces a single recall-activation entry point that, for a candidate recall:

1. calls `evaluate_memory_authority()` (`app/agent_memory/authority_guard.py`) to determine the
   authority level (suggestion-only / instructional / action-authorizing) and whether mutation is
   allowed;
2. builds a `RecallExplanation` (`app/agent_memory/recall_explanation.py`) describing why the memory
   was recalled, its provenance, and its authority limits;
3. emits a recall receipt recording what was recalled for the task;
4. returns the guarded result to the caller (answer/orientation/proposal surface).

Per `RUNTIME_VS_DURABLE_STATE_BOUNDARY.md :: Leakage prevention`, the activation/recall state is
runtime-only and is captured in the recall receipt for audit — it is **not** stamped as a durable
property of the recalled artifact, and recall never escalates to mutation authority on its own.

## Concretely

```
recall_for_context(memory_ref, intended_use="answer")
  -> decision = evaluate_memory_authority(memory)        # suggestion-only / etc.
  -> explanation = build_recall_explanation(memory, why_now=...)
  -> emit recall receipt
  -> return GuardedRecall{may_answer, may_propose, may_write=False unless decision allows, explanation}

# unreviewed/inferred/contradicted memory -> suggestion-only, may_write stays False
```

## Why This Matters

Without a guarded consumer, durable memory is inert and the authority guard is untested in
production. With it, recall becomes explainable and bounded: the system can use memory to answer or
propose, but unreviewed memory cannot become hidden authority — the exact rule the agent-memory
contract requires.

## Acceptance Criteria

- [ ] The recall consumer runs `evaluate_memory_authority` and emits a recall receipt for each recall.
  Verify: `tests/agent_memory/test_guarded_recall_activation.py::test_recall_runs_authority_guard_and_emits_receipt`
- [ ] Unreviewed or inferred memory recalled into context cannot authorize writeback (may_write False).
  Verify: `tests/agent_memory/test_guarded_recall_activation.py::test_unreviewed_recall_cannot_authorize_writeback`
- [ ] Activation state is recorded only in the recall receipt and is not persisted as a durable
  property of the artifact.
  Verify: `tests/agent_memory/test_guarded_recall_activation.py::test_activation_not_persisted_as_authority`

## How to Verify (Pre-Merge)

- Add the named tests; assert the guard is invoked (not bypassed) and a receipt is produced.
- Assert the unreviewed/inferred path yields suggestion-only authority.
- Assert no durable write of activation state to the artifact occurs.
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/agent_memory/test_guarded_recall_activation.py`

## Out of Scope

- The reasoning/answer surface's own logic (this task provides the guarded recall seam it calls).
- Companion UI surfacing of recall provenance (DURABLE-MEMORY-05).
- Materialization (DURABLE-MEMORY-03) and decision persistence (DURABLE-MEMORY-01).

## Related Docs

- `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md`
- `docs/CONCEPTS/RUNTIME_VS_DURABLE_STATE_BOUNDARY.md`
- `docs/CONCEPTS/RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md`
- `app/agent_memory/authority_guard.py`, `app/agent_memory/recall_explanation.py`

## Related GitHub Issues

- Parent feature: Durable Memory and Recall (see PARENT_FEATURE_ISSUE.md).
- Blocked on DURABLE-MEMORY-03 (MATERIALIZE_PROMOTED_MEMORY_TO_VAULT).
