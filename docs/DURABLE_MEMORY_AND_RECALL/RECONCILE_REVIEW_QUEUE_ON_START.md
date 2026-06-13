---
name: Reconcile Review Queue On Start
description: On startup, reconcile the in-memory review queue against persisted decisions so decided candidates are not re-surfaced.
task_id: DURABLE-MEMORY-02
source_anchor: docs/CONCEPTS/RUNTIME_VS_DURABLE_STATE_BOUNDARY.md :: Discardability semantics
parent_capability: Durable Memory and Recall
prerequisites: [DURABLE-MEMORY-01]
depends_on: [PERSIST_REVIEW_DECISIONS.md]
can_parallelize_with: []
---
State: Specified. Not yet delivered. Blocked on DURABLE-MEMORY-01.

# RECONCILE_REVIEW_QUEUE_ON_START

## Purpose

Ensure that when the review queue is rebuilt (process start, or candidates re-observed), a candidate
that already has a persisted decision is not presented again as a new, undecided item.

## What This Task Does

On queue construction / candidate intake, consults the durable decision store from
DURABLE-MEMORY-01 and filters or annotates candidates whose decision is **terminal**: a rejected,
revised, or promoted-**and-materialized** candidate is excluded from the pending set (or shown with
its decided posture), rather than appearing as fresh pending work.

A promotion that has not yet materialized its vault artifact (blocked or failed write — see
`MATERIALIZE_PROMOTED_MEMORY_TO_VAULT` "Terminal-on-success invariant") is **non-terminal** and must
NOT be suppressed: such a candidate stays actionable so the materialization is re-attempted. This is
the safeguard against a promoted candidate silently disappearing from review with no artifact.

The pending queue itself remains runtime state and is still rebuilt from observation — this task does
not persist the queue. It only reconciles the rebuilt queue against the durable decision record.

## Concretely

```
# decision store: candidate_X -> REJECT (terminal); candidate_Z -> PROMOTE pending-materialization
rebuild_review_queue(observed=[candidate_X, candidate_Y, candidate_Z])
  -> pending = [candidate_Y, candidate_Z]   # X (terminal) suppressed; Z (unmaterialized) stays actionable
  -> (candidate_X retrievable as already-decided via the decision store)
```

## Why This Matters

Persisting decisions (DURABLE-MEMORY-01) is only half the trust fix. If the rebuilt queue ignores
those decisions, the user still sees previously-handled candidates as new. Reconciliation is what
makes "I already reviewed this" actually hold across restarts, while respecting the boundary rule
that the pending queue is discardable runtime state.

## Acceptance Criteria

- [ ] A candidate with a terminal decision is not re-surfaced as a new pending item after restart.
  Verify: `tests/agent_memory/test_review_queue_reconciliation.py::test_decided_candidates_not_resurfaced`
- [ ] A candidate with no persisted decision still appears as pending.
  Verify: `tests/agent_memory/test_review_queue_reconciliation.py::test_undecided_candidates_still_pending`
- [ ] A promoted-but-not-yet-materialized candidate (blocked/failed write) is NOT suppressed; it
  stays actionable so materialization is re-attempted.
  Verify: `tests/agent_memory/test_review_queue_reconciliation.py::test_promoted_but_unmaterialized_candidate_stays_actionable`
- [ ] Reconciliation is vault-scoped: a decision in another vault/channel does not suppress a
  candidate in the active one.
  Verify: `tests/agent_memory/test_review_queue_reconciliation.py::test_reconciliation_is_vault_scoped`

## How to Verify (Pre-Merge)

- Add the named tests; seed the decision store, rebuild the queue, assert the pending set.
- Confirm the pending queue is still rebuilt from observation (not loaded from a durable queue store).
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/agent_memory/test_review_queue_reconciliation.py`

## Out of Scope

- The durable decision store itself (DURABLE-MEMORY-01).
- Materialization to vault (DURABLE-MEMORY-03) and recall (DURABLE-MEMORY-04).
- Persisting pending candidates.

## Related Docs

- `docs/CONCEPTS/RUNTIME_VS_DURABLE_STATE_BOUNDARY.md`
- `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md`
- `app/agent_memory/review_queue.py`
- `app/api/routes/companion.py` (review-queue endpoints)

## Related GitHub Issues

- Parent feature: Durable Memory and Recall (see PARENT_FEATURE_ISSUE.md).
- Blocked on DURABLE-MEMORY-01 (PERSIST_REVIEW_DECISIONS).
