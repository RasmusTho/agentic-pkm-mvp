---
name: Enforce the Operation Execution Kernel
description: Execute typed operations with authority, precondition, idempotency, receipt, and fail-closed recovery enforcement
task_id: AUTOOPS-02
github_issue: 5331
source_anchor: "docs/contracts/YGGDRASIL_AUTONOMOUS_OPERATIONS_CONTRACT.md :: Concurrency, no-clobber, and idempotency"
parent_capability: Yggdrasil Autonomous Operations
prerequisites: [AUTOOPS-01]
depends_on: [ESTABLISH_OPERATION_CONTRACTS.md]
can_parallelize_with: []
---

# Enforce the Operation Execution Kernel

## Purpose

Provide the single production call site that adapters use to authorize and execute an operation.

## What This Task Does

Add a thin execution kernel that resolves explicit context, enforces policy and version
preconditions, binds idempotency, invokes one owner-native handler, and records a redacted receipt.

## Concretely

```text
execute(request, delegation)
  -> resolve context -> authorize -> reserve idempotency -> owner handler -> receipt
  -> typed refusal/conflict/recovery outcome on every failed phase
```

## Why This Matters

Cross-surface parity is unsafe if each entrypoint independently implements authority, retry, or success semantics.

## Acceptance Criteria

- [ ] The production executor enforces context, delegation, policy, version, and idempotency before owner effects.
  Verify: `tests/operations/test_execution_kernel.py::test_executor_enforces_all_preconditions_before_owner_handler`
- [ ] Same-key replay returns the existing receipt while key reuse with different intent conflicts.
  Verify: `tests/operations/test_execution_kernel.py::test_idempotency_replay_is_stable_and_intent_mismatch_conflicts`
- [ ] Ambiguous owner outcomes remain recoverable and never trigger blind retry or fabricated success.
  Verify: `tests/operations/test_execution_kernel.py::test_ambiguous_owner_outcome_is_fail_closed_and_recoverable`
- [ ] Receipt persistence and restart readback preserve operation identity and redaction.
  Verify: `tests/operations/test_execution_kernel_restart.py::test_receipts_survive_restart_without_sensitive_payloads`

## How to Verify (Pre-Merge)

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/operations/test_execution_kernel.py tests/operations/test_execution_kernel_restart.py`
- `ruff check app tests`

## Out of Scope

- Domain-specific mutation logic, adapter presentation, long-running job supervision, or deployment.

## Restart / Durability Posture

Accepted and terminal operation identities and receipts survive restart. In-flight work whose owner
effect cannot be proven returns `recovery_required`; it is never automatically re-executed.

## Related Docs

- `docs/contracts/YGGDRASIL_AUTONOMOUS_OPERATIONS_CONTRACT.md`
- `docs/contracts/GOVERNED_WRITE_PROTOCOL.md`
- `docs/CONCEPTS/TRUST_SEMANTICS_CONTRACT.md`

## Related GitHub Issues

Block on AUTOOPS-01. TCD hint: `fresh_issue_agent`, helper budget 1, strongest reliable implementation
capability at high reasoning because this is authority, concurrency, durability, and recovery code.
