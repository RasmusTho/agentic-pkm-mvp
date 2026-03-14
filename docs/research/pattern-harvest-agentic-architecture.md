State: offline synthesis (system not online); repo-grounded analysis only.
# Pattern Harvest — Agentic Architecture (Outer/Inner)

## 1) Purpose & Scope
- Brief: We’ll treat this as a targeted pattern-harvest for Yggdrasil/agentic-pkm-mvp: validate our current stratified model by mapping multi-agent best practices onto two layers — Outer Architecture (event choreography, outbox, A2A contracts, policy/guardrails, observability) and Inner Architecture (LangGraph AgentState, PER loops, tool invocation via MCP/tool interfaces). The goal is to extract the “highest leverage” patterns for our constraints (human-first, file/config-first, store abstraction, deterministic CI): event schema discipline; explicit A2A contracts; coherent tool layer boundary (MCP); observability & agent-ops; human-first config + validation/evals.
- Offline phase; output is docs/backlog only, no runtime wiring or new services. Evidence: this doc is scoped to documentation; no code changes accompany it.

## 2) Current Baseline Snapshot (Repo-grounded)
### Outer Architecture
- Outbox envelope carries `event`, `trace_id`, `timestamp`, `payload`, `meta` and is used for both the canonical DB outbox and the JSONL audit log. Evidence: app/events/schema.py (OutboxEvent model), app/services/outbox.py, app/index/outbox.py.
- Event catalogue includes panel/runtime events (`panel.intent.created`, `panel.intent.executed`, `panel.action.*`, `promote.intent.created`). Evidence: docs/EVENTS.md §PanelAgent events; docs/ARCHITECTURE.md SoT v5.0 PanelAgent Runtime V1 bullet.
- A2A message schema exists (request/response/error with sender/recipient/correlation/trace). Evidence: app/a2a/schema.py (AgentRequest/AgentResponse/AgentError).
- Audit logging used by orchestrator and agents via `audit_log(object_id, agent, action, trace_id, details)`. Evidence: app/agents/base/audit.py; app/orchestrator/events.py (audit_log in emit_step_started/finished/error).
- Import guardrails enforce agent boundary (no ingest/watcher/file internals from agents/panel runtime). Evidence: tests/architecture/test_outer_inner_boundaries.py.

### Inner Architecture
- ASK agent uses LangGraph with AgentState and PER-style steps in `app/agents/ask/graph.py`. Evidence: app/agents/ask/graph.py (state + graph nodes).
- PanelAgent uses LangGraph runtime (`graph.py`) and explicit PanelAgentState; actions interpreted to events. Evidence: app/agents/panel_agent/graph.py; app/agents/panel_agent/state.py.
- Planner/Orchestrator plans/exec: Plan/PlanStep schemas and MockPlanExecutor for deterministic execution. Evidence: app/planner/schema.py; app/orchestrator/executor.py (MockPlanExecutor).

### Configuration & Governance
- Panel action catalog mappings defined in docs/settings/panel-actions.md (ids, intent_type, downstream_event, params). Evidence: docs/settings/panel-actions.md.
- Watcher auto-run policy treats AI-fenced notes as candidates once `WATCHER_AUTO_EXEC=1` is armed; only `ai_panel_auto_run: never` / `ai_panel: { auto_run: never }` blocks the automation. Evidence: docs/HUMAN-FLOWS.md §PanelAgent runtime + watcher integration (policy gating).
- CLI flags/environment documented for ingest/panel/watcher settings. Evidence: docs/OPERATIONS.md (stable commands/runbooks) and docs/HUMAN-FLOWS.md (watcher notes).
- Panel action wiring now config-driven via YAML (`docs/settings/panel-action-wiring.yaml`), defaulting to promotion events; override with `PANEL_ACTION_WIRING_PATH`. Evidence: app/agents/panel_agent/wiring.py; docs/settings/panel-action-wiring.yaml.

### Observability & AgentOps
- Audit JSONL writer and ring snapshot underpin agent audit trail. Evidence: app/agents/base/audit.py (audit_log, _audit_ring_snapshot).
- Orchestrator emits `orchestrator.step.*` and MCP tool call events for execution tracing. Evidence: app/orchestrator/events.py (emit_step_started/finished/error, emit_mcp_tool_call_*).
- Status/operational snapshot maintained in docs/STATUS.md (SoT tables and notes). Evidence: docs/STATUS.md table.

### Docker/Runtime Posture
- Base compose defines db/api/worker services mounting repo; STORE_BACKEND=pg in containers. Evidence: docker-compose.yaml (services db/api/worker).
- Watcher compose for polling daemon mounts vault to /vault and /state for snapshots. Evidence: docker-compose.watcher.yml (watcher service command/volumes).
- Docker usage not primary human interface; CLI exposed via python -m app.cli. Evidence: docs/OPERATIONS.md and docs/HUMAN-FLOWS.md.
- Watcher daemon supports snapshot outside vault via --snapshot-path (/state default in Docker). Evidence: app/cli/watcher.py (vault-watcher-daemon), app/watcher/vault_watcher.py (run_watcher_daemon).

## 3) Pattern Harvest Cards

### Card A — Event schema discipline
- Pattern: Stable, versioned event envelopes with trace_id/idempotency and clear retry/DLQ semantics; shared naming conventions.
- Our Current State: OutboxEvent envelope (`event`, `trace_id`, `timestamp`, `payload`, `meta`). Evidence: app/events/schema.py. Panel events listed with names/payloads. Evidence: docs/EVENTS.md §PanelAgent events. No explicit versioning/idempotency fields beyond event_id. Evidence: app/events/schema.py (event_id default).
- Gap / Risk: No documented versioning policy or DLQ/retry contract for outbox consumers (Unknown for retries).
- Recommendation: Define event naming/version policy + idempotency keys in docs; add schema lint in CI; document DLQ/poison handling expectations for outbox replayers.
- Acceptance Criteria: 
  - Docs page enumerates event naming/version rules and idempotency guidance.
  - CI check validates event schema files/envelopes for required fields + version tag.
  - Outbox consumer contract doc mentions retry/DLQ expectations and trace propagation.

### Card B — A2A contracts
- Pattern: Explicit request/response/error envelopes with correlation_id, timeouts, and error taxonomy; async event hooks for long-running flows.
- Our Current State: AgentRequest/AgentResponse/AgentError schemas with sender/recipient/correlation_id/trace_id. Evidence: app/a2a/schema.py. A2A events audit logging present. Evidence: app/a2a/events.py (audit_log on agent messages).
- Gap / Risk: No documented SLAs/timeouts or routing policy; unclear how A2A integrates with planner/orchestrator in production (Unknown).
- Recommendation: Publish A2A contract doc (routing, retries, expected intents), add sample traces, and align planner/orchestrator usage with a minimal contract for panel/planner/orchestrator chain.
- Acceptance Criteria:
  - A2A contract doc with routing/timeout/error taxonomy published.
  - Example trace in docs showing correlation_id + trace_id across agents.
  - Lint or schema check ensuring A2A messages carry correlation_id + trace_id.

### Card C — Tool layer boundary (MCP/tools)
- Pattern: Tool registry with allowed args, permissions, timeouts; adapters testable without live backends; MCP boundary respected.
- Our Current State: Tool descriptors with allowed_args/mock_result (e.g., mcp.vault.append_note, internal.ingest_external, promotion.emit_intent). Evidence: app/planner/tools.py. MockPlanExecutor validates args and emits MCP tool call events. Evidence: app/orchestrator/executor.py (_validate_tool_args/_validate_required_args, emit_mcp_tool_call_*). Tools invoked from inner graphs (ASK/PanelAgent) via orchestrator/planner mocks. Evidence: docs/ARCHITECTURE.md tool note; app/agents/panel_agent/graph.py uses call_llm, not MCP.
- Gap / Risk: Permissions/timeout policy not documented; MCP boundary not formalized; tool side-effects beyond append_note/promotion emit not described (Unknown).
- Recommendation: Define tool policy (allow/deny, timeouts, audit) and MCP adapter contract; add fixture-based tests for tool descriptors and arg validation; document promotion tool side-effects.
- Acceptance Criteria:
  - Tool policy doc with permissions/timeout defaults and audit expectations.
  - Test coverage ensures each tool descriptor has allowed_args/mock_result and arg validation enforced.
  - MCP boundary diagram + adapter contract recorded in docs.

### Card D — Observability & AgentOps
- Pattern: Unified audit + metrics surface per agent/tool; runbooks for error handling; trace propagation enforced.
- Our Current State: audit_log writes JSONL with object_id/agent/action/trace_id; orchestrator emits step/tool events; status snapshot tracked in docs/STATUS.md. Evidence: app/agents/base/audit.py; app/orchestrator/events.py; docs/STATUS.md.
- Gap / Risk: Metrics/alerting not documented; audit retention/rotation unspecified; no runbook for watcher/panel/orchestrator failures (Unknown for alerting).
- Recommendation: Document observability stack for agents (audit locations, optional metrics hooks, trace_id requirements), add runbook stubs for panel/watcher/orchestrator incident steps, and codify trace propagation requirement in CI lint.
- Acceptance Criteria:
  - Observability/AgentOps doc with audit paths, trace propagation rules, and troubleshooting steps.
  - Runbook stubs for panel/watcher/orchestrator errors added to ops docs.
  - CI lint that fails when events/agent logs omit trace_id.

### Card E — Human-first config + validation/evals
- Pattern: File-first configuration (vault/system folder) with validation; regression evals gated; CLI only as tooling surface.
- Our Current State: Panel action catalog defined in docs/settings/panel-actions.md; watcher policy via note frontmatter. Evidence: docs/settings/panel-actions.md; docs/HUMAN-FLOWS.md policy section. CLI documented as tooling surface for ingest/panel/watcher. Evidence: docs/OPERATIONS.md command/runbook sections. Eval stack (DeepEval/Ragas) present but optional via markers/env. Evidence: docs/TESTING.md (PanelAgent LLM E2E opt-in; eval markers).
- Gap / Risk: No explicit “CLI not primary UI” statement in architecture docs; config validation limited; eval gates optional (mock by default).
- Recommendation: Add explicit statement in architecture/human-flows that CLI is tooling, not human UI; add schema validation for panel-actions and watcher config; document eval gating with local providers.
- Acceptance Criteria:
  - Architecture/HUMAN-FLOWS updated with “CLI is tooling surface” statement.
  - Config validation step for panel-actions and watcher settings (doc + test).
  - Eval doc describing optional runs and provider requirements; CI ensures eval tests are skipped unless configured.

## 4) Architecture Stack Diagram (Mermaid)
```mermaid
flowchart LR
    subgraph Config["Config (vault frontmatter, docs/settings/*)"]
        FM[Frontmatter policy\n(panel auto-run, uuids)]
        PA[panel-actions catalog\n(docs/settings/panel-actions.md)]
    end

    subgraph Stores["Stores / Components"]
        OS[ObjectStore]
        PS[PlanStore]
        VI[VectorIndex]
    end

    subgraph Outer["Outer Architecture"]
        OB[Outbox events\n(event, trace_id, payload, meta)]
        A2A[A2A envelopes\n(request/response/error)]
        OBS[Audit/Observability\n(audit_log, orchestrator.step)]
        POL[Policy/Guardrails\n(frontmatter gates, max-notes)]
    end

    subgraph Inner["Inner Architecture (per agent)"]
        ASK[ASK LangGraph\nAgentState]
        PANEL[PanelAgent LangGraph\nPanelAgentState]
        PLAN[Planner\nPlan/PlanStep]
        ORCH[Orchestrator\nMockPlanExecutor]
    end

    subgraph Tools["Tool Layer"]
        MCP[mcp.vault.append_note\nToolDescriptor]
        PROMO[promotion.emit_intent\ninternal tool]
        ING[internal.ingest_external]
    end

    subgraph Docker["Docker Runtime Boundary"]
        API[api/worker containers]
        WATCH[watcher daemon\n(/vault mount, /state snapshot)]
    end

    Config --> Outer
    Config --> Inner
    Inner --> Tools
    Outer --> Stores
    Inner --> Stores
    Outer <---> Tools
    Docker --- Outer
    Docker --- Inner
    Docker --- Tools
```

## 5) Backlog Candidates (Prioritized)
1) Event schema & versioning doc (Docs, Offline now): Publish naming/version/idempotency guidance with DLQ/retry expectations; AC: doc with examples, CI lint validating required fields, trace_id/idempotency mention.
2) A2A contract & trace example (Docs, Offline now): Document routing/timeout/error taxonomy plus sample trace; AC: doc page, example payload chain, correlation_id/trace_id lint.
3) Tool policy & MCP adapter spec (Docs/CI, Offline now): Define allow/deny/timeout/audit rules; AC: policy doc, descriptor completeness check in CI, adapter contract note.
4) Observability runbooks (Docs, Offline now): Add runbooks for panel/watcher/orchestrator failures; AC: runbook sections, trace_id requirement callout, audit path references.
5) Config validation for panel-actions/watcher (Docs/CI, Offline now): Describe schema validation and add test/lint to reject invalid mappings; AC: doc, schema file, CI check.
6) CLI-is-tooling statement (Docs, Offline now): Update architecture/human-flows to assert CLI is agent/automation surface, not human UI; AC: statement in docs, cross-link from CLI reference.
7) Docker friction log (Docs, Offline now): Capture container runtime gaps (state paths, permissions, observability) as explicit backlog; AC: backlog list in ops/research, with acceptance test ideas.
8) Eval gating guidance (Docs, Offline now): Document eval modes (mock/skip/live) and provider requirements; AC: doc page snippet, env examples, CI ensures eval tests skip when unset.
9) Outbox consumer contract (Docs, Offline now): Define expected consumer behaviour (ordering, retries, DLQ); AC: contract doc, example consumer pseudocode, idempotency key guidance.
10) MCP/tool test harness (CI/Docs, Offline later): Add deterministic harness for tool adapters; AC: tests using mock executor, coverage report, documented usage.

## 6) Open Questions / Missing Evidence
- DLQ/retry semantics for outbox consumers not documented (Unknown).
- Tool permission/timeout policy unspecified (Unknown).
- A2A routing/runtime usage in production not described (Unknown).
- Metrics/alerting stack for agents/orchestrator not found (Unknown).
- Explicit statement that CLI is not a primary human UI absent from current architecture docs (gap to address).
