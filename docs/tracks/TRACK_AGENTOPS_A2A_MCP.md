State: Orchestrator-managed A2A routing fully delivered — handler-registry routing (#360), response/error receipts (#361), multi-agent chain traceability (#362). Parent feature #359 closed. MCP orchestration still planned.
# Track — AgentOps, A2A, MCP

Scope: outer agent coordination, event/A2A contracts, tool/MCP boundaries, and observability/ops hardening.

## Architecture hardening themes
- Event schema discipline: naming/versioning/idempotency/trace_id; DLQ/retry thinking captured in `docs/research/pattern-harvest-agentic-architecture.md`.
- A2A contracts: current-state envelope schema and emitted audit actions are documented in `docs/contracts/A2A_CONTRACT_AND_TRACE.md`; handler-registry routing (#360), response/error receipts (#361), and multi-step chain traceability (#362) are all delivered. Full capability spec: `docs/ORCHESTRATOR_A2A_ROUTING/README.md`. Parent feature: #359 (closed). Tracked by: #233, #360, #361, #362. Source Anchor: A2A-ROUTING
- Tool boundary: MCP descriptor registry with allowed_args + mock_result; deterministic adapters; permission/timeouts documented in `docs/contracts/TOOL_POLICY_AND_MCP_ADAPTER_CONTRACT.md`. Tracked by: #234. Source Anchor: MCP-TOOL-BOUNDARY
- Observability & agent-ops: audit events/metrics/runbooks for panel/watcher/orchestrator; CLI is tooling (not UI). Current incident workflow now lives in `docs/runbooks/RUNBOOK_AGENTOPS_INCIDENT_TRIAGE.md`. Tracked by: #235. Source Anchor: AGENTOPS-OBSERVABILITY
- Config validation: vault-first, schema-validated wiring for panel actions/watcher policies.

## Delivered scaffolding
- Deterministic A2A message schema and mocks.
- MCP descriptor registry with mocks; Plan/PlanStep schema (v4.9) shared by planner backends.
- Pattern harvest doc with backlog and Mermaid stack view: `docs/research/pattern-harvest-agentic-architecture.md`.

## Delivered routing (complete)
- Orchestrator-managed in-process A2A routing via handler registry (`MockPlanExecutor`). Supported recipients route through registered handlers with audit/trace; unsupported recipients fail the step clearly with `not_implemented`. Issue #360. Spec: `docs/ORCHESTRATOR_A2A_ROUTING/ROUTE_AGENT_CALLS_THROUGH_REGISTERED_HANDLERS.md`.
- Complete routed receipt set: response and error events emitted for all handler dispatch paths. Issue #361, PR #377.
- Multi-step chain traceability proven across V1 and V2 orchestrator surfaces. Issue #362, PR #383.

## Planned
- MCP ToolProvider integration for LangGraph executor; richer tool coverage under strict descriptors.

## Links
- Forward plan: `docs/ROADMAP.md` (tracks section).
- Fitness/CI contracts: `docs/tracks/TRACK_FITNESS_CI_CONTRACT.md`.
- Current A2A contract: `docs/contracts/A2A_CONTRACT_AND_TRACE.md`.
