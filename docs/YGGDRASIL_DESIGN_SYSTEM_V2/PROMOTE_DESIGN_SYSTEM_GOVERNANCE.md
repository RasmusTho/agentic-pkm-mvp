---
name: Promote the Design System Governance
description: Point DP-11, the handoff gate, and the design-handoff skill at the token source, and record the Shell trial outcome, then hand the parent to closure.
task_id: YDS-06
github_issue: 5631
source_anchor: "docs/YGGDRASIL_DESIGN_SYSTEM_V2/README.md :: Rollout"
parent_capability: Yggdrasil Design System v2
prerequisites: [YDS-01, YDS-02, YDS-03, YDS-04, YDS-05]
depends_on: [ESTABLISH_TOKEN_SOURCE_AND_GENERATOR.md, RECONCILE_LIVE_DESIGN_SYSTEM.md, MIGRATE_COMPANION_SURFACES.md, MIGRATE_BUILDER_SURFACES.md, ADOPT_TOKENS_IN_BIFROST.md]
can_parallelize_with: []
---

# Promote the Design System Governance

## Purpose

Once the system is delivered, make the governing rules describe it, so future design work routes
through the token source instead of the old hand-copied sheet.

## What This Task Does

- Updates `docs/DESIGN_PRINCIPLES.md :: 11. Shared Visual Language` to name the token source, the
  version, the two themes, and the effects rule.
- Updates `companion-ui/docs/DESIGN_HANDOFF_GOVERNANCE.md :: Yggdrasil design-system gate` and
  `.codex/skills/yggdrasil-design-handoff/SKILL.md` to point at the generated sheet and version.
- Records the owner's Shell trial outcome (graduate, change, or drop) and adjusts the spec to match.
- Promotes `docs/YGGDRASIL_DESIGN_SYSTEM_V2/README.md` from a target-state spec to an owner doc.
- Hands the parent feature issue to `verification-and-closure`. This task starts only after YDS-05
  is delivered in the Bifrost repository, because Bifrost adoption is part of the capability.

## Concretely

A builder reading DP-11 is sent to `design-system/yggdrasil/` and its generated sheet, not to a
hand-maintained file.

## Why This Matters

If the rules keep pointing at the old model, new work will reintroduce copied sheets and local
palettes.

## Acceptance Criteria

- [ ] DP-11 names the token source, version, themes, and effects rule.
  - Verify: doc writeback at `docs/DESIGN_PRINCIPLES.md :: 11. Shared Visual Language`
- [ ] The design-handoff skill gate reads the generated sheet and records the token version.
  - Verify: doc writeback at `.codex/skills/yggdrasil-design-handoff/SKILL.md :: Live design-system gate`
- [ ] The Shell trial outcome is recorded with the owner's decision.
  - Verify: doc writeback at `docs/YGGDRASIL_DESIGN_SYSTEM_V2/README.md :: Yggdrasil Light "Shell"`
- [ ] The parent-closure handoff is recorded.
  - Verify: doc writeback at `docs/YGGDRASIL_DESIGN_SYSTEM_V2/PARENT_FEATURE_ISSUE.md :: Validation / Acceptance Path`

## How to Verify (Pre-Merge)

- `python3 scripts/docs_guard.py`
- `pytest -q tests/architecture/test_agent_skill_entrypoints.py tests/architecture/test_docs_index.py`

## Out of Scope

- Any token or consumer change.

## Related Docs

- `docs/DESIGN_PRINCIPLES.md`
- `companion-ui/docs/DESIGN_HANDOFF_GOVERNANCE.md`
- `.codex/skills/yggdrasil-design-handoff/SKILL.md`

## Related GitHub Issues

Filed as #5631 under parent #5626. This is the final child. It carries the parent-closure handoff.
