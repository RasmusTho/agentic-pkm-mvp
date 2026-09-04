---
name: Design the Human Operations Flow
description: Produce a governed Companion interaction handoff for discovery, delegation, progress, receipts, conflicts, and recovery
task_id: AUTOOPS-09
github_issue: 5338
source_anchor: "docs/contracts/YGGDRASIL_AUTONOMOUS_OPERATIONS_CONTRACT.md :: Human flow"
parent_capability: Yggdrasil Autonomous Operations
prerequisites: []
depends_on: []
can_parallelize_with: [Establish Operation Contracts, Consolidate Discovery and Read Operations]
---

# Design the Human Operations Flow

## Purpose

Turn the human-flow contract into an implementation-ready Companion design before UI code expands.

## What This Task Does

Use the governed Yggdrasil design-handoff workflow to specify operation discovery, target selection,
one-time bounded delegation, preview, progress, receipts, conflict resolution, cancellation, and recovery.
Cover keyboard, accessibility, small/large viewports, empty/loading/error states, and progressive disclosure.

## Concretely

```text
Select artifacts -> choose action -> see exact scope/policy -> delegate once
-> watch item progress -> inspect receipt/conflict -> retry recovery or narrow scope
```

## Why This Matters

Adding isolated buttons would expose capability without a coherent, trustworthy human flow.

## Acceptance Criteria

- [ ] A governed design handoff maps every human-flow stage and required GUI addition to existing Companion surfaces/components.
  Verify: `tests/governance/test_autonomous_operations_design_handoff.py::test_handoff_maps_human_flow_and_components`
- [ ] The handoff specifies loading, empty, denial, conflict, partial failure, cancellation, restart, and recovery states.
  Verify: `tests/governance/test_autonomous_operations_design_handoff.py::test_handoff_covers_failure_and_recovery_states`
- [ ] The handoff includes accessible keyboard/focus behavior and responsive layouts with review evidence.
  Verify: `tests/governance/test_autonomous_operations_design_handoff.py::test_handoff_covers_accessibility_and_responsive_behavior`
- [ ] Validation records the yggdrasil-design-handoff workflow result without claiming runtime delivery.
  Verify: `tests/governance/test_autonomous_operations_design_handoff.py::test_handoff_records_validation_without_shipped_claim`

## How to Verify (Pre-Merge)

- Run `.codex/skills/yggdrasil-design-handoff/SKILL.md` for the handoff lifecycle and its required validators.
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/governance/test_autonomous_operations_design_handoff.py`
- `rg -n "Failure and recovery states|Accessibility and responsive behavior|Design validation receipt" companion-ui/docs/design-handoffs/autonomous-operations/README.md`
- `python3 scripts/docs_guard.py --mode pr --base-ref origin/main`

## Out of Scope

- Runtime implementation, visual redesign of unrelated Companion pages, or new design-system primitives without evidence.

## Related Docs

- `docs/contracts/YGGDRASIL_AUTONOMOUS_OPERATIONS_CONTRACT.md`
- `docs/HUMAN_FLOW_TO_RUNTIME_MAP.md`
- `companion-ui/docs/UI_RUNTIME_BOUNDARIES.md`

## Related GitHub Issues

Create one ready child. TCD hint: `fresh_issue_agent`, helper budget 0, reliable design-capable agent
at high reasoning; must use `yggdrasil-design-handoff` and remain docs/design-only.
