---
name: Emit Agent Call Responses And Failures
description: Emit complete request, response, and failure receipts for routed agent_call steps
task_id: A2A-ROUTING-02
source_anchor: docs/tracks/TRACK_AGENTOPS_A2A_MCP.md :: A2A-ROUTING
parent_capability: Orchestrator-managed A2A routing
prerequisites: [A2A-ROUTING-01]
depends_on: [ROUTE_AGENT_CALLS_THROUGH_REGISTERED_HANDLERS.md]
can_parallelize_with: []
---

State: Delivered (issue #361, PR #377).

# Emit Agent Call Responses And Failures

Delivery receipt: Issue #361, PR #377.

## Purpose

Make the routed `agent_call` path inspectable by emitting the complete success and failure receipt set, not just the request event.

## What This Task Does

- Emits `agent.response.created` for successful routed handler completion.
- Emits `agent.error.created` for handler failures, permission denials, or timeout/error cases that belong to the routed A2A path.
- Preserves `trace_id` and correlation continuity across request, response, and error receipts.
- Returns step results or surfaced errors that reflect the emitted routing outcome.

## Concretely

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q \
  tests/a2a/test_events.py \
  tests/orchestrator/test_orchestrator_a2a_errors.py \
  tests/orchestrator/test_orchestrator_runs_steps.py -m "not pg"

# Expected audit sequence after delivery:
# agent.request.created
# agent.response.created
# or
# agent.request.created
# agent.error.created
```

## Why This Matters

Without response and failure receipts, the orchestrator cannot prove what happened after request emission. Operators and downstream tests only see a request plus a generic fallback error, which is not enough for a real routing contract.

## Acceptance Criteria

- [x] Successful routed calls emit `agent.response.created` with the expected status/result shape.
- [x] Routed failures emit `agent.error.created` with stable `error_type` semantics for the current contract.
- [x] `trace_id` and correlation data are preserved across the emitted receipt sequence.
- [x] Step outputs or surfaced execution errors stay aligned with the emitted A2A receipt.
- [x] Focused tests cover both success and failure receipt paths.

## How to Verify (Pre-Merge)

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q \
  tests/a2a/test_events.py \
  tests/orchestrator/test_orchestrator_a2a_errors.py \
  tests/orchestrator/test_orchestrator_runs_steps.py -m "not pg"

rg -n "emit_agent_response_event|emit_agent_error_event|trace_id|correlation_id" app/a2a app/orchestrator tests/a2a tests/orchestrator
```

## Out of Scope

- Retry/backoff policy.
- Queueing, DLQ, or long-running delivery semantics.
- Owner-doc promotion before the parent capability is validated.

## Related Docs

- `docs/ORCHESTRATOR_A2A_ROUTING/README.md`
- `docs/contracts/A2A_CONTRACT_AND_TRACE.md`
- `docs/tracks/TRACK_AGENTOPS_A2A_MCP.md`

## Related GitHub Issues

- Feature issue: `#359`
- Implementation task issue: `#361` (delivered via PR #377)
