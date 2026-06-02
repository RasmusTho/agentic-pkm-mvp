---
State: v5.6 – PanelAgent catalog (LLM-backed intent interpretation default; rule-mode opt-out for tests; freeform discovery via llm_hint; proposal-only cognitive capabilities added per #982).
mappings:
  - id: "promote.evergreen"
    kind: "promotion"
    labels:
      - "Gör denna anteckning evergreen"
      - "Make this note evergreen"
    description: "Promote the note to evergreen maturity."
    llm_hint: "Choose this when the instruction asks to promote, make evergreen, or mature the note."
    intent_type: "promotion"
    trust_verb: "APPLY"
    downstream_event: "review.promote.evergreen"
    capability_class: "governed_execution"
    authority_class: "governed_effect"
    requires_human_gate: true
    params:
      maturity: "evergreen"
  - id: "note.archive"
    kind: "archival"
    labels:
      - "Arkivera den här anteckningen"
      - "Archive this note"
    description: "Archive the note without promotion."
    llm_hint: "Choose this when the instruction asks to archive or retire the note."
    intent_type: "archival"
    downstream_event: "note.archive"
    capability_class: "governed_execution"
    authority_class: "governed_effect"
    requires_human_gate: true
  - id: "ingest.summary.create"
    kind: "ingest"
    labels:
      - "Skapa en separat sammanfattningsanteckning"
      - "Create a separate summary note"
    description: "Create a sibling summary note for this content."
    llm_hint: "Choose this when the instruction asks to summarize the note into a separate document."
    intent_type: "ingest"
    downstream_event: "ingest.summary.create"
    capability_class: "governed_execution"
    authority_class: "governed_effect"
    requires_human_gate: true
  - id: "note.move.workbench"
    kind: "zone"
    labels:
      - "Flytta den här anteckningen till Workbench"
      - "Move this note to Workbench"
      - "Move this note to the workbench folder"
    description: "Move the note from Inbox to Workbench logical zone."
    llm_hint: "Choose this when the instruction asks to move the note to Workbench or the workbench folder."
    intent_type: "zone_move"
    trust_verb: "APPLY"
    downstream_event: "note.move.workbench"
    capability_class: "governed_execution"
    authority_class: "governed_effect"
    requires_human_gate: true
    params:
      source_zone: "inbox"
      destination_zone: "workbench"
  - id: "queue_review"
    kind: "note_lifecycle"
    labels:
      - "Köa den här anteckningen för granskning"
      - "Queue this note for review"
      - "Queue for review"
    description: "Stage a governed review proposal for this note without mutating review_state."
    llm_hint: "Choose this when the instruction asks to queue, schedule, or stage the note for review."
    intent_type: "note_lifecycle"
    trust_verb: "APPLY"
    downstream_event: "panel.governance.requested"
    capability_class: "governed_execution"
    authority_class: "governed_effect"
    requires_human_gate: true
    params:
      operation: "queue_review"
  # ---------------------------------------------------------------------------
  # Proposal-only cognitive capabilities (#982).
  #
  # These entries surface bounded orientation / retrieval / clarification /
  # proposal moves for PanelAgent. They are non-governance-bearing per
  # docs/CAPABILITY_CONTRACT_MODEL.md (`Cognitive mediation capability
  # classes`): authority_class is `read-only` or `proposal`, they never
  # mutate the vault, and their downstream events are observational
  # (`panel.proposal.*` / `panel.retrieval.*`). The PanelAgent governance
  # gate (_is_governance_bearing) treats these as non-governance-bearing
  # and allows same-pass execution when explicitly selected.
  # ---------------------------------------------------------------------------
  - id: "proposal.note_diagnosis"
    kind: "proposal"
    labels:
      - "Diagnosticera den här anteckningen"
      - "Diagnose this note"
    description: "Return a bounded diagnosis of the note's current state (what is unclear, what is unresolved, what is incomplete)."
    llm_hint: "Choose this when the instruction asks for an assessment, diagnosis, or what's wrong/unclear about the note."
    intent_type: "proposal"
    downstream_event: "panel.proposal.note_diagnosis"
    capability_class: "proposal"
    authority_class: "proposal"
    requires_human_gate: false
  - id: "proposal.next_actions"
    kind: "proposal"
    labels:
      - "Föreslå nästa steg"
      - "Suggest next actions"
    description: "Propose a small, bounded set of next-step suggestions for the human to consider."
    llm_hint: "Choose this when the instruction asks what to do next, for next steps, or for action suggestions."
    intent_type: "proposal"
    downstream_event: "panel.proposal.next_actions"
    capability_class: "proposal"
    authority_class: "proposal"
    requires_human_gate: false
  - id: "proposal.clarifying_questions"
    kind: "clarification"
    labels:
      - "Ställ förtydligande frågor"
      - "Ask clarifying questions"
    description: "Return clarifying questions the human can answer to disambiguate the note's intent."
    llm_hint: "Choose this when the instruction is vague, ambiguous, or asks for clarification."
    intent_type: "clarification"
    downstream_event: "panel.proposal.clarifying_questions"
    capability_class: "clarification"
    authority_class: "read-only"
    requires_human_gate: false
  - id: "retrieval.related_notes"
    kind: "retrieval"
    labels:
      - "Visa relaterade anteckningar"
      - "Show related notes"
    description: "Return a bounded list of candidate related notes for orientation."
    llm_hint: "Choose this when the instruction asks for related material, neighboring notes, or what connects to this note."
    intent_type: "retrieval"
    downstream_event: "panel.retrieval.related_notes"
    capability_class: "retrieval"
    authority_class: "read-only"
    requires_human_gate: false
  - id: "note.summary.propose"
    kind: "proposal"
    labels:
      - "Föreslå en sammanfattning"
      - "Propose a summary"
    description: "Return a bounded summary proposal of the note inline in the panel log (does not create a separate note)."
    llm_hint: "Choose this when the instruction asks for a quick or inline summary that should remain visible for review, not for a separate summary document."
    intent_type: "proposal"
    downstream_event: "panel.proposal.note_summary"
    capability_class: "proposal"
    authority_class: "proposal"
    requires_human_gate: false
---

PanelAgent action catalog (canonical source for AI panel actions).
- `id`: canonical action id (e.g., `promote.evergreen`, `note.archive`, `proposal.next_actions`).
- `kind`: category of action (promotion, ingest, hygiene, chat, zone, proposal, clarification, retrieval).
- `labels`: human-facing labels/synonyms shown in panels; used as hints, not strict matches.
- `description` / `llm_hint`: short explanation for prompts.
- `intent_type` + `downstream_event`: determine runtime event fan-out (promotion emits `promote.intent.created`; proposal/retrieval/clarification emit observational `panel.proposal.*` / `panel.retrieval.*` log entries).
- `params`: structured parameters for the downstream event (e.g., `maturity: evergreen`).

### Capability metadata (#982)

Each catalog entry carries a small slice of the standard capability contract per
`docs/CAPABILITY_CONTRACT_MODEL.md`:

- `capability_class` — one of `orientation`, `proposal`, `retrieval`, `clarification`, `synthesis_review`, `governed_execution`, `repair_maintenance`.
- `authority_class` — one of `read-only`, `proposal`, `governed_effect`.
- `requires_human_gate` — boolean. `true` for governance-bearing capabilities; `false` for proposal-only / read-only cognitive capabilities.

The PanelAgent governance gate (`_is_governance_bearing` in
`app/agents/panel_agent/graph.py`) reads these fields from the active catalog
to decide whether an LLM-selected freeform proposal must be written back
unchecked for human confirmation (governance-bearing) or may execute in the
same runtime pass (proposal-only / read-only). The hardcoded action-id
allowlist that previously implemented this gate has been replaced by the
catalog metadata above.

### Proposal-only cognitive capabilities

`proposal.note_diagnosis`, `proposal.next_actions`, `proposal.clarifying_questions`,
`retrieval.related_notes`, and `note.summary.propose` are non-governance-bearing.
They never mutate the vault, never cross WriteGuard, and never produce a
receipt-governed effect. Their downstream events are observational
(`panel.proposal.*` / `panel.retrieval.*`) and surface bounded, human-readable
output in the panel log. Outputs remain proposal-shaped; admission to the
durable surface still requires an explicit human action (e.g., promotion,
archival, or summary-note creation).

Rule-mode continues to match checkbox labels against this catalog deterministically. LLM-mode (opt-in) uses the same catalog plus panel/note context to choose actions; checkboxes are treated as hints.
