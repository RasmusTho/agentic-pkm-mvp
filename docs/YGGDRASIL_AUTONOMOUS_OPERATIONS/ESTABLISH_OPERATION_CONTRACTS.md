---
name: Establish Operation Contracts
description: Define the shared request, outcome, receipt, conflict, and capability vocabulary without adding a new domain authority
task_id: AUTOOPS-01
github_issue: 5330
source_anchor: "docs/contracts/YGGDRASIL_AUTONOMOUS_OPERATIONS_CONTRACT.md :: Operation envelope"
parent_capability: Yggdrasil Autonomous Operations
prerequisites: []
depends_on: []
can_parallelize_with: [Design the Human Operations Flow]
---

# Establish Operation Contracts

## Purpose

Give every adapter one stable, typed language for operations before runtime paths are consolidated.

## What This Task Does

Define provider-free operation requests, context, preconditions, item and aggregate outcomes,
receipts, conflicts, and capability discovery. Keep domain payloads owned by their existing models.

## Concretely

```text
OperationRequest(kind="artifact.move", context=..., target=..., expected_version=7)
OperationOutcome(status="conflicted", conflict={expected: 7, actual: 8}, effect_receipt=null)
```

## Why This Matters

Without one typed contract, GUI and MCP can report different truths or silently discard recovery data.

## Acceptance Criteria

- [ ] Contract types round-trip every status and preserve extensions without provider fields.
  Verify: `tests/operations/test_contracts.py::test_operation_contract_round_trip_and_forward_compatible_extensions`
- [ ] Capability discovery distinguishes supported, policy-disabled, and unavailable operations.
  Verify: `tests/operations/test_contracts.py::test_capability_discovery_reports_support_policy_and_availability`
- [ ] Architecture fitness rejects domain writes and adapter imports from the contract package.
  Verify: `tests/architecture/test_autonomous_operations_boundaries.py::test_operation_contracts_are_provider_free_and_non_writing`

## How to Verify (Pre-Merge)

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/operations/test_contracts.py tests/architecture/test_autonomous_operations_boundaries.py`
- `ruff check app tests`

## Out of Scope

- Runtime dispatch, persistence, domain adapters, GUI, or MCP transport.

## Related Docs

- `docs/contracts/YGGDRASIL_AUTONOMOUS_OPERATIONS_CONTRACT.md`
- `docs/contracts/CAPABILITY_CONTRACT.md`
- `docs/contracts/ARTIFACT_CONTRACT.md`

## Related GitHub Issues

Create one ready child of the capability parent. TCD hint: `fresh_issue_agent`, helper budget 0,
balanced implementation capability at medium reasoning; the slice is typed core code with bounded tests.
