State: Planned / not implemented in SoT v4.10.
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

# Normalizer Agent Configuration (sample)

Sample config for future agent-config loading. Reality-MVP uses direct functions/graphs for ingest; this YAML is not consumed at runtime. Keep for v5.x reference alongside `docs/INGEST.md`.
