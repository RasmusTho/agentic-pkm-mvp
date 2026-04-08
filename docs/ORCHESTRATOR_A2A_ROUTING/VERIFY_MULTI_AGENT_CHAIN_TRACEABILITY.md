---
name: Verify Multi-Agent Chain Traceability
description: Prove the routed A2A contract across multi-step plans and the current orchestrator runtime surfaces
task_id: A2A-ROUTING-03
source_anchor: docs/tracks/TRACK_AGENTOPS_A2A_MCP.md :: A2A-ROUTING
parent_capability: Orchestrator-managed A2A routing
prerequisites: [A2A-ROUTING-01, A2A-ROUTING-02]
depends_on:
  - ROUTE_AGENT_CALLS_THROUGH_REGISTERED_HANDLERS.md
  - EMIT_AGENT_CALL_RESPONSES_AND_FAILURES.md
can_parallelize_with: []
---

State: Delivered.

# Verify Multi-Agent Chain Traceability

## Purpose

Lock the routed A2A capability into the repo with integration coverage that proves traceability across multi-step plans and the current orchestrator runtime surfaces.

## What This Task Does

- Adds or tightens integration coverage for multi-step plans that include routed `agent_call` steps.
- Verifies that the current orchestrator V1 path preserves the A2A routing receipts end to end.
- Extends flagged V2 coverage where `agent_call` steps already execute through the shared executor.
- Produces one parent-capability validation receipt that links task-level verification to the feature outcome.

## Concretely

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q \
  tests/orchestrator/test_orchestrator_runs_steps.py \
  tests/orchestrator/test_multi_step_chain_traceability.py \
  tests/orchestration/v2/test_orchestrator_integration.py -m "not pg"

# Expected proof after delivery:
# multi-step plan emits trace-consistent request/response/error receipts
# V1 path verified
# flagged V2 path verified where agent_call steps already execute
```

## Why This Matters

The capability is not actually delivered when only the single-step happy path works. The repo claims a broader multi-agent direction, so the final acceptance gate needs chain-level evidence that the routed path remains traceable on the orchestrator surfaces that already execute `agent_call` steps.

## Acceptance Criteria

- [x] Multi-step plan coverage proves trace continuity across routed `agent_call` execution.
- [x] The current V1 orchestrator path is covered by focused integration tests.
- [x] Flagged V2 coverage is updated where the shared executor path exercises routed `agent_call` steps.
- [ ] The parent feature issue contains one explicit validation receipt summarizing the proven surfaces and remaining limits.
- [x] Owner docs are not promoted until this validation evidence exists.

## How to Verify (Pre-Merge)

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q \
  tests/orchestrator/test_orchestrator_runs_steps.py \
  tests/orchestrator/test_multi_step_chain_traceability.py \
  tests/orchestration/v2/test_orchestrator_integration.py -m "not pg"

rg -n "trace_id|agent.request.created|agent.response.created|agent.error.created|orchestrator.v2" tests/orchestrator tests/orchestration/v2 app/orchestrator
```

## Out of Scope

- New remote agent transports.
- New runtime claims for agent families that are still planned or parked.
- Promoting roadmap or owner-doc wording before the parent capability is validated.

## Related Docs

- `docs/ORCHESTRATOR_A2A_ROUTING/README.md`
- `docs/AGENTS.md`
- `docs/contracts/A2A_CONTRACT_AND_TRACE.md`
- `docs/tracks/TRACK_AGENTOPS_A2A_MCP.md`

## Related GitHub Issues

- Feature issue: `#359`
- Implementation task issue: `#362`
