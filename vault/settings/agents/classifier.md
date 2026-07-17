
uuid: 00000000-0000-0000-0000-000000000101
title: Classifier Agent Settings
origin: user
review_state: evergreen
trust: internal

## Toggles
- [x] enable
- [ ] dry_run

## Routing
| key | value |
| --- | --- |
| min_confidence | 0.65 |
| retry_policy.max_tries | 2 |
| timeout_ms | 8000 |

```yaml settings
model: llama3.1:8b@ollama
embedding: nomic-embed-text@ollama
reranker: ce_local
rules:
  must_block_without_sources: true
labels: ["agent:classifier","stage:ingest"]
```

## Förklaringar & möjliga värden
<!-- BEGIN:settings:reference -->
### Reference — Classifier

| key | type | default | allowed | description |
|-----|------|---------|---------|-------------|
| `enable` | `bool` | `True` | `` | Enable this agent. |
| `dry_run` | `bool` | `False` | `` | Disable writes for this agent. |
| `timeout_ms` | `int` | `8000` | `100-120000` | Agent-specific timeout in milliseconds. |
| `labels` | `List` | `PydanticUndefined` | `` | Tag this agent with capability labels. |
| `min_confidence` | `float` | `0.5` | `` | Minimum confidence for positive classifications. |
| `retry_policy` | `RetryPolicy` | `PydanticUndefined` | `` |  |
| `model` | `Optional` | `` | `` | Preferred LLM model for classifier prompts. |
| `embedding` | `Optional` | `` | `` | Embedding provider override. |
| `reranker` | `Optional` | `` | `` | Reranker provider override. |
| `rules` | `Dict` | `PydanticUndefined` | `` | Additional policy flags for classifier runs. |
<!-- END:settings:reference -->
