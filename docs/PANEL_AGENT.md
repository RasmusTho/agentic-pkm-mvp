State: v5.0 – PanelAgent runtime V1 (promotion fan-out + AI-log on Reality-MVP base).
# PanelAgent / NoteInteractionAgent (Runtime v5.0)

Purpose: translate human-driven AI panels in vault notes into structured intents/events while keeping the panel simple, optional, and human-first.

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
- Reads the note from ObjectStore (vault mirror), not directly from the filesystem.
- Finds each AI panel, parses instruction + checkbox actions, enriches actions via `docs/settings/panel-actions.md` mappings, and emits **one** Outbox event per panel: `panel.intent.created`.
- Interprets checked actions and:
  - emits `panel.intent.executed` with per-action status,
  - emits `panel.action.triggered` for handled actions,
  - emits `panel.action.logged` for unmapped/unhandled actions (v5.x placeholders),
  - emits `promote.intent.created` when an action has `intent_type: promotion` (e.g. `promote.evergreen` mapping) so Promotion Agent flows can react,
  - emits `panel.log.created` and mirrors the same human-readable entry into the note’s `panel_logs` payload (AI-log/traceability).
- No LangGraph/planner/tool calls; this remains a lightweight runtime loop on top of Reality-MVP.

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
