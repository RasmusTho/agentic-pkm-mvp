---
name: Materialize Promoted Memory To Vault
description: When memory is promoted to semantic knowledge, materialize it as a human-reviewable vault artifact through the governed write path.
task_id: DURABLE-MEMORY-03
source_anchor: docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md :: Review and promotion rules
parent_capability: Durable Memory and Recall
prerequisites: [DURABLE-MEMORY-01]
depends_on: [PERSIST_REVIEW_DECISIONS.md]
can_parallelize_with: []
---
State: Implemented. Delivery PR for issue #1906.

# MATERIALIZE_PROMOTED_MEMORY_TO_VAULT

## Purpose

When a candidate is promoted into durable *semantic* memory, materialize it as a human-reviewable
vault artifact — the writing surface — so promoted memory converges into the human-authored surface
rather than living only as a hidden machine record. This implements the owner's 2026-06-13 decision.

## What This Task Does

On a promote-to-semantic decision, builds a governed write-proposal and routes it through the
existing authority path: `proposal → WriteGuard → receipt → vault artifact`. The materialized note:

- is written through `app/write_guard.py` (a vault-internal write, consistent with the owner's
  "all vault-internal writes pass WriteGuard" rule) and the companion-note / knowledge write path;
- carries provenance frontmatter (source_refs, generated_by, promoted-from candidate id, decided_by);
- is labeled as agent-promoted material, distinct from and never overriding human-authored notes;
- has a corresponding promotion receipt (`app/receipts/promotion_receipts.py`) — the receipt is the
  accountability record, the note is the durable semantic surface.

Episodic/working/preference promotions that the contract does NOT treat as semantic knowledge are
out of scope for materialization; only semantic promotion materializes a vault artifact.

**Terminal-on-success invariant.** A promote-to-semantic decision becomes *terminal* — the state
that suppresses the candidate from the pending review set in `RECONCILE_REVIEW_QUEUE_ON_START` —
only once the vault artifact is successfully materialized. If materialization is blocked
(safe_mode/unhealthy) or otherwise fails, the system records a **failed-attempt receipt** and the
promotion stays **actionable**: the candidate remains in (or returns to) the pending/retry set and
is re-attempted when writes are allowed again. A promoted candidate must never be suppressed from
review while no artifact exists. (Non-semantic promotions need no artifact and are terminal on
decision.)

## Concretely

```
promote(candidate, target_class=SEMANTIC, decided_by="companion-ui:reviewer")
  -> governed write-proposal
  -> DEFAULT_WRITE_GUARD.assert_writes_allowed("memory.materialize")
  -> write vault note (provenance frontmatter; agent-promoted label)
  -> PromotionReceipt{vault_id, channel, artifact_path, candidate_id, decided_by, decided_at}

# blocked path:
# health state == safe_mode/unhealthy
#   -> WritesBlockedError, no note written
#   -> failed-attempt receipt recorded; promotion stays ACTIONABLE (non-terminal)
#   -> candidate is NOT suppressed from review; re-attempted when writes are allowed
#   -> a terminal promoted decision is recorded only after the artifact write succeeds
```

## Why This Matters

This is the step that gives promoted memory a durable, intelligible home the user can read, edit, and
trust — without letting the runtime silently write authority. Routing through WriteGuard + receipt
keeps it inside `RUNTIME_VS_DURABLE_STATE_BOUNDARY.md` ("runtime value → proposal → governance →
receipt → durable artifact, never silent persistence") and the writing-surface contract.

## Acceptance Criteria

- [ ] Semantic promotion materializes a vault artifact only after `assert_writes_allowed` passes, and
  records a promotion receipt.
  Verify: `tests/agent_memory/test_memory_materialization.py::test_promotion_materializes_via_writeguard_with_receipt`
- [ ] When writes are blocked (safe_mode/unhealthy), no vault note is written and the attempt raises.
  Verify: `tests/agent_memory/test_memory_materialization.py::test_blocked_writes_prevent_materialization`
- [ ] Blocked/failed materialization records a failed-attempt receipt and keeps the promotion
  actionable (the candidate is NOT marked terminal and NOT suppressed from review); a terminal
  promoted decision is recorded only after the artifact write succeeds.
  Verify: `tests/agent_memory/test_memory_materialization.py::test_blocked_materialization_keeps_promotion_actionable`
- [ ] The materialized note carries provenance and an agent-promoted label and does not overwrite an
  existing human-authored note.
  Verify: `tests/agent_memory/test_memory_materialization.py::test_materialized_note_preserves_provenance_and_human_authorship`
- [ ] Non-semantic promotions (episodic/working/preference) do not materialize a vault artifact.
  Verify: `tests/agent_memory/test_memory_materialization.py::test_non_semantic_promotion_does_not_materialize`

## How to Verify (Pre-Merge)

- Add the named tests using a temp vault and a fake/stub WriteGuard state.
- Assert the receipt is written and references the artifact path.
- Assert blocked-state path raises and leaves the vault unchanged.
- Assert human-authored content is never overwritten (collision → new agent-promoted artifact or
  governed-merge proposal, per the companion-note contract).
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/agent_memory/test_memory_materialization.py`

## Out of Scope

- Recall activation and authority-guard wiring (DURABLE-MEMORY-04).
- Companion UI surfacing (DURABLE-MEMORY-05).
- Decision persistence (DURABLE-MEMORY-01) and queue reconciliation (DURABLE-MEMORY-02).
- Changing the companion-note contract or the writing-surface contract (cite, do not modify).

## Related Docs

- `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md`
- `docs/CONCEPTS/RUNTIME_VS_DURABLE_STATE_BOUNDARY.md`
- `docs/SEPARATING_PERSISTENCE_SURFACES/DEFINE_WRITING_SURFACE_CONTRACT.md`
- `docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md`
- `app/write_guard.py`, `app/receipts/promotion_receipts.py`

## Related GitHub Issues

- Parent feature: Durable Memory and Recall (see PARENT_FEATURE_ISSUE.md).
- Blocked on DURABLE-MEMORY-01. May split into proposal-build and write-path issues if large.
