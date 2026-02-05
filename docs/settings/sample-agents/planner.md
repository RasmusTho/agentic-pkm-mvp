---
State: Partially outdated; template for future planner orchestration (not used in SoT v4.10).
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

State: v5.5 baseline aligned (legacy sections retained where noted; registry watcher default, DB outbox canonical, JSONL audit log non-canonical; watcher auto-run gated; LangGraph planner opt-in).

## v5.5 Baseline Delta (Current Reality)
- Registry watcher is the runtime default; legacy snapshot watcher is dev-only.
- DB outbox (Postgres) is the canonical queue; JSONL audit log is non-canonical and used for lag inspection.
- Watcher auto-run remains off unless allowlisted; LangGraph/Reasoning rollout is opt-in.
- See `docs/STATUS.md` and `docs/ARCHITECTURE.md` for the current baseline and forward line.

# Planner Agent Configuration

This sample mirrors the `vault/_system/agents/planner.md` document that will ship with
agent-first planning. Runtime code can load this via `app.settings.agents.load_agent_configs`.
