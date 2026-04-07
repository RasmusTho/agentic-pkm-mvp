State: Delivered (issue #360)
Doc role: Feature index
Authority: Entry point for orchestrator-managed A2A routing. References spec doc and contract doc.

# Orchestrator A2A Routing

Orchestrator-managed routing for in-process `agent_call` plan steps.

## Delivered

- `ROUTE_AGENT_CALLS_THROUGH_REGISTERED_HANDLERS.md` — handler registry routing spec (A2A-ROUTING-01)

## Related docs

- `docs/contracts/A2A_CONTRACT_AND_TRACE.md` — canonical A2A envelope schema and audit event contract
- `docs/tracks/TRACK_AGENTOPS_A2A_MCP.md` — track context (A2A-ROUTING anchor)
- `docs/AGENTS.md` — agent matrix

## Posture

Routing is in-process. No remote transport, no retry queue, no delivery SLA.
Supported recipients are registered as `AgentHandler` callables on `MockPlanExecutor`.
Unsupported recipients fail the step with `error_type="not_implemented"`.
