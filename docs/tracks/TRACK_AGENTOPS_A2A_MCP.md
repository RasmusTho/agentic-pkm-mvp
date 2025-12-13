State: Pattern harvest documented; A2A/MCP orchestration scaffolding planned; mocks/determinism in place.
# Track — AgentOps, A2A, MCP

Scope: outer agent coordination, event/A2A contracts, tool/MCP boundaries, and observability/ops hardening.

## Architecture hardening themes
- Event schema discipline: naming/versioning/idempotency/trace_id; DLQ/retry thinking captured in `docs/research/pattern-harvest-agentic-architecture.md`.
- A2A contracts: envelope schema (`agent.request.created` / `agent.response.created` / `agent.error`) with traceability; orchestration-managed routing planned.
- Tool boundary: MCP descriptor registry with allowed_args + mock_result; deterministic adapters; permission/timeouts documented.
- Observability & agent-ops: audit events/metrics/runbooks for panel/watcher/orchestrator; CLI is tooling (not UI).
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
