State: Partially outdated; template ingest flow (not loaded in SoT v4.10 runtime).
---
flow_id: ingest
name: "Ingest pipeline"
enabled: true

event_triggers:
  - ingest.object.created
  - ingest.object.updated

intent: |
  Turn new raw text into structured, searchable knowledge with minimal human friction.

suggested_patterns:
  - name: standard_ingest
    description: "Normalize, classify, chunk, reason, index."
    steps:
      - target: agent:normalizer
      - target: agent:classifier
      - target: agent:chunker
      - target: mcp:vault.append_note
        description: "Persist summary back to the vault note."
        args:
          title: "Ingest summary"
          body: "{{ summary }}"
          tags:
            - ingest
            - summary
  - name: light_ingest
    description: "Only normalize and classify for quick triage."
    steps:
      - target: agent:normalizer
      - target: agent:classifier

planner_mode:
  strictness: advisory
  max_steps: 8

prompt_profiles:
  - id: ingest-default
    description: "Standard ingest mode."
    prompt_template_ref: prompts/planner/ingest-default.md
  - id: ingest-fast
    description: "Cheaper, faster triage mode."
    prompt_template_ref: prompts/planner/ingest-fast.md
---

# Ingest Flow Profile

Sample profile that lives in `vault/_system/flows/ingest.flow.md` when running against a live
vault. This file documents the YAML frontmatter accepted by `app.settings.flow_profiles`.

- `event_triggers` declares which events enable the profile.
- `intent` and `suggested_patterns` capture the human strategy for the flow.
- `planner_mode` and `prompt_profiles` advise the planner but do not force execution paths.
- Pattern steps accept structured entries with `target`, optional `description`, and `args` for tool calls.
