State: v5.0 – PanelAgent runtime V1 (promotion fan-out + AI-log on Reality-MVP base).
# PanelAgent / NoteInteractionAgent (Runtime v5.0)

Purpose: translate human-driven AI panels in vault notes into structured intents/events while keeping the panel simple, optional, and human-first.

## PanelAgent Runtime V1 (current baseline)
- SoT v5.0 baseline built on top of the locked v4.10 Reality-MVP.
- Runtime V1 uses a fixed mapping from panel actions to follow-up events (e.g., promotion intents) and mirrors them into `panel_logs` for traceability.
- This is a simplified bridge/runtime loop, not the final agentic design; it keeps watcher and manual panel flows working while the agent migrates to LangGraph.
- Internal implementation now runs through a LangGraph-based control flow (`PanelAgentState`), but external behaviour and emitted events remain identical.
- Planner pipeline (opt-in, `PANEL_AGENT_PIPELINE=planner`): PanelAgent builds a `PanelActionIntent` and asks the Planner to create a plan for the selected actions. Plans can now be executed via the Orchestrator using the CLI (`python -m app.cli panel-orchestrate-plan --plan-id <plan_id>`), while the default direct path remains unchanged.
- Action catalog (`docs/settings/panel-actions.md`) is the canonical list of actions (id, kind, labels/synonyms, description/llm_hint, downstream event, params). Rule-mode matches checkbox labels deterministically; LLM-mode is opt-in and uses the catalog + panel/note context with checkboxes as hints.

## PanelAgent 2.0 (planned v5.5)
- Introduces an explicit `PanelAgentState` (note reference, panel intent, actions, history, policy) and drives behaviour from a LangGraph graph (e.g., `graph.py`).
- LLM-based reasoning decides which panel actions to execute (and in what order) rather than relying on fixed mappings.
- Planner/Orchestrator integration (A2A/plan objects) executes chosen actions (promotion, summaries, hygiene) with the same guardrails as other agents.
- PanelAgent Runtime V1 remains the baseline until this LangGraph-driven 2.0 path is implemented and proven in production.
- LangGraph control flow now supports a decider mode (`PANEL_AGENT_DECIDER=rule|llm`); `rule` remains the default to preserve current behaviour, while `llm` is an opt-in, experimental action selector using the shared LLM provider.
- LLM-driven contract tests live under `tests/e2e/test_panel_llm_e2e.py` (gated by `@pytest.mark.panel_llm_e2e` and `PANEL_AGENT_LLM_E2E=1`) to validate end-to-end promotion/non-promotion scenarios using the real decider.

## Panel syntax (Markdown)
- Panels are delimited by tolerant AI fences: any `%% ...ai... %%` (case-insensitive) line opens/closes a panel. First fence opens, second closes, third opens the next, etc.
- Inside a panel:
  - `## AI-instruktion` — free-text instruction from the human.
  - `## AI-åtgärder` — markdown checkboxes (`- [ ] ...` / `- [x] ...`) for discrete actions.
  - `## AI-logg` — append-only bullet log of prior system actions.
- Legacy notes that only use the headings without fences are still parsed; new panels should use fences.
- Panel content is not indexed or used as knowledge.

Example:
```
%% AI:Start %%
## AI-instruktion
Please promote this note after verifying the summary.
## AI-åtgärder
- [ ] Promote this note
- [x] Re-classify as Concept
## AI-logg
- Action: "Re-classify as Concept" (2025-03-01 10:00)
%% AI:End %%
```

## Runtime V1 (fan-out, promotion intent, AI-log)
- Invocation: `python -m app.cli panel run --uuid <note_uuid>` (default runs the runtime loop). Use `--emit-only` to keep legacy “emit-only” behaviour without executing runtime actions.
- Multi-note invocation: `python -m app.cli panel run-many <uuid> [<uuid> ...]` (default runs runtime; `--emit-only` supported). Used by watcher flows; auto-run policy gates watcher-driven calls.
- Reads the note from ObjectStore (vault mirror), not directly from the filesystem.
- Finds each AI panel, parses instruction + checkbox actions, enriches actions via `docs/settings/panel-actions.md` mappings, and emits **one** Outbox event per panel: `panel.intent.created`.
- Interprets checked actions and:
  - emits `panel.intent.executed` with per-action status,
  - emits `panel.action.triggered` for handled actions,
  - emits `panel.action.logged` for unmapped/unhandled actions (v5.x placeholders),
  - emits `promote.intent.created` when an action has `intent_type: promotion` (e.g. `promote.evergreen` mapping) so Promotion Agent flows can react,
  - emits `panel.log.created` and mirrors the same human-readable entry into the note’s `panel_logs` payload (AI-log/traceability).
- No LangGraph/planner/tool calls; this remains a lightweight runtime loop on top of Reality-MVP.
- Auto-run policy (SoT v5.3, watcher-facing): watchers only auto-run panels when the note explicitly allows it via frontmatter, e.g.:
  - `ai_panel_auto_run: watcher` (watcher may auto-run panel runtime)
  - `ai_panel_auto_run: manual` or missing (default, watcher skips; manual CLI still allowed)
  - `ai_panel_auto_run: never` (watcher must not auto-run; manual CLI still allowed)
  - Nested form also supported: `ai_panel: { auto_run: watcher|manual|never }`
  Manual CLI commands (`panel run`, `panel run-many`) ignore the policy; it gates watcher-driven automation only.

### Planner pipeline (opt-in)
- `PANEL_AGENT_PIPELINE=planner` keeps the external runtime behaviour the same and also builds a `PanelActionIntent` for triggered actions, storing a plan via Planner (`plan_panel_actions`).
- Plans include promotion steps mapped to the `promotion.emit_intent` tool. They can be executed via Orchestrator in a CLI-first path: `python -m app.cli panel-orchestrate-plan --plan-id <plan_id>`. Watcher-driven execution remains off for now.
- Decider and pipeline are orthogonal toggles:
  - `PANEL_AGENT_DECIDER=rule|llm` selects how actions are chosen (default `rule`).
  - `PANEL_AGENT_PIPELINE=direct|planner` selects whether to emit promotion directly (default) or also create plans (planner mode).

## UAT / Trying it out
- The quickest way to exercise PanelAgent + watcher flows on a small set of notes is in `docs/UAT_PANEL_WATCHER.md` (prep notes, targeted ingest, panel run-many, watcher dry-run/run, and what to observe).

### Event payload (panel.intent.created)
```json
{
  "event": "panel.intent.created",
  "version": "1.0",
  "source": {"component": "panel_agent", "trigger": "cli", "sot": "v5.0-step1"},
  "payload": {
    "note": {"uuid": "NOTE-UUID", "path": "vault/Note.md", "origin": "vault"},
    "panel": {"panel_id": "panel-1", "instruction": "Do the thing"},
    "actions": [
      {
        "id": "promote.evergreen",
        "label": "Gör denna anteckning evergreen",
        "checked": true,
        "mapping": {
          "intent_type": "promotion",
          "downstream_event": "review.promote.evergreen",
          "params": {"maturity": "evergreen"}
        }
      },
      {"id": "unknown-action", "label": "Other", "checked": false, "mapping": null}
    ]
  }
}
```

### Derived runtime events
- `panel.intent.executed` — payload `{note, panel, actions:[{id,label,checked,status,emitted_events}]}` (source `panel_agent` / trigger `runtime`).
- `panel.action.triggered` — payload `{note, panel_id, action:{id,label}, target_event}` for handled actions.
- `panel.action.logged` — payload `{note, panel_id, action:{id,label,checked}, reason, mapping?}` for unmapped/unimplemented actions.
- `promote.intent.created` — payload includes `{note, panel, action, instruction, maturity}`; emitted when a checked action has `intent_type: promotion`.
- `panel.log.created` — payload is a human-readable log entry (`summary`, `note`, `panel_id`, `actions`) also mirrored into `panel_logs` on the note object.

## Wiring configuration
- Default wiring: `docs/settings/panel-action-wiring.yaml` (maps canonical action ids to target events).
- Resolution order: `PANEL_ACTION_WIRING_PATH` env override > `VAULT_ROOT/System/Config/panel-action-wiring.yaml` > repo default.
- Validation: config must define an `actions` list with `id`, `kind` (event|intent, defaults to event), and `event_type`/`target_event` (or `intent_type`). Unknown/invalid configs emit a warning and fall back to the default wiring; runtime behaviour stays unchanged.
- CLI/Watcher use the same wiring; panel decider (rule/LLM) still selects actions, wiring only controls emitted events.

Promotion intents (`promote.intent.created`) represent intent-only; apply effects by running the promotion consumer (`python -m app.cli promote-consume`), which emits `promote.done` when successful.
