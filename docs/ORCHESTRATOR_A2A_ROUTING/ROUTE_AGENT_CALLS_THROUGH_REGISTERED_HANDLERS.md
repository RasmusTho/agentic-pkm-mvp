---
name: Route Agent Calls Through Registered Handlers
description: Replace the default not-implemented fallback with orchestrator-owned routing for supported agent_call targets
task_id: A2A-ROUTING-01
source_anchor: docs/tracks/TRACK_AGENTOPS_A2A_MCP.md :: A2A-ROUTING
parent_capability: Orchestrator-managed A2A routing
prerequisites: none
depends_on: []
can_parallelize_with: []
---

State: Delivered (issue #360, PR #366).

# Route Agent Calls Through Registered Handlers

<!-- A2A-ROUTING-01 -->

## Purpose

Make `agent_call` steps useful for supported targets by routing them through an orchestrator-owned handler surface instead of always falling back to the generic `not_implemented` path.

## What This Task Does

- Introduces an `AgentHandler` registry on `MockPlanExecutor` (constructor `handlers` dict + `register_handler()` method).
- Keeps the current in-process A2A posture; no remote transport is implied.
- Preserves the existing agent-config permission checks before execution.
- Returns a structured step result that reflects the handler outcome: `agent`, `request_id`, and `response` (full model dump).
- Unsupported recipients emit `agent.error.created` and raise `StepExecutionError` with `error_type="not_implemented"` — step status becomes `error`.

## Concretely

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q \
  tests/orchestrator/test_agent_config_enforcement.py \
  tests/orchestrator/test_orchestrator_a2a_errors.py \
  tests/orchestrator/test_orchestrator_runs_steps.py -m "not pg"
# 9 passed
```

## Why This Matters

The repo already models multi-step plans with `agent_call` steps, but supported targets still behaved like stubs. With the handler registry, the A2A path is now a real in-process execution surface.

## Acceptance Criteria

- [x] Supported `agent_call` recipients are resolved through an explicit orchestrator-owned handler path.
- [x] Unsupported recipients still fail clearly instead of silently succeeding.
- [x] Agent-config permission checks continue to gate execution before the handler runs.
- [x] Routed calls return a structured step result that downstream orchestration code can inspect.
- [x] Focused orchestrator tests cover both supported and unsupported recipients.

## How to Verify (Post-Merge)

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q \
  tests/orchestrator/test_agent_config_enforcement.py \
  tests/orchestrator/test_orchestrator_a2a_errors.py \
  tests/orchestrator/test_orchestrator_runs_steps.py -m "not pg"

rg -n "handle_agent_request|send_agent_request|agent_call" app/orchestrator app/a2a tests/orchestrator
```

## Out of Scope

- Remote A2A transport or queue semantics.
- Timeout, retry, or SLA policy.
- Broad planner redesign outside the `agent_call` routing boundary.

## Implementation Surface

- `app/orchestrator/executor.py` — `AgentHandler` type alias, `MockPlanExecutor.register_handler()`, routing in `_execute_agent_call()`
- `app/orchestrator/agents.py` — `_normalize_agent_target` exported for use by executor
- Tests: `tests/orchestrator/test_orchestrator_a2a_errors.py`, `tests/orchestrator/test_agent_config_enforcement.py`, `tests/orchestrator/test_orchestrator_runs_steps.py`

## Related Docs

- `docs/ORCHESTRATOR_A2A_ROUTING/README.md`
- `docs/contracts/A2A_CONTRACT_AND_TRACE.md`
- `docs/AGENTS.md`
- `docs/tracks/TRACK_AGENTOPS_A2A_MCP.md`

## Related GitHub Issues

- Feature issue: `#359`
- Implementation task issue: `#360` (delivered)
