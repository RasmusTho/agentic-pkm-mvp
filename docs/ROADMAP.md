State: Locked baseline SoT v4.10 (Reality-MVP) with the active forward line tracked through v5.5 (PanelAgent planner pipeline + CLI-first orchestration).
# Roadmap — Forward Line Only

This roadmap is forward-looking. Historical 4.x ladder details now live in `docs/history/SOT_4X_HISTORY.md`. Delivered/current truth lives in `docs/ARCHITECTURE.md` and `docs/STATUS.md`.

## Baselines
- **SoT v4.10 (locked baseline)** — Reality-MVP: stable vault ingest, minimal external ingest, ASK API, observability + interim GUI, orchestrator runtime V1. No changes to scope or acceptance.
- **SoT v5.0+ (forward line)** — PanelAgent runtime + watcher track on top of v4.10. Forward line currently tracked through **v5.5B** (planner pipeline + CLI-first orchestration with promotion consumer).

## Now / Next (2–4 increments)
1) **PanelAgent LangGraph decider + watcher auto-exec (v5.5C, planned)**
   - LangGraph-driven decider turned on safely (`PANEL_AGENT_DECIDER=llm`), with watcher auto-execution gated by policy.
   - Acceptance: panel runs in watcher produce the same events as direct runs; LLM branch is opt-in and audited; CI still deterministic by default.
2) **Watcher → Panel → Planner/Orchestrator automation (v5.5D, planned)**
   - Execute panel-created plans automatically under watcher control (with safety limits); promotion consumer remains opt-in but observable.
   - Acceptance: watcher summary + status counters reflect plan creation + execution; promotion intents and executions remain idempotent.
3) **Vault-as-GUI Settings Architecture (v5.6 track, planned)**
   - Human-editable settings in the vault (`@Settings/`/System/Config) compiled to typed artifacts; schema validation + hot reload.
   - Acceptance: compiler CLI, schema checks in CI, deterministic artifacts, vault-first precedence over repo defaults.
4) **LangGraph rollout to additional agents (v5.6)**
   - Add AgentState + LangGraph graphs to 1–2 agents (Promotion, Reviewer, Hygiene); move decision logic from pipelines into graphs while keeping event/A2A outer contracts.

## Delivered (v5.x forward line)
- **PanelAgent Runtime V1 (v5.0)** — parses AI panels, emits `panel.intent.created`, runtime emits `panel.intent.executed`/`panel.action.*`/`panel.log.created`, fans out `promote.intent.created`.
- **Watcher track (v5.1–v5.4)** — targeted ingest (`ingest-vault-paths`), panel run-many CLI, snapshot-based `vault-watcher-run`, policy-gated auto-panel (`ai_panel_auto_run`), dry-run + max-notes + structured summaries.
- **Panel planner pipeline (v5.5A/B)** — `PanelActionIntent`, planner-mode pipeline creating plans from panel actions, CLI-first orchestration to execute panel plans with promotion tool + consumer emitting `promote.done`; status counters track intents and executions.

## Tracks (forward-looking)
- **PanelAgent / Planner / Orchestrator** — converge on LangGraph inner per agent, planner-mode default, orchestrator execution auditable via events and status counters; watcher auto-exec next.
- **Watcher deployment** — Docker-first `vault-watcher-daemon` with snapshot outside vault (`/state`); host service fallback for iCloud/Obsidian mounts; auto-panel stays policy-gated.
- **Config & validation** — vault-first wiring (`System/Config/panel-action-wiring.yaml`) with schema validation; future Vault-as-GUI compiler to make settings human-first and typed.
- **Architecture hardening** — event schema discipline, A2A/tool boundaries, observability runbooks, and eval gating captured in `docs/research/pattern-harvest-agentic-architecture.md`.

## Links
- Historical ladder and objectives: `docs/history/SOT_4X_HISTORY.md`
- Current architecture truth: `docs/ARCHITECTURE.md`
- Operational snapshot and counters: `docs/STATUS.md`
