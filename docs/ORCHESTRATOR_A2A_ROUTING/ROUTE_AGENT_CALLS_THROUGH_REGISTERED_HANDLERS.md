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

State: Specification ready.

# Route Agent Calls Through Registered Handlers

## Purpose

Make `agent_call` steps useful for supported targets by routing them through an orchestrator-owned handler surface instead of always falling back to the generic `not_implemented` path.

## What This Task Does

- Introduces or wires a handler-resolution path for supported `agent_call` recipients.
- Keeps the current in-process A2A posture; no remote transport is implied.
- Preserves the existing agent-config permission checks before execution.
- Returns a structured step result that reflects the handler outcome rather than only the request id.

## Concretely

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q \
  tests/orchestrator/test_agent_config_enforcement.py \
  tests/orchestrator/test_orchestrator_a2a_errors.py \
  tests/orchestrator/test_orchestrator_runs_steps.py -m "not pg"

# Example execution target after delivery:
# plan step kind=agent_call agent=reviewer
# -> agent.request.created emitted
# -> registered handler executes
# -> step result includes routed handler outcome
```

## Why This Matters

The repo already models multi-step plans with `agent_call` steps, but supported targets still behave like stubs. Until the orchestrator can resolve and execute registered handlers, the A2A path is not a real implementation surface.

## Acceptance Criteria

- [ ] Supported `agent_call` recipients are resolved through an explicit orchestrator-owned handler path.
- [ ] Unsupported recipients still fail clearly instead of silently succeeding.
- [ ] Agent-config permission checks continue to gate execution before the handler runs.
- [ ] Routed calls return a structured step result that downstream orchestration code can inspect.
- [ ] Focused orchestrator tests cover both supported and unsupported recipients.

## How to Verify (Pre-Merge)

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

## Related Docs

- `docs/ORCHESTRATOR_A2A_ROUTING/README.md`
- `docs/contracts/A2A_CONTRACT_AND_TRACE.md`
- `docs/AGENTS.md`
- `docs/tracks/TRACK_AGENTOPS_A2A_MCP.md`

## Related GitHub Issues

- Feature issue: `#359`
- Implementation task issue: `#360`
