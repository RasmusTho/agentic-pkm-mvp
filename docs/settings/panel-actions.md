---
State: v5.5 – PanelAgent catalog (LLM decider opt-in; rule-mode default).
mappings:
  - id: "promote.evergreen"
    kind: "promotion"
    labels:
      - "Gör denna anteckning evergreen"
      - "Make this note evergreen"
    description: "Promote the note to evergreen maturity."
    intent_type: "promotion"
    downstream_event: "review.promote.evergreen"
    params:
      maturity: "evergreen"
  - id: "note.archive"
    kind: "archival"
    labels:
      - "Arkivera den här anteckningen"
      - "Archive this note"
    description: "Archive the note without promotion."
    intent_type: "archival"
    downstream_event: "note.archive"
  - id: "ingest.summary.create"
    kind: "ingest"
    labels:
      - "Skapa en separat sammanfattningsanteckning"
      - "Create a separate summary note"
    description: "Create a sibling summary note for this content."
    intent_type: "ingest"
    downstream_event: "ingest.summary.create"
---

PanelAgent action catalog (canonical source for AI panel actions).
- `id`: canonical action id (e.g., `promote.evergreen`, `note.archive`).
- `kind`: category of action (promotion, ingest, hygiene, chat, zone).
- `labels`: human-facing labels/synonyms shown in panels; used as hints, not strict matches.
- `description` / `llm_hint`: short explanation for prompts.
- `intent_type` + `downstream_event`: determine runtime event fan-out (promotion emits `promote.intent.created`).
- `params`: structured parameters for the downstream event (e.g., `maturity: evergreen`).

Rule-mode continues to match checkbox labels against this catalog deterministically. LLM-mode (opt-in) uses the same catalog plus panel/note context to choose actions; checkboxes are treated as hints.
