---
State: Partially outdated; template only (runtime uses direct normalizer, not this YAML) in SoT v4.10.
agent_id: normalizer
agent_type: worker
enabled: true
flows:
  - ingest
allowed_targets:
  - normalize.queue
allowed_events:
  - ingest.object.created
model:
  provider: ollama
  name: llama3.1:8b-instruct
  temperature: 0.0
  max_tokens: 1024
tools:
  - normalize
prompt_template_ref: normalizer.prompts.default
---

State: v5.5 baseline aligned (legacy sections retained where noted; registry watcher default, DB outbox canonical, JSONL audit log non-canonical; watcher auto-run gated; LangGraph planner opt-in).

## v5.5 Baseline Delta (Current Reality)
- Registry watcher is the runtime default; legacy snapshot watcher is dev-only.
- DB outbox (Postgres) is the canonical queue; JSONL audit log is non-canonical and used for lag inspection.
- Watcher auto-run remains off unless allowlisted; LangGraph/Reasoning rollout is opt-in.
- See `docs/STATUS.md` and `docs/ARCHITECTURE.md` for the current baseline and forward line.

# Normalizer Agent Configuration

A worker that tidies new notes before downstream flows act on them. The YAML frontmatter is
identical to the data loaded in tests under `tests/settings/test_agent_configs.py`.
