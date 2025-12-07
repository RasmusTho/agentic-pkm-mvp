State: Planned / not implemented in SoT v4.10 (for future planner flows).
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

# Ingest Flow Profile (sample)

Reference YAML for a future planner/orchestrator-driven ingest flow. Reality-MVP does not load or enforce this file; ingest today is driven by CLI (`vault-alpha-ingest`, `pkm-alpha-ingest`) and the HybridStore path in `docs/INGEST.md`. Keep as a template for v5.x planner work.
