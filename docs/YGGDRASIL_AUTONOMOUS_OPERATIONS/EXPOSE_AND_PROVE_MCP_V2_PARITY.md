---
name: Expose and Prove MCP v2 Parity
description: Map the shared operation matrix to MCP v2 and prove parity with Companion while retaining the MCP v1 compatibility profile
task_id: AUTOOPS-11
github_issue: 5340
source_anchor: "docs/contracts/YGGDRASIL_AUTONOMOUS_OPERATIONS_CONTRACT.md :: MCP v2 parity profile"
parent_capability: Yggdrasil Autonomous Operations
prerequisites: [AUTOOPS-03, AUTOOPS-04, AUTOOPS-05, AUTOOPS-06, AUTOOPS-07, AUTOOPS-08, AUTOOPS-10]
depends_on: [CONSOLIDATE_DISCOVERY_AND_READ_OPERATIONS.md, CONSOLIDATE_CREATE_AND_EDIT_OPERATIONS.md, DELIVER_IDENTITY_PRESERVING_MOVE_AND_RENAME.md, DELIVER_CLASSIFICATION_TAGGING_AND_ORDERING.md, COMPOSE_ARCHIVE_AND_RESTORE_OPERATIONS.md, DELIVER_SAFE_BATCH_EXECUTION_AND_RECOVERY.md, IMPLEMENT_COMPANION_OPERATIONS_WORKSPACE.md]
can_parallelize_with: []
---

# Expose and Prove MCP v2 Parity

## Purpose

Complete the agent flow and prove that MCP and Companion are adapters over the same governed behavior.

## What This Task Does

Expose capability discovery and the full supported operation matrix through versioned MCP v2 schemas,
delegate exclusively to the shared operations API, preserve typed outcomes/receipts, retain ADR-0061
MCP v1 behavior, and run integrated human/agent parity and recovery acceptance.

## Concretely

```text
MCP v2 tools/list -> capability-derived schemas
MCP v2 operation call -> shared operations API -> unchanged typed outcome
MCP v1 ask/capture/retrieve/read/health -> unchanged compatibility behavior
```

## Why This Matters

This is the proof that agent autonomy is first-class without creating a privileged or less-governed back door.

## Acceptance Criteria

- [ ] MCP v2 advertises every supported operation family from capability discovery and no raw filesystem writer.
  Verify: `tests/mcp/test_mimer_v2_parity.py::test_v2_tools_are_capability_derived_and_exclude_raw_filesystem_write`
- [ ] Direct, HTTP, Companion, and MCP v2 calls preserve equivalent status, conflict, receipt, and recovery semantics.
  Verify: `tests/operations/test_cross_surface_conformance.py::test_all_operation_families_share_owner_native_semantics`
- [ ] MCP v1's five operations remain schema- and behavior-compatible.
  Verify: `tests/mcp/test_mimer_v2_parity.py::test_v1_compatibility_and_v2_operation_parity`
- [ ] Failure injection proves partial batch, stale version, disconnect-after-write, projection lag, and restart recovery across surfaces.
  Verify: `tests/operations/test_operations_failure_matrix.py::test_operations_failure_matrix_is_fail_closed_and_recoverable`
- [ ] A real MCP client and Companion UAT run produce a current-SHA parent acceptance receipt and closure handoff.
  Verify: runtime receipt: yggdrasil-autonomous-operations-acceptance.v1
- [ ] Current-state owner docs and this capability directory are promoted only after the parent accepts that receipt.
  Verify: doc writeback at `docs/YGGDRASIL_AUTONOMOUS_OPERATIONS/README.md :: Owner-Doc Promotion`

## How to Verify (Pre-Merge)

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/mcp/test_mimer_server.py tests/mcp/test_mimer_v2_parity.py tests/operations/test_cross_surface_conformance.py tests/operations/test_operations_failure_matrix.py`
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/architecture/test_autonomous_operations_boundaries.py`
- `ruff check app tests companion-ui/companion-app`
- Run the exact real-client and Companion UAT procedure, post `yggdrasil-autonomous-operations-acceptance.v1` to the parent, then invoke parent closure.

## Out of Scope

- Replacing stdio transport, adding a network listener, weakening authentication, or deploying to stable.

## Restart / Durability Posture

The MCP adapter owns no effect state. Reconnection uses durable operation receipt lookup; ambiguous
disconnects never authorize blind replay. Compatibility behavior survives server restart.

## Related Docs

- `docs/contracts/YGGDRASIL_AUTONOMOUS_OPERATIONS_CONTRACT.md`
- `docs/adr/ADR-0061-mimer-mcp-client-adapter.md`
- `docs/MIMER_MCP_CLIENT_ADAPTER/README.md`
- `docs/YGGDRASIL_AUTONOMOUS_OPERATIONS/PARENT_FEATURE_ISSUE.md`

## Related GitHub Issues

Block on AUTOOPS-03 through 10 and completion of the existing MCP v1 family #3366/#3368/#3369/#3370.
TCD hint: `fresh_issue_agent`, helper budget 1, strongest reliable capability at high reasoning for
external protocol, authority mapping, integrated parity, and terminal acceptance.
