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

# Planner Agent Configuration

This sample mirrors the `vault/_system/agents/planner.md` document that will ship with
agent-first planning. Runtime code can load this via `app.settings.agents.load_agent_configs`.
