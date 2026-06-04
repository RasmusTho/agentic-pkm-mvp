---
name: Carry Linkage Through Write Proposals
description: Carry bundle linkage through the governed write-proposal path without bypassing WriteGuard.
task_id: CONTEXT-BUNDLES-RUNTIME-04
source_anchor: docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md :: Relation to writeback and write guards
parent_capability: Context Bundles — Production Runtime Integration
prerequisites: [CONTEXT-BUNDLES-RUNTIME-02]
depends_on: [EMIT_FROM_REAL_RETRIEVAL.md]
can_parallelize_with: [CONSUME_IN_ORIENTATION_AND_RESURFACING.md]
github_issue: "https://github.com/RasmusTho/agentic-pkm-mvp/issues/1564"
---

# CARRY_LINKAGE_THROUGH_WRITE_PROPOSALS

## Purpose

Carry a bundle / stable bundle reference through the production governed write-proposal path so the
human can inspect the evidence behind a proposal — without the bundle becoming write authority.

## What This Task Does

Wires bundle linkage through the production governed write-proposal path using
`app/writeback/bundle_proposal.py`, keeping propose / stage / apply / log distinct and ensuring
WriteGuard (`app/write_guard.py`) runs independently and remains authoritative.

## Concretely

A production write proposal should carry a stable bundle reference plus explicit authority posture
(`may_propose` true, `may_write` false), and the proposal path must still pass through the normal
governed write boundary before any apply.

## Why This Matters

The contract is explicit that a bundle may support a proposal but must not bypass trust semantics or
APPLY rules. This is the point where evidence-bearing proposals could silently become hidden write
authority if the boundary is vague.

## Acceptance Criteria

- [ ] Production write proposals carry a bundle / stable reference.
  Verify: `tests/writeback/test_production_write_proposal_linkage.py::test_proposal_carries_bundle_reference`
- [ ] Linkage does not bypass WriteGuard.
  Verify: `tests/writeback/test_production_write_proposal_linkage.py::test_linkage_does_not_bypass_write_guard`
- [ ] propose / stage / apply / log remain distinct.
  Verify: `tests/writeback/test_production_write_proposal_linkage.py::test_propose_stage_apply_log_distinct`

## How to Verify (Pre-Merge)

- Add the writeback-layer tests named above.
- Run `ruff check app tests`.
- Confirm the proposal path requires the governed write boundary before apply and never upgrades
  `may_propose` into `may_write`.

## Out of Scope

- Executing applies in this slice.
- Receipt query projection (#1565).
- UI review rendering.

## Related Docs

- `docs/CONTEXT_BUNDLES/CONNECT_CONTEXT_BUNDLE_TO_WRITE_PROPOSALS.md`
- `docs/CONCEPTS/TRUST_SEMANTICS_CONTRACT.md`
- `app/writeback/bundle_proposal.py`
- `app/write_guard.py`

## Related GitHub Issues

- Implementation issue: [#1564](https://github.com/RasmusTho/agentic-pkm-mvp/issues/1564)
- Depends on: [#1562](https://github.com/RasmusTho/agentic-pkm-mvp/issues/1562)
- Parent feature: [#1559](https://github.com/RasmusTho/agentic-pkm-mvp/issues/1559)
