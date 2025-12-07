uuid: 00000000-0000-0000-0000-000000000002
title: Providers
origin: user
review_state: evergreen
trust: internal
---
State: Example / sandbox (not authoritative).
## Provider defaults
```yaml settings
llm:
  default_chat:
    kind: openai_compat
    base_url: "http://127.0.0.1:11434/v1"
    model: "llama3.1:8b"
embedding:
  default:
    kind: openai_compat
    model: "nomic-embed-text"
reranker:
  ce_local:
    kind: colbert
    device: cpu
```

## Notes
Example only; actual provider configuration is via env vars (`LLM_PROVIDER`, `LLM_MODEL`, etc.) and defaults in `docs/LLM.md` / `docs/SETTINGS.md`.
