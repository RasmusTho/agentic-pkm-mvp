State: SoT v4.10 Reality-MVP (current core).
# PanelAgent / NoteInteractionAgent (Reality-MVP)

Purpose: translate human-driven AI panels in vault notes into internal intents/events while keeping the panel simple, optional, and human-first.

## Panel syntax (Markdown)
- Panels are delimited by tolerant AI fences: any `%% ...ai... %%` (case-insensitive) line opens/closes a panel. First fence opens, second closes, third opens the next, etc.
- Inside a panel:
  - `## AI instruction` — free-text instruction from the human.
  - `## AI actions` — markdown checkboxes (`- [ ] ...` / `- [x] ...`) for discrete actions.
  - `## AI log` — append-only bullet log of prior system actions.
- Legacy notes that only use the headings without fences are still parsed; new panels should use fences.
- Panel content is not indexed or used as knowledge.

Example:
```
%% AI:Start %%
## AI instruction
Please promote this note after verifying the summary.
## AI actions
- [ ] Promote this note
- [x] Re-classify as Concept
## AI log
- Action: "Re-classify as Concept" (2025-03-01 10:00)
%% AI:End %%
```

## Parsing model
- `app/agents/panel/parser.py` → `PanelState` (instruction text, actions, logs, spans, fenced flag).
- `PanelAction`: `checked`, `text`.
- `PanelLogEntry`: raw log line (append-only).

## Action mapping → events
- Mappings come from `vault/_system/panel-actions/*.md` (or `docs/settings/panel-actions*` fallback) via `app.settings.panel_actions`.
- `app/agents/panel/events.py` maps triggered actions to `OutboxEvent` using the canonical envelope (`event`, `trace_id`, `source="panel.agent"`, `timestamp`, `payload`, `meta`).
- Minimal payload: `note_id`, `action_text`, plus any mapping `payload_template`; `instruction_text` is included when present.
- Event dispatch to Planner/Orchestrator is flag-gated via `PANEL_EVENTS_ENABLE`/`panel_events_enable`; without it the agent still rewrites panels and surfaces intents but does not emit downstream plans.

## Agent flow (minimal, deterministic)
- `handle_note_update(note_id, old_markdown, new_markdown, mappings)`:
  1. Parse old/new panels.
  2. Diff to find newly checked actions (`PanelIntent`).
  3. Enrich intents via mappings, convert to `OutboxEvent`.
  4. Remove triggered actions from the panel and append simple log entries.
- The agent is stateless; panel edits drive intent emission. Panel text remains the human-facing control surface.

## Contract tests
- Parser/agent behaviour is covered under `tests/panel/*`.
- Outbox envelope is enforced separately in `tests/architecture/test_events_outbox_contracts.py`.
