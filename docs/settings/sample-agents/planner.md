State: Planned / not implemented in SoT v4.10.
---
agent_id: planner
agent_type: planner
enabled: true
flows:
  - ingest
  - promotion
allowed_targets:
  - planner.queue
  - audit.log
allowed_events:
  - ingest.object.created
  - promote.intent.created
model:
  provider: openai
  name: gpt-4o
  temperature: 0.2
  max_tokens: 2048
tools:
  - summarize
  - planner.scratchpad
prompt_template_ref: planner.prompts.default
---

# Planner Agent Configuration (sample)

Template for future planner/orchestrator wiring. Reality-MVP does not load or execute planner configs; keep for v5.x design reference. For current behaviour see `docs/AGENTS.md` and `docs/PANEL_AGENT.md`.
