State: v5.5B delivered (planner pipeline + CLI-first orchestration + promotion consumer); v5.5C decider in progress.
# Track — PanelAgent LangGraph (v5.5)

Scope: PanelAgent evolution toward LangGraph inner loops with catalog-driven decider, planner/orchestrator integration, and watcher automation.

## Delivered
- PanelAgent Runtime V1 (v5.0 baseline) emits `panel.intent.created` → runtime → `panel.intent.executed` / `panel.action.*` / `panel.log.created`, and `promote.intent.created` for mapped promotion actions; AI logs persisted as `panel_logs`.
- Config-driven catalog + wiring: `docs/settings/panel-actions.md` + `docs/settings/panel-action-wiring.yaml` with precedence env > vault System/Config > repo default; invalid wiring falls back with warning.
- Decider modes: rule (default, deterministic) and opt-in LLM (`PANEL_AGENT_DECIDER=llm`), both using the action catalog; checkboxes treated as hints in LLM mode.
- Planner pipeline (v5.5A): `PanelActionIntent` + opt-in planner mode (`PANEL_AGENT_PIPELINE=planner`) to create plans from panel actions.
- CLI-first orchestration (v5.5B): panel-originated plans executable via orchestrator + promotion tool; promotion consumer emits `promote.done` applying review_state/promotion metadata.

## In progress (v5.5C)
- LangGraph decider hardening and default readiness; rule remains default while LLM mode stays opt-in.

## Planned (forward line)
- Watcher auto-exec path for panel plans with safety limits (gated by concurrency/idempotency guards).
- Richer panel actions (summary/reply) with MCP/tool boundaries; A2A envelopes for planner/orchestrator integration.

## Notes
- External contract unchanged: panel CLI and watcher flows remain policy-gated; decider defaults to rule; planner/orchestrator path opt-in.
- Promotion intents are intent-only until consumer runs; status counters expose both intents and executions.

## Links
- Roadmap Now/Next: `docs/ROADMAP.md`.
- PanelAgent reference: `docs/PANEL_AGENT.md`.
- Watcher integration: `docs/tracks/TRACK_WATCHER.md`.
- Events: `docs/EVENTS.md` (panel.* / promote.* / promote.done).
