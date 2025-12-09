State: v5.0 – PanelAgent step 1 (runtime loop on Reality-MVP base).
# PanelAgent / NoteInteractionAgent (Runtime v5.0 step 1)

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

## Runtime (v5.0 step 1)
- Invocation: `python -m app.cli panel run --uuid <note_uuid>`.
- Reads the note from ObjectStore (vault mirror), not directly from the filesystem.
- Finds each AI panel, parses instruction + checkbox actions, enriches actions via `docs/settings/panel-actions.md` mappings, and emits **one** Outbox event per panel: `panel.intent.created`.
- No planners/tools are called in this step; it is introspective-only (read → parse → map → Outbox).

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

## Next steps (v5.0 step 2 ideas)
- Option A — pure fan-out: consume `panel.intent.created`, emit one `panel.action.intent.created` per checked action (still no tools), keeping AI-logg untouched.
- Option B — minimal orchestration: consume `panel.intent.created`, write human-readable previews back into `AI-logg` for visibility, while deferring real tool calls to later steps.
- These remain planned v5.x follow-ons in the roadmap (panel flows feeding Planner/Orchestrator once Reality-MVP is stable).
