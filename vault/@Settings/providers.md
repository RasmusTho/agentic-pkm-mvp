
---
uuid: 00000000-0000-0000-0000-000000000002
title: Providers
origin: user
review_state: evergreen
trust: internal
---
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

## Förklaringar & möjliga värden
<!-- BEGIN:settings:reference -->
| key | type | default | allowed | description |
|-----|------|---------|---------|-------------|
| _pending | _ | _ | _ | Run `python -m app.cli settings compile --auto-heal` to update this table. |
<!-- END:settings:reference -->
