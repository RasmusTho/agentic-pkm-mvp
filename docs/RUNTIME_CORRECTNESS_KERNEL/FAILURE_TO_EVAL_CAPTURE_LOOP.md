---
name: Failure to Eval Capture Loop
description: Draft every schema_violation dead-letter and every UNKNOWN classification as an eval-case candidate with full provenance into a human review queue; human confirmation promotes to the golden sets
task_id: KERNEL-15
source_anchor: "docs/audits/SYSTEM_REDESIGN_CORRECTNESS_KERNEL_2026-07-02.md :: §5.4"
parent_capability: RUNTIME_CORRECTNESS_KERNEL
prerequisites: [KERNEL-12, KERNEL-13]
depends_on: [DEAD_LETTER_HEALTH_SIGNAL.md, INTENT_CLASSIFICATION_GOLDEN_SET.md]
can_parallelize_with: []
---

# Failure to Eval Capture Loop

## Purpose

Eval ground truth in a probabilistic system is accumulated **adjudicated history**, not a-priori
labels (audit **§5.4**, RQ4). Today dead-letters and misclassifications vanish into logs
(`outbox.event.dead_lettered` → JSONL; `intent_classifier` `_defaulted` → nothing durable). This task
closes the loop: every failure becomes a candidate regression test after human adjudication.

## What This Task Does

- On every dead-letter with reason `schema_violation` (KERNEL-08/12 emit these), draft an eval-case
  candidate. On every `UNKNOWN` classification (KERNEL-07 surfaces these), draft a
  `classification_case.v1` candidate.
- The draft is a **companion-note-class artifact** in the vault system folder, following
  `docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md`: system-owned location resolved via
  `get_vault_system_dir_rel()` (the layout-aware system folder, e.g. `⚙️ System/`), not the human
  writing surface, not the DB. This honors the storage-substrate rule — human-reviewable, long-lived
  material belongs in notes.
- Each draft carries **full provenance**: `trace_id`, source event (topic + original event id),
  and a payload snapshot. Enough for a reviewer to reconstruct the failure without log archaeology.
- Drafts land in a **human review queue** (mirror the existing pattern:
  `app/agent_memory/review_queue.py` + `materialize_promoted_memory` in
  `app/agent_memory/materialization.py`, which requires a promoted entry before it writes).
- Drafting is **WriteGuard-gated** like all vault writes: call
  `app/write_guard.py::WriteGuard.assert_writes_allowed(action)` before the vault write, matching
  `materialize_promoted_memory`'s use of `DEFAULT_WRITE_GUARD`.
- **No auto-promotion.** Human confirmation promotes a draft into the golden datasets
  (`classification_case.v1` for UNKNOWN cases from KERNEL-13; a topic-schema fixture for
  `schema_violation` cases). Adjudication is the ground-truth step.

## Concretely

```bash
pytest -q tests/eval/test_failure_capture_loop.py
```

The tests inject a `schema_violation` dead-letter and an `UNKNOWN` classification and assert a draft
candidate appears with provenance, gated by WriteGuard, and is NOT auto-promoted.

## Why This Matters

This is the only sustainable answer to RQ4: ground truth is curated history. It converts the two
worst silent failures (dead-lettered events, misrouted intents) into permanent regression coverage,
feeding KERNEL-13's golden set from real production failures instead of hand-authored cases alone.

## Acceptance Criteria

- [ ] A `schema_violation` dead-letter produces a draft eval-case companion-note artifact in the
      system folder with full provenance (trace_id, source event, payload snapshot).
      Verify: `tests/eval/test_failure_capture_loop.py::test_dead_letter_drafts_case_with_provenance`
- [ ] An `UNKNOWN` classification produces a draft `classification_case.v1` candidate with provenance.
      Verify: `tests/eval/test_failure_capture_loop.py::test_unknown_drafts_classification_case`
- [ ] Draft writes go through WriteGuard; a blocked write-state prevents the draft, asserted through
      the production write path.
      Verify: `tests/eval/test_failure_capture_loop.py::test_draft_is_write_guard_gated` — asserts `WriteGuard.assert_writes_allowed` is invoked from the draft-write entrypoint.
- [ ] No auto-promotion: a draft is not in the golden dataset until a recorded human decision
      promotes it.
      Verify: `tests/eval/test_failure_capture_loop.py::test_no_auto_promotion`

## How to Verify (Pre-Merge)

1. `pytest -q tests/eval/test_failure_capture_loop.py`.
2. Full `pytest -q -m "not pg"` + `RUN_INTEGRATED_RUNTIME_UAT=1 pytest -q -m uat_integrated_runtime`
   (vault-write path).
3. `ruff check app tests`.

## Parent-closure handoff (final child)

This is the last child of the capability. On merge, drive the parent-issue closure:
- Verify every `Verify:` target in the README "Capability acceptance criteria" is green on `main`.
- Trigger the owner-doc promotion PR (`docs/EVENTS.md`, `docs/DB_SCHEMA.md`, `docs/EMBEDDINGS.md`,
  `docs/HEALTH.md`, `docs/ARCHITECTURE.md`) reflecting shipped reality, per the README checklist and
  `post-merge-owner-doc`.

## Out of Scope

- The review UI itself (memory ledger/review UI stays W7/W8; reuse the existing queue surface).
- Operator-correction capture (§5.4 also names it; this task covers dead-letters + UNKNOWNs only).
- Changing companion-note eligibility policy.

## Related Docs

- `docs/audits/SYSTEM_REDESIGN_CORRECTNESS_KERNEL_2026-07-02.md :: §5.4`
- `docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md`, `app/write_guard.py`
- `app/agent_memory/review_queue.py`, `app/agent_memory/materialization.py` (queue + promote pattern)

## Related GitHub Issues

One bounded issue (the final child; carries parent closure). TCD hint: Sonnet / high effort
(cross-surface loop: worker dead-letter path + classifier UNKNOWN path + vault companion-note write +
review queue). Escalate if the two failure sources need materially different draft surfaces.
