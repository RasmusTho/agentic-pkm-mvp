State: Partially outdated; template only (runtime uses direct normalizer, not this YAML) in SoT v4.10.
---
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

# Normalizer Agent Configuration

A worker that tidies new notes before downstream flows act on them. The YAML frontmatter is
identical to the data loaded in tests under `tests/settings/test_agent_configs.py`.
