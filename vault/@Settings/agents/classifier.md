
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
| key | type | default | allowed | description |
|-----|------|---------|---------|-------------|
| _pending | _ | _ | _ | Run `python -m app.cli settings compile --auto-heal` to update this table. |
<!-- END:settings:reference -->
