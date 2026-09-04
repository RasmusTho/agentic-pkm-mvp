---
name: Implement the Companion Operations Workspace
description: Implement the accepted human flow over the shared operations API with truthful progress, receipts, conflicts, and recovery
task_id: AUTOOPS-10
github_issue: 5339
source_anchor: "docs/contracts/YGGDRASIL_AUTONOMOUS_OPERATIONS_CONTRACT.md :: Required GUI additions"
parent_capability: Yggdrasil Autonomous Operations
prerequisites: [AUTOOPS-03, AUTOOPS-04, AUTOOPS-05, AUTOOPS-06, AUTOOPS-07, AUTOOPS-08, AUTOOPS-09]
depends_on: [CONSOLIDATE_DISCOVERY_AND_READ_OPERATIONS.md, CONSOLIDATE_CREATE_AND_EDIT_OPERATIONS.md, DELIVER_IDENTITY_PRESERVING_MOVE_AND_RENAME.md, DELIVER_CLASSIFICATION_TAGGING_AND_ORDERING.md, COMPOSE_ARCHIVE_AND_RESTORE_OPERATIONS.md, DELIVER_SAFE_BATCH_EXECUTION_AND_RECOVERY.md, DESIGN_HUMAN_OPERATIONS_FLOW.md]
can_parallelize_with: []
---

# Implement the Companion Operations Workspace

## Purpose

Give humans the complete governed operations flow in Companion, including the capabilities absent from the GUI today.

## What This Task Does

Implement operation capability discovery, contextual actions for create/edit/move/rename/classify/tag/
order/archive/restore, bounded batch preview/delegation, live progress, receipt inspection, typed
conflicts, cancellation, and recovery using only the shared operations API.

## Concretely

```text
Companion selection/action UI -> operations HTTP adapter -> shared kernel
Outcome UI renders operation status verbatim and offers only contract-allowed next actions.
```

## Why This Matters

The product is not functionally complete if only agents can reach the broader operation surface.

## Acceptance Criteria

- [ ] The accepted human flow exposes all supported operation families through capability-driven controls.
  Verify: `companion-ui/companion-app/src/features/operations/__tests__/operations-workspace.test.tsx::renders_capability_driven_operation_actions`
- [ ] Delegation preview states exact targets, policy ceiling, cardinality, and effect before one confirmation.
  Verify: `companion-ui/companion-app/src/features/operations/__tests__/delegation-flow.test.tsx::confirms_bounded_scope_once_before_execution`
- [ ] Progress and result views preserve per-item receipts, conflicts, refusal, lag, cancellation, and recovery.
  Verify: `companion-ui/companion-app/src/features/operations/__tests__/operation-results.test.tsx::renders_truthful_progress_receipts_and_recovery`
- [ ] Focus, keyboard, screen-reader, and responsive behavior matches the accepted handoff.
  Verify: `companion-ui/companion-app/src/features/operations/__tests__/operations-accessibility.test.tsx::supports_keyboard_focus_labels_and_responsive_layout`
- [ ] UI code cannot import domain stores or bypass the operations client boundary.
  Verify: `tests/architecture/test_autonomous_operations_boundaries.py::test_companion_operations_use_only_public_operations_client`

## How to Verify (Pre-Merge)

- Run the focused Companion test files named above through the repository's package-manager command.
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/architecture/test_autonomous_operations_boundaries.py`
- `ruff check app tests companion-ui/companion-app`
- Run the visual/responsive validation required by the accepted design handoff.

## Out of Scope

- Changing operation semantics, domain storage, design-system replacement, or MCP behavior.

## Restart / Durability Posture

The UI owns no effect truth. After reload/restart it rehydrates active and completed operations from
durable receipts; unavailable readback is shown as unknown/recovery-required, never reset to success.

## Related Docs

- `docs/contracts/YGGDRASIL_AUTONOMOUS_OPERATIONS_CONTRACT.md`
- `companion-ui/docs/UI_RUNTIME_BOUNDARIES.md`
- `companion-ui/docs/design-handoffs/autonomous-operations/README.md`

## Related GitHub Issues

Block on AUTOOPS-03 through 09. TCD hint: `fresh_issue_agent`, helper budget 1, strongest reliable
implementation capability at high reasoning due to broad UI/state-machine and accessibility scope.
