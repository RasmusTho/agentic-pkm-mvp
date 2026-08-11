---
uuid: 00000000-0000-0000-0000-000000000008
title: Retrieval tuning
origin: user
review_state: evergreen
trust: internal
---
## Rerank defaults

```yaml settings
rerank: "off"
rerank_provider: none
rerank_top_k: 100
```

The values above are durable vault settings. `RERANK_ENABLE`, `RERANK_PROVIDER`, and
`RERANK_TOP_K` remain deprecated one-release bootstrap overrides.
