---
name: Consolidate Create and Edit Operations
description: Route capture, typed creation, and versioned editing through existing governed write owners
task_id: AUTOOPS-04
github_issue: 5333
source_anchor: "docs/contracts/YGGDRASIL_AUTONOMOUS_OPERATIONS_CONTRACT.md :: Receipts and provenance"
parent_capability: Yggdrasil Autonomous Operations
prerequisites: [AUTOOPS-02]
depends_on: [ENFORCE_OPERATION_EXECUTION_KERNEL.md]
can_parallelize_with: []
---

# Consolidate Create and Edit Operations

## Purpose

Expose creation and editing without adding a generic file writer or bypassing governed-write semantics.

## What This Task Does

Register capture, typed artifact creation, metadata/content edit, and proposal-apply handlers over
existing owner-native write services. Bind expected versions, trace, policy decision, effect receipt,
and Store/index/link convergence to the operation outcome.

## Concretely

```text
artifact.update(id="...", expected_version=4, patch=...)
  -> governed owner writer -> committed source receipt -> projection convergence status
```

## Why This Matters

An agent can only act autonomously when a bounded delegation reaches the same safe writer as the GUI.

## Acceptance Criteria

- [ ] Capture/create/update production handlers invoke only enumerated governed writer entrypoints.
  Verify: `tests/operations/test_write_operations.py::test_write_operations_invoke_only_governed_owner_entrypoints`
- [ ] Version mismatch, policy denial, validation error, and ambiguous acknowledgement remain distinct and non-retrying.
  Verify: `tests/operations/test_write_operations.py::test_write_failures_preserve_conflict_denial_validation_and_ambiguity`
- [ ] Successful outcomes bind source receipt, provenance, and projection convergence without claiming lag as full convergence.
  Verify: `tests/operations/test_write_operations.py::test_success_binds_effect_receipt_and_truthful_projection_state`
- [ ] Existing MCP v1 capture semantics remain unchanged.
  Verify: `tests/mcp/test_mimer_server.py::test_capture_preserves_governed_receipt_at_production_callsite`

## How to Verify (Pre-Merge)

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/operations/test_write_operations.py tests/mcp/test_mimer_server.py`
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/api/test_capture_inbox_api.py`
- `ruff check app tests`

## Out of Scope

- Raw filesystem writes, arbitrary schema creation, move/rename, batch execution, or writer CAS migrations already owned by #3570.

## Restart / Durability Posture

Committed source effects and receipts survive restart. An unacknowledged response is recoverable by
operation identity; restart never turns uncertainty into a retry.

## Related Docs

- `docs/contracts/YGGDRASIL_AUTONOMOUS_OPERATIONS_CONTRACT.md`
- `docs/contracts/GOVERNED_WRITE_PROTOCOL.md`
- `docs/contracts/MIMER_CLIENT_CONTRACT.md`

## Related GitHub Issues

Block on AUTOOPS-02 and reconcile with the existing #3570 writer-safety family. TCD hint:
`fresh_issue_agent`, helper budget 1, strongest reliable capability at high reasoning for authority-bearing writes.
