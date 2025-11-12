---
uuid: 00000000-0000-0000-0000-000000000104
title: QA Agent Settings
origin: user
review_state: evergreen
trust: internal
---
## Toggles
- [x] enable

## Retrieval
| key | value |
| --- | --- |
| search_k | 8 |
| context_docs | 5 |

```yaml settings
llm:
  provider: mock
  model: "llama3.1:8b-instruct"
  host: "http://127.0.0.1:11434"
  timeout_s: 60
  max_tokens: 400
labels: ["agent:qa","stage:answer"]
```

## Förklaringar & möjliga värden
<!-- BEGIN:settings:reference -->
| key | type | default | allowed | description |
|-----|------|---------|---------|-------------|
| _pending | _ | _ | _ | Run `python -m app.cli settings compile --auto-heal` to update this table. |
<!-- END:settings:reference -->
