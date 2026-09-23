---
name: Reconcile the Live Design System
description: Republish the Claude Design "Yggdrasil Design System" from the generated outputs so the live gate passes again and the system is no longer Legacy.
task_id: YDS-02
github_issue: 5628
source_anchor: "docs/YGGDRASIL_DESIGN_SYSTEM_V2/README.md :: Rollout"
parent_capability: Yggdrasil Design System v2
prerequisites: [YDS-01]
depends_on: [ESTABLISH_TOKEN_SOURCE_AND_GENERATOR.md]
can_parallelize_with: []
---

# Reconcile the Live Design System

## Purpose

Bring the live Claude Design system (`f2b13410-af14-4875-8029-445352123f57`) back into byte parity
with the repo binding sheet after YDS-01, and fix the drift already recorded against it.

## What This Task Does

- Uploads the generated `colors_and_type.css` to the live project through the owner-started
  `/design-sync` flow. The flow must use a finalized plan that names every written path.
- Rewrites the live `README.md` and `SKILL.md` so their prose matches the tokens (closes DS-1). They
  describe Dark and Shell, density, the ink/mark role tones, and the effects rule.
- Adds Shell previews next to the existing Dark previews.
- Records the DS-2 disposition. Either named component previews are promoted to bundle exports, or
  the limitation is kept with a reason.
- Updates the gate to record the new token SHA-256 and system version.

## Concretely

After upload, the SHA-256 of the live `colors_and_type.css` equals the SHA-256 of
`companion-ui/companion-app/colors_and_type.css` on `main`. The gate section records that value.

## Why This Matters

YDS-01 changes the bytes of the binding sheet, so the fail-closed gate blocks all new design
generation until the live system matches again.

## Acceptance Criteria

- [ ] The gate records the new token SHA-256, the system version, and the reconciliation date.
  - Verify: doc writeback at `companion-ui/docs/DESIGN_HANDOFF_GOVERNANCE.md :: Yggdrasil design-system gate`
- [ ] The DS-1 and DS-2 conflicts carry a reconciled disposition.
  - Verify: doc writeback at `docs/BUILDEROPS_COCKPIT/DESIGN_DECISIONS.md :: Design-system conflicts`
- [ ] The spec records S2 as delivered, with the live-parity evidence.
  - Verify: doc writeback at `docs/YGGDRASIL_DESIGN_SYSTEM_V2/README.md :: Rollout`

## How to Verify (Pre-Merge)

- Read the live `colors_and_type.css` back and compare SHA-256 with the repo binding sheet.
- `python3 scripts/docs_guard.py`
- `git diff --check`

## Out of Scope

- Changing token values. Any change goes back through YDS-01's source and generator.
- Generating new designs.

## Related Docs

- `.codex/skills/yggdrasil-design-handoff/SKILL.md :: Live design-system gate`
- `companion-ui/docs/DESIGN_HANDOFF_GOVERNANCE.md`

## Related GitHub Issues

Filed as #5628 under parent #5626. The owner starts `/design-sync`, because the Claude Design write tool is only used inside that
owner-started flow. The owner has a working Claude Design login as of 2026-09-22.
