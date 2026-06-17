---
name: Persist Review Decisions
description: Persist memory review decisions as durable, vault-scoped governance receipts that survive restart.
task_id: DURABLE-MEMORY-01
source_anchor: docs/CONCEPTS/RUNTIME_VS_DURABLE_STATE_BOUNDARY.md :: Persistence rules
parent_capability: Durable Memory and Recall
prerequisites: []
depends_on: []
can_parallelize_with: []
---
State: Implemented. Delivery PR for issue #1904.

# PERSIST_REVIEW_DECISIONS

## Purpose

Make memory review *decisions* (promote / reject / revise) survive a process restart so a candidate
that was already reviewed is not silently re-surfaced as new. This is the foundation of the durable
memory capability.

## What This Task Does

Adds a durable, vault-scoped store for review decisions, classified as governance receipts/traces
(not durable semantic artifacts), and writes a decision record whenever a review outcome is recorded
through the existing review-queue decision path (`app/agent_memory/review_queue.py`,
`app/agent_memory/promotion.py`, and the companion decision endpoint in `app/api/routes/companion.py`).

The store follows the established runtime-state persistence pattern (vault-scoped SQLite as in
`app/orientation/leave_point_cursor.py`, or a Postgres table with a memory fallback as in
`app/services/outbox.py`), keyed by `(vault_id, channel)` from `VaultContext`. It extends or composes
with `app/receipts/promotion_receipts.py` rather than inventing a parallel receipt concept.

## Concretely

```
record_decision(candidate_id, outcome=PROMOTE, decided_by="companion-ui:reviewer")
  -> ReviewDecisionRecord{vault_id, channel, candidate_id, outcome, decided_by, decided_at, source_refs}
  -> persisted (durable, vault-scoped)

# after process restart:
get_decision(candidate_id) -> ReviewDecisionRecord (still present)
```

A pending (undecided) candidate is NOT persisted by this task — per
`RUNTIME_VS_DURABLE_STATE_BOUNDARY.md :: Persistence rules`, pending entries are discardable runtime
state.

The store must distinguish **terminal** outcomes (reject, revise, promote-and-materialized) from a
**non-terminal** promote that is still pending materialization, so downstream reconciliation
(`RECONCILE_REVIEW_QUEUE_ON_START`) suppresses only terminal outcomes. Recording the decision does
not by itself make a semantic promotion terminal — `MATERIALIZE_PROMOTED_MEMORY_TO_VAULT` marks it
terminal only once the artifact write succeeds, and writes a failed-attempt receipt otherwise.

## Why This Matters

Today review decisions live only in a process-memory singleton
(`_MEMORY_CANDIDATE_REVIEW_QUEUE` in `app/api/routes/companion.py`) and vanish on restart. From the
user's seat that is a trust break: "I already reviewed this — why is it asking again?" Persisting the
decision as a receipt is exactly what the durable-state boundary permits and closes that gap without
making the queue itself durable.

## Acceptance Criteria

- [ ] Recording a review decision writes a durable record that is present after a simulated restart.
  Verify: `tests/agent_memory/test_review_decision_store.py::test_decisions_survive_restart`
- [ ] Decision records are vault-scoped; a decision in one vault/channel is not visible in another.
  Verify: `tests/agent_memory/test_review_decision_store.py::test_decision_store_is_vault_scoped`
- [ ] Pending (undecided) candidates are not written to the durable store.
  Verify: `tests/agent_memory/test_review_decision_store.py::test_pending_candidates_are_not_persisted`
- [ ] Decision records preserve provenance (candidate source_refs, decided_by, decided_at) and are
  classified as receipts/traces, not semantic artifacts.
  Verify: `tests/agent_memory/test_review_decision_store.py::test_decision_record_preserves_provenance`

## How to Verify (Pre-Merge)

- Add the named tests; the restart test must construct a fresh store instance over the same backing
  location and assert the decision is still retrievable.
- Confirm `(vault_id, channel)` scoping via two distinct `VaultContext` values.
- Confirm no write occurs for a candidate that is still pending.
- `pytest -q tests/agent_memory/test_review_decision_store.py`

## Out of Scope

- Reconciling the in-memory queue on startup (DURABLE-MEMORY-02).
- Materializing promoted memory into the vault (DURABLE-MEMORY-03).
- Recall activation and authority-guard wiring (DURABLE-MEMORY-04).
- Making pending candidates durable.

## Related Docs

- `docs/CONCEPTS/RUNTIME_VS_DURABLE_STATE_BOUNDARY.md`
- `docs/CONCEPTS/RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md`
- `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md`
- `app/receipts/promotion_receipts.py`
- `app/orientation/leave_point_cursor.py` (vault-scoped persistence precedent)

## Related GitHub Issues

- Parent feature: Durable Memory and Recall (see PARENT_FEATURE_ISSUE.md).
- Foundation slice; no prerequisites.
