State: Pattern harvest documented; A2A/MCP orchestration scaffolding planned; mocks/determinism in place.
# Track — AgentOps, A2A, MCP

Scope: outer agent coordination, event/A2A contracts, tool/MCP boundaries, and observability/ops hardening.

## Architecture hardening themes
- Event schema discipline: naming/versioning/idempotency/trace_id; DLQ/retry thinking captured in `docs/research/pattern-harvest-agentic-architecture.md`.
- A2A contracts: current-state envelope schema and emitted audit actions are documented in `docs/contracts/A2A_CONTRACT_AND_TRACE.md`; the delivered docs contract work is tracked by #233, while the planned implementation capability now has a dedicated specification set in `docs/ORCHESTRATOR_A2A_ROUTING/README.md` and parent feature issue #359. Source Anchor: A2A-ROUTING
- Tool boundary: MCP descriptor registry with allowed_args + mock_result; deterministic adapters; permission/timeouts documented in `docs/contracts/TOOL_POLICY_AND_MCP_ADAPTER_CONTRACT.md`. Tracked by: #234. Source Anchor: MCP-TOOL-BOUNDARY
- Observability & agent-ops: audit events/metrics/runbooks for panel/watcher/orchestrator; CLI is tooling (not UI). Current incident workflow now lives in `docs/runbooks/RUNBOOK_AGENTOPS_INCIDENT_TRIAGE.md`. Tracked by: #235. Source Anchor: AGENTOPS-OBSERVABILITY
- Config validation: vault-first, schema-validated wiring for panel actions/watcher policies.

## Delivered scaffolding
- Deterministic A2A message schema and mocks; routing/orchestrator playback to follow.
- MCP descriptor registry with mocks; Plan/PlanStep schema (v4.9) shared by planner backends.
- Pattern harvest doc with backlog and Mermaid stack view: `docs/research/pattern-harvest-agentic-architecture.md`.

## Planned
- Orchestrator-managed A2A routing for multi-agent chains with audit/trace. Specification: `docs/ORCHESTRATOR_A2A_ROUTING/README.md`. Backlog: #359, #360, #361, #362.
- MCP ToolProvider integration for LangGraph executor; richer tool coverage under strict descriptors.

## Links
- Forward plan: `docs/ROADMAP.md` (tracks section).
- Fitness/CI contracts: `docs/tracks/TRACK_FITNESS_CI_CONTRACT.md`.
- Current A2A contract: `docs/contracts/A2A_CONTRACT_AND_TRACE.md`.
