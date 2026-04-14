State: New (post-v5.6 follow-up)
Doc role: Reference contract
Authority: Canonical current-state contract for the repo's timeout handling, SLA boundaries, and observable timeout behavior across orchestration surfaces. This document describes enacted behavior only and must stay aligned with `app/orchestrator/executor.py`, `app/orchestrator/v2_runtime.py`, `app/quality/`, and the owning SoT docs.

# Timeout And SLA Contract

This document describes the current timeout handling, SLA boundaries, and observable timeout behavior across orchestration surfaces in the repository.
It is a current-state contract for per-tool timeouts, executor-level timeout enforcement, and error propagation.
It does not claim production A2A transport SLA, retry queues, dead-letter queues, or runtime-level timeout budgets for multi-step plans.

Use this document with:
- `docs/ARCHITECTURE.md` for current runtime boundaries and orchestrator V1/V2 posture.
- `docs/contracts/TOOL_POLICY_AND_MCP_ADAPTER_CONTRACT.md` for tool descriptor and execution semantics.
- `docs/contracts/A2A_CONTRACT_AND_TRACE.md` for agent-to-agent coordination (which currently has no timeout management).

## Current posture

- Per-tool timeout is supported via `tool_timeout_seconds` setting passed to the executor.
- Timeout is enforced at the executor level for individual tool calls, not at the orchestrator level.
- Orchestrator V1 (default) and V2 (flagged) both delegate timeout enforcement to the executor.
- Both orchestrators support a ThreadPoolExecutor for parallel execution (V1 uses single-threaded by default; V2 uses parallel).
- Timeout is observable: caught errors are emitted with error_type `tool_timeout`.
- No repo-wide A2A/runtime timeout policy, retry queue, delivery SLA, or multi-step plan budget exists.

## Timeout handling by surface

### Executor-level timeout (primary surface)

The executor (`MockPlanExecutor`) handles timeout for individual tool calls:

| Aspect | Current behavior | Meaning |
| --- | --- | --- |
| Setting | `StepContext.tool_settings["tool_timeout_seconds"]` | Float value (seconds) for per-tool timeout. |
| Enforcement | `timeout_wrapper(call, timeout_secs)` from `app.quality` | Wraps tool invocation with timeout boundary. |
| Error type | `tool_timeout` in `StepExecutionError` | Observable error discriminator for timeout vs. other failures. |
| Scope | Per-tool call only | Does not apply to plan-level or orchestrator-level budgets. |
| Default | No timeout (None) | If `tool_timeout_seconds` is absent or unparseable, no timeout is applied. |

Current implementation (executor.py lines 212-221):
- Parse `tool_timeout_seconds` from settings as float.
- If parsing fails, set timeout to None.
- If timeout is set, wrap tool invocation with `timeout_wrapper(call, timeout_secs)`.
- Catch `FutureTimeoutError` and `TimeoutError` exceptions.
- Raise `StepExecutionError(..., error_type="tool_timeout")`.

### Orchestrator-level constraints (V1 and V2)

| Surface | Constraint | Meaning |
| --- | --- | --- |
| V1 Orchestrator | Single-threaded execution by default | Steps are executed sequentially; timeout on one step blocks subsequent steps. |
| V2 Orchestrator | Parallel execution via ThreadPoolExecutor | Multiple steps execute concurrently; timeout on one step does not block concurrent peers, but may trigger compensation. |
| Compensation (V2 only) | Triggered on step failure | If a step times out or fails, V2 may compensate by rolling back completed predecessors in reverse order. |
| Plan-level budget | Not supported | No orchestrator-level timeout for the entire plan. Each step has only its per-tool timeout. |

### Tool-specific timeout semantics

Tool descriptors do not define per-tool timeout overrides; timeout is controlled only via `tool_settings["tool_timeout_seconds"]`.

| Tool kind | Timeout control | Meaning |
| --- | --- | --- |
| `mcp` (MCP-backed tools) | `tool_timeout_seconds` | Applies to the tool invocation wrapped by executor. |
| `internal` (repo-owned handlers) | `tool_timeout_seconds` | Applies to the handler invocation wrapped by executor. |
| `cli` (reserved, not currently dispatched) | Not applicable | Reserved for future use. |

### A2A routing timeout (current limitation)

A2A currently has no timeout management:

| Aspect | Current state | Meaning |
| --- | --- | --- |
| In-process routing | No timeout | Agent handlers are called synchronously; no timeout protection at the A2A message level. |
| Timeout responsibility | Caller-owned | If a caller needs timeout for an A2A exchange, it must implement that timeout in its own code, not rely on the A2A layer. |
| Future delivery | Not claimed | Production A2A transport, retry queue, and delivery SLA do not exist. |

## Observable timeout behavior

### Error propagation

When a tool times out:

1. The executor catches the timeout exception in `_invoke_tool`.
2. It raises `StepExecutionError(..., error_type="tool_timeout")`.
3. The orchestrator (V1 or V2) catches `StepExecutionError` and emits `ORCHESTRATOR_STEP_ERROR` event.
4. The event includes the error_type, making the timeout observable in audit logs.

Example event payload (simplified):
```json
{
  "event": "ORCHESTRATOR_STEP_ERROR",
  "step_id": "step-42",
  "error_type": "tool_timeout",
  "error_message": "tool call timed out",
  "trace_id": "trace-xyz"
}
```

### Retry and compensation (V2 only)

V2 runtime checks `last_error_type == "timeout"` (line 461 in v2_runtime.py) to inform retry/compensation logic.
Current behavior: timeout is treated as a retriable error, and compensation may roll back predecessors.

## Constraints and non-claims

- No production A2A transport or runtime-level SLA beyond per-tool timeout.
- No retry queue, dead-letter queue, or orchestrator-managed delivery SLA.
- V1 and V2 both preserve the per-tool timeout boundary; no plan-level or orchestrator-level timeout budget.
- Tool timeout is observable and distinguishable from other failure modes via error_type.
- In-process A2A handlers have no timeout protection from the A2A layer; timeouts are caller-owned.

## Validation and compliance checklist

When adding or modifying timeout behavior:

- [ ] Tool execution uses `tool_timeout_seconds` from `StepContext.tool_settings`.
- [ ] Timeout is wrapped via `timeout_wrapper(...)` from `app.quality`.
- [ ] Timeout failures emit `StepExecutionError(..., error_type="tool_timeout")`.
- [ ] Orchestrator error events (`ORCHESTRATOR_STEP_ERROR`) correctly capture the error_type for audit.
- [ ] Tests distinguish timeout from other failures using error_type.
- [ ] A2A in-process routing does not introduce new timeout dependencies.
- [ ] Owner docs remain truthful about what timeout/SLA behavior is baseline vs. future.
