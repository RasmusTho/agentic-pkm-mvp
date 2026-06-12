---
name: Promote Cognitive Load Owner Docs
description: Promote accepted #1638 runtime evidence into owner docs and close the parent validation hub
task_id: CLRA-04
source_anchor: docs/COGNITIVE_LOAD_RUNTIME_ADOPTION/README.md :: Capability-Level Acceptance Criteria
parent_capability: cognitive-load-runtime-adoption
prerequisites: [CLRA-01, CLRA-02, CLRA-03]
depends_on:
  - PROVE_SOURCE_PRESERVING_SUMMARY_REVIEW.md
  - SURFACE_SCARCE_RESURFACING_CARDS.md
  - STAGE_TEXT_CORRECTION_PROPOSALS.md
can_parallelize_with: []
---

# Promote Cognitive Load Owner Docs

## Purpose

This task closes the #1638 validation loop after runtime/UI evidence exists. It updates owner docs
so shipped cognitive-load support is described truthfully and remaining target-state work is not
misread as delivered.

## What This Task Does

After #1679 and the two runtime/UI children are delivered, promote accepted reality into the
appropriate owner docs, update this spec directory's state, post the final parent validation receipt,
and close #1638 if all acceptance conditions are satisfied.

## Concretely

The final child should:

- inspect #1638 and child delivery receipts;
- update owner docs such as `docs/STATUS.md`, `docs/ARCHITECTURE.md`,
  `docs/COGNITIVE_LOAD_PROJECTION_LAYER.md`, `docs/COMPANION_UI_PRODUCT_SPEC.md`, or this spec
  directory only where shipped truth changed;
- record #1646/#1647 as a separate Source Understanding parent path, not a #1638 blocker;
- update `README.md` and `PARENT_FEATURE_ISSUE.md` in this directory from active/filed to delivered
  when closure is accepted;
- post a final validation receipt to #1638 and close it.

## Why This Matters

Feature breakdown avoids overclaiming while child evidence is still accumulating. The parent should
close only when owner docs and backlog state match shipped reality.

## Acceptance Criteria

- [x] #1638 has validation receipts for #1679, scarce resurfacing cards, and correction proposals.
  Verify: parent issue receipt on `https://github.com/RasmusTho/agentic-pkm-mvp/issues/1638`.
- [x] Owner docs distinguish shipped runtime/UI support from target-state cognitive-load work.
  Verify: doc writeback at `docs/STATUS.md :: cognitive-load` or an explicit no-change receipt if
  current-state docs already remain truthful.
- [x] #1646/#1647 are recorded as a separate Source Understanding path and not a #1638 blocker.
  Verify: doc writeback at `docs/COGNITIVE_LOAD_RUNTIME_ADOPTION/README.md :: Capability Boundary`
  and parent issue receipt on #1638.
- [x] This spec directory records delivered state and linked child issue numbers.
  Verify: doc writeback at `docs/COGNITIVE_LOAD_RUNTIME_ADOPTION/README.md :: Relationship to GitHub Issues`.
- [x] #1638 is closed only after all parent acceptance conditions are satisfied.
  Verify: closed GitHub Issue #1638 with final validation receipt.

## How to Verify (Pre-Merge)

- `git diff --check`
- `python3 scripts/docs_guard.py`
- `gh issue view 1638 --json state,body,comments`
- focused `rg` checks for any owner docs changed in the PR

## Out of Scope

- Implementing new runtime/UI behavior.
- Closing #1646 or #1647.
- Promoting Source Understanding Mode into #1638.
- Creating new cognitive-load feature work beyond explicit follow-up issues.

## Related Docs

- `docs/COGNITIVE_LOAD_RUNTIME_ADOPTION/README.md`
- `docs/COGNITIVE_LOAD_RUNTIME_ADOPTION/PARENT_FEATURE_ISSUE.md`
- `docs/COGNITIVE_LOAD_PROJECTION_LAYER.md`
- `docs/STATUS.md`
- `docs/ARCHITECTURE.md`
- `docs/COMPANION_UI_PRODUCT_SPEC.md`

## Related GitHub Issues

Execution issue: [#1682](https://github.com/RasmusTho/agentic-pkm-mvp/issues/1682).
Parent validation hub: [#1638](https://github.com/RasmusTho/agentic-pkm-mvp/issues/1638).
