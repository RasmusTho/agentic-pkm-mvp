State: Aligned (v4.10, with known debt — dispatch is flag-gated).
---
mappings:
  - text: "Promote this note"
    event_type: "promote.intent.created"
    payload_template:
      intent: "promote"
  - text: "Re-classify as Concept"
    event_type: "curation.classify.done"
  - text: "Mark as needs review"
    event_type: "curation.review.done"
    payload_template:
      allow: false
---

Fallback panel-action mappings used by `app.settings.panel_actions.load_panel_action_mappings` when no vault overrides exist (`vault/_system/panel-actions/*.md`). The PanelAgent turns newly checked checkboxes under `## AI-åtgärder` into `OutboxEvent` envelopes with:
- `event` = `event_type` above,
- `source` = `panel.agent`,
- payload containing `note_id`, `action_text`, optional `instruction_text`, plus any `payload_template`.

Event dispatch to Planner/Orchestrator is controlled by `PANEL_EVENTS_ENABLE`; when disabled, mappings still help enrich panel intents but no downstream plans are sent.
