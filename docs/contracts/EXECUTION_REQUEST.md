State: Target-state contract stub; execution routing is not fully implemented under this shape.
Doc role: Contract stub
Authority: Owns the EXE side-effect request seam after GOV authorization.
Owner subsystem: EXE - Capability Execution & Automation
Temporal class: strategic
Review cadence: event-driven
Source of truth: mixed
Last reviewed: 2026-06-21

# ExecutionRequest

## Purpose

Separate cognitive planning from side-effecting execution by requiring authorized execution requests, previews/dry runs where possible, result reporting, and trace/receipt linkage.

## Inputs

- Requested side effect.
- Actor/principal.
- Resource target.
- DecisionToken reference for governed effects.
- ActiveContextSet reference.
- Tool/provider adapter reference.
- Dry-run/preview preference.

## Outputs

- Execution status.
- Preview or dry-run result.
- Effect result.
- Rollback result where possible.
- Execution receipt/trace linkage.

## Commands

- Preview.
- Dry run.
- Execute.
- Roll back where possible.
- Report result.
- Normalize external effect response.

## Queries

- What ran?
- Which DecisionToken authorized it?
- What failed?
- Which receipt/trace records apply?
- Is rollback available?

## Events

- `execution.requested`
- `execution.previewed`
- `execution.started`
- `execution.succeeded`
- `execution.failed`
- `execution.rollback_attempted`

## Invariants

- EXE knows how to execute; GOV decides whether execution is admissible.
- CAO does not perform unmanaged tool side effects.
- Authority-bearing durable effects require DecisionToken reference.
- Result linkage is visible to OEF and GOV.

## Allowed Producers

- CAO workflows.
- HIX human-command surfaces.
- Automation triggers under GOV policy.

## Allowed Consumers

- EXE runners, EBF tool/provider adapters, GOV receipts, OEF traces, HIX status surfaces.

## Forbidden Use

- Do not use ExecutionRequest to bypass policy.
- Do not let EXE decide semantic authority internally.
- Do not hide failed external side effects.

## Failure Modes

- Agent runtime performs side effects without EXE/GOV seam.
- Execution mechanism becomes authority.
- Rollback/preview posture is implied but not recorded.

## Transitional Implementation Notes

Existing tool/MCP/provider execution paths should be wrapped before widening autonomous or agent-triggered side effects.

A first transitional adapter lives in `app/execution/execution_request.py`: frozen
`ExecutionRequest` and `ExecutionResult` dataclasses plus `CONTRACT_VERSION`,
mirroring `app/governance/governed_write.py`. It reuses the `DecisionToken` type
from `app.governance.governed_write` rather than redefining it, so EXE and GOV
share one authorization vocabulary.

The first wrapped side effect is the real-vault `mcp.vault.append_note` write in
`app/orchestrator/executor.py` (`MockPlanExecutor._run_vault_append`, reached via
`_execute_tool_call` -> `_invoke_tool`). The wrapper is additive and lives behind
the existing real-tool gate (`_should_use_real_tool`), so mock/CI behavior and
tool policy are unchanged. The `ExecutionRequest`/`ExecutionResult` carry
`context.trace_id` (and `context.agent_id` as actor) so trace linkage rides the
already-emitted `mcp.tool_call.started` / `mcp.tool_call.finished` events.

Transitional DecisionToken gap: the orchestrator does not yet thread a
`DecisionToken` through `StepContext`, so the `decision_token` field is OPTIONAL
and defaults to `None` on this path. This is the documented transitional gap the
contract permits — authority-bearing durable effects will require a non-null
`DecisionToken` once GOV authorization is threaded into orchestrator execution.

## Open Questions

- Which side-effect classes require preview or dry-run before execution?
- Which rollback guarantees are practical versus best-effort diagnostics?

## Linked Source-Of-Truth Docs

- `docs/SYSTEM_BREAKDOWN_STRUCTURE.md`
- `docs/contracts/TOOL_POLICY_AND_MCP_ADAPTER_CONTRACT.md`
- `docs/CONCEPTS/WORKFLOW_MUTATION_AND_GOVERNANCE_SEMANTICS.md`
- `docs/EVENTS.md`
