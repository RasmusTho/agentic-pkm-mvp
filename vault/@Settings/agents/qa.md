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
### Reference — Qa

| key | type | default | allowed | description |
|-----|------|---------|---------|-------------|
| `enable` | `bool` | `True` | `` | Enable this agent. |
| `dry_run` | `bool` | `False` | `` | Disable writes for this agent. |
| `timeout_ms` | `int` | `8000` | `100-120000` | Agent-specific timeout in milliseconds. |
| `labels` | `List` | `PydanticUndefined` | `` | Tag this agent with capability labels. |
| `search_k` | `int` | `8` | `` | Documents retrieved before filtering. |
| `context_docs` | `int` | `5` | `` | Documents kept in the final answer context. |
| `llm` | `QaLLMSettings` | `PydanticUndefined` | `` |  |
<!-- END:settings:reference -->
