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

On a promote-to-semantic decision, the persisted human review authorizes MEM to request a GOV
PolicyDecision and DecisionToken bound to the reviewer, materialization action, write class, and
exact HKA target. The production authority path is `human review → GOV token → WriteGuard → HKA
create-once write and mutation receipt → promotion receipt → GOV AuthorityReceipt → terminal
decision`. The materialized note:

- is written through `app/write_guard.py` (a vault-internal write, consistent with the owner's
  "all vault-internal writes pass WriteGuard" rule) and the companion-note / knowledge write path;
- carries provenance frontmatter (source_refs, generated_by, promoted-from candidate id, decided_by)
  plus the candidate's explicit `scope_id` binding;
- is labeled as agent-promoted material, distinct from and never overriding human-authored notes;
- has a corresponding promotion receipt (`app/receipts/promotion_receipts.py`) as transition
  evidence, while HKA's mutation receipt remains the state-owner fact and GOV's distinct
  AuthorityReceipt remains the accountability record.

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

**Scope producer invariant.** A semantic candidate must carry an explicit `scope_id` before
materialization. The materializer refuses a missing or invalid binding before any artifact or
transition receipt is written. It serializes the persisted `PROMOTE` decision from nonterminal state
through a durable `materializing` reservation, note and receipt creation, and the terminal
transition. The reservation binds the immutable scope, candidate digest, and original reviewer
authority; once it exists, reject/revise cannot replace the decision after an indeterminate external
write. The candidate-bound note identity is checked before selecting any new target, while HKA's
create-once operation protects the exact chosen path. This allows one successful materializer and
prevents a revoked, changed, repeated, or competing materializer from writing. The persisted binding is
written to both note and receipt; legacy unscoped artifacts remain unchanged. Bound recall denies
unscoped artifacts fail closed and requires scope, candidate, artifact UUID, and selected vault to
match the applied receipt; unbound recall retains its existing behavior.
The selected vault ID is trusted only when its selected path equals the root used for recall, and
receipt top-level artifact identity must agree with its linkage fields. If a reject or revise races
with a durable `materializing` reservation, the store refuses it and the API restores the original
pending queue entry (including removal of any speculative revision) before returning a conflict.

Late failures are resumed idempotently. The materialization identity is stable per
vault/channel/candidate. A retry validates and reuses an existing applied receipt plus its
candidate-bound note and governed mutation facts. Before HKA runs, the owned receipt-source
continuity marker durably reserves the exact candidate/materialization target. The reservation is
cleared only after the applied promotion receipt is durably appended. An interrupted attempt whose
reservation remains therefore fails closed for explicit remediation independently of mutable note
frontmatter; it never selects a suffixed target or invokes HKA a second time. An unreceipted
candidate-bound note likewise cannot be treated as durable authority. Conflicting or multiple
recovery artifacts fail closed instead of producing another note or receipt.

The owned receipt source carries a continuity marker. Upgrade initialization backfills a missing
marker only for legacy history that has no persisted source binding and whose complete owned receipt
chains are present. A legacy marker version without an exact-target reservation map may be upgraded
only during initialization after every required owned receipt chain is complete; the active marker
version requires that map, so field loss fails closed. Once a source binding is persisted, a missing
or empty marker is continuity loss and cannot be backfilled automatically. A nonterminal decision
cannot retain that binding while omitting or clearing its `materializing` reservation; this
inconsistent state is rejected before receipt-source initialization, GOV, or HKA. If the source is
absent while the review store already
contains an in-progress materialization, a terminal semantic promotion, or legacy promotion history
whose memory type is unavailable, materialization refuses to create a fresh empty history and
requires explicit remediation. A known non-semantic terminal promotion does not imply materialization
receipt history. Source loss after the marker exists likewise fails closed.
Structured promotion and AuthorityReceipt envelopes must also carry one unambiguous event identity:
JSONL `event`/`event_type`/`topic` aliases and the authoritative DB row topic may not disagree. A
conflict or malformed nested structured payload makes that source unavailable before HKA and during
terminal reconciliation.

## Concretely

```
promote(candidate, target_class=SEMANTIC, decided_by="companion-ui:reviewer")
  -> GOV PolicyDecision + DecisionToken bound to reviewer/action/write class/exact target
  -> DEFAULT_WRITE_GUARD.assert_writes_allowed("memory.materialize")
  -> HKA create-once vault note + mutation receipt
  -> PromotionReceipt{vault_id, channel, artifact_path, candidate_id, decided_by, decided_at,
                      policy_decision, decision_token, state_owner_receipt}
  -> GOV AuthorityReceipt{decision_token_id, source_receipt_ref, state_owner=HKA}
  -> terminal promotion decision

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
- [ ] Semantic materialization refuses a missing or invalid candidate scope before writing, while
  successful materialization persists the immutable decision scope into the artifact and receipt.
  Verify: `tests/agent_memory/test_memory_materialization.py::test_semantic_materialization_requires_scope_before_write`
  Verify: `tests/agent_memory/test_materialization_live_path.py::test_accept_materializes_and_marks_terminal`
- [ ] Materialization requires a current nonterminal `PROMOTE` for the same persisted scope and
  permits only one successful materializer.
  Verify: `tests/agent_memory/test_memory_materialization.py::test_materialization_refuses_intervening_same_scope_rejection`
  Verify: `tests/agent_memory/test_memory_materialization.py::test_duplicate_materializer_refuses_after_terminal_success`
  Verify: `tests/agent_memory/test_memory_materialization.py::test_retry_reconciles_applied_receipt_after_late_query_failure`
  Verify: `tests/agent_memory/test_memory_materialization.py::test_retry_refuses_candidate_note_without_governed_receipt_after_append_failure`
- [ ] Non-semantic promotions (episodic/working/preference) do not materialize a vault artifact.
  Verify: `tests/agent_memory/test_memory_materialization.py::test_non_semantic_promotion_does_not_materialize`

## How to Verify (Pre-Merge)

- Add the named tests using a temp vault and a fake/stub WriteGuard state.
- Assert the receipt is written and references the artifact path.
- Assert blocked-state path raises and leaves the vault unchanged.
- Assert human-authored content is never overwritten (collision → new agent-promoted artifact or
  governed-merge proposal, per the companion-note contract).
- `pytest -q tests/agent_memory/test_memory_materialization.py`

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
