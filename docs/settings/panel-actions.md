---
State: v5.0 – PanelAgent runtime V1 (promotion fan-out).
mappings:
  - id: "promote.evergreen"
    label: "Gör denna anteckning evergreen"
    text: "Gör denna anteckning evergreen"
    intent_type: "promotion"
    downstream_event: "review.promote.evergreen"
    event_type: "review.promote.evergreen"
    params:
      maturity: "evergreen"
  - id: "note.archive"
    label: "Arkivera den här anteckningen"
    text: "Arkivera den här anteckningen"
    intent_type: "archival"
    downstream_event: "note.archive"
    event_type: "note.archive"
  - id: "ingest.summary.create"
    label: "Skapa en separat sammanfattningsanteckning"
    text: "Skapa en separat sammanfattningsanteckning"
    intent_type: "ingest"
    downstream_event: "ingest.summary.create"
    event_type: "ingest.summary.create"
---

Human-first reference mappings that connect checkbox text under `## AI-åtgärder` to structured event types.
Runtime V1 uses `intent_type: promotion` mappings (e.g. `promote.evergreen`) to emit `promote.intent.created`; other mapped actions are logged for future v5.x handling.
