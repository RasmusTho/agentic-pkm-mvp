
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
