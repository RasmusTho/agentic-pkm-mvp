State: Pattern harvest documented; A2A/MCP orchestration scaffolding planned; mocks/determinism in place.
# Track — AgentOps, A2A, MCP

Scope: outer agent coordination, event/A2A contracts, tool/MCP boundaries, and observability/ops hardening.

## Architecture hardening themes
- Event schema discipline: naming/versioning/idempotency/trace_id; DLQ/retry thinking captured in `docs/research/pattern-harvest-agentic-architecture.md`.
- A2A contracts: current-state envelope schema and emitted audit actions are documented in `docs/contracts/A2A_CONTRACT_AND_TRACE.md`; orchestration-managed routing remains planned. Tracked by: #233. Source Anchor: A2A-ROUTING
- Tool boundary: MCP descriptor registry with allowed_args + mock_result; deterministic adapters; permission/timeouts documented. Tracked by: #234. Source Anchor: MCP-TOOL-BOUNDARY
- Observability & agent-ops: audit events/metrics/runbooks for panel/watcher/orchestrator; CLI is tooling (not UI). Shipped: incident triage runbook (`docs/runbooks/RUNBOOK_AGENTOPS_INCIDENT_TRIAGE.md`) covering current-state watcher/panel/orchestrator diagnostic signals, commands, and escalation paths. Delivery receipt: Issue #235, PR (pending). Source Anchor: AGENTOPS-OBSERVABILITY
- Config validation: vault-first, schema-validated wiring for panel actions/watcher policies.

## Delivered scaffolding
- Deterministic A2A message schema and mocks; routing/orchestrator playback to follow.
- MCP descriptor registry with mocks; Plan/PlanStep schema (v4.9) shared by planner backends.
- Pattern harvest doc with backlog and Mermaid stack view: `docs/research/pattern-harvest-agentic-architecture.md`.

## Planned
- Orchestrator-managed A2A routing for multi-agent chains with audit/trace.
- MCP ToolProvider integration for LangGraph executor; richer tool coverage under strict descriptors.

## Links
- Forward plan: `docs/ROADMAP.md` (tracks section).
- Fitness/CI contracts: `docs/tracks/TRACK_FITNESS_CI_CONTRACT.md`.
- Current A2A contract: `docs/contracts/A2A_CONTRACT_AND_TRACE.md`.
