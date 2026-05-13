
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
### Reference — Providers

| key | type | default | allowed | description |
|-----|------|---------|---------|-------------|
| `llm` | `Dict` | `PydanticUndefined` | `` | Named chat/LLM providers. |
| `embedding` | `Dict` | `PydanticUndefined` | `` | Embedding model providers. |
| `reranker` | `Dict` | `PydanticUndefined` | `` | Cross-encoder/rerank providers. |
<!-- END:settings:reference -->
