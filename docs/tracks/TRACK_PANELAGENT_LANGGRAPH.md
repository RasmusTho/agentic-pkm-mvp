State: v5.6 — freeform catalog-driven proposal path delivered (instruction text → catalog discovery, no checkbox required).
# Track — PanelAgent LangGraph (v5.5)

Scope: PanelAgent evolution toward LangGraph inner loops with catalog-driven decider, planner/orchestrator integration, and watcher automation.

## Delivered
- PanelAgent Runtime V1 (v5.0 baseline) emits `panel.intent.created` → runtime → `panel.intent.executed` / `panel.action.*` / `panel.log.created`, and `promote.intent.created` for mapped promotion actions; AI logs persisted as `panel_logs`.
- Config-driven catalog + wiring: `docs/settings/panel-actions.md` + `docs/settings/panel-action-wiring.yaml` with precedence env > vault System/Config > repo default; invalid wiring falls back with warning.
- Decider modes: LLM-backed (default for runtime) and rule-based (`PANEL_AGENT_DECIDER=rule`, explicit opt-out for tests), both using the action catalog; checkboxes treated as hints in LLM mode.
- Planner pipeline (v5.5A): `PanelActionIntent` + opt-in planner mode (`PANEL_AGENT_PIPELINE=planner`) to create plans from panel actions.
- CLI-first orchestration (v5.5B): panel-originated plans executable via orchestrator + promotion tool; promotion consumer emits `promote.done` applying review_state/promotion metadata.

## Delivered (v5.5C)
- LangGraph decider hardening: LLM mode is default for runtime; rule mode (`PANEL_AGENT_DECIDER=rule`) is explicit opt-out for tests and deterministic validation lanes with automatic fallback to rule on LLM error; telemetry surfaces action selections and reasons in status counters; no external event-contract changes.

## Delivered (v5.6)
- Freeform catalog-driven proposal path: when a panel has an instruction but no checkbox actions, the LLM decider (`PANEL_AGENT_DECIDER=llm`) queries the full active catalog and selects canonical action IDs from instruction text alone. Proposals are validated against the catalog (out-of-catalog IDs dropped). Selected actions flow through the same execution gates as checkbox-derived actions. Fallback to rule mode on LLM error. Catalog entries now carry `llm_hint` for richer discovery prompts.

## Planned (forward line)
- Watcher auto-exec path for panel plans with safety limits (gated by concurrency/idempotency guards).
- Richer panel actions (summary/reply) with MCP/tool boundaries; A2A envelopes for planner/orchestrator integration.
- Multi-step workflows, uncertainty→suggested checkboxes (remaining PA2 items).

## Notes
- External contract unchanged: panel CLI and watcher flows remain policy-gated; decider defaults to LLM-backed intent interpretation in runtime; rule mode available as explicit opt-out for tests; planner/orchestrator path opt-in.
- Promotion intents are intent-only until consumer runs; status counters expose both intents and executions.

## Links
- Roadmap Now/Next: `docs/ROADMAP.md`.
- PanelAgent reference: `docs/PANEL_AGENT.md`.
- Watcher integration: `docs/tracks/TRACK_WATCHER.md`.
- Events: `docs/EVENTS.md` (panel.* / promote.* / promote.done).
