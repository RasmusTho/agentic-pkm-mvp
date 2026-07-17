---
uuid: 00000000-0000-0000-0000-000000000103
title: Reviewer Agent Settings
origin: user
review_state: evergreen
trust: internal
---
## Toggles
- [x] enable

## Thresholds
| key | value |
| --- | --- |
| threshold | 0.78 |
| rules.min_score | 0.78 |

```yaml settings
escalation_channel: "curation-triage"
rules:
  required_labels: ["agent:reviewer","stage:curation"]
  min_score: 0.78
labels: ["agent:reviewer","stage:curation"]
```

## Förklaringar & möjliga värden
<!-- BEGIN:settings:reference -->
### Reference — Reviewer

| key | type | default | allowed | description |
|-----|------|---------|---------|-------------|
| `enable` | `bool` | `True` | `` | Enable this agent. |
| `dry_run` | `bool` | `False` | `` | Disable writes for this agent. |
| `timeout_ms` | `int` | `8000` | `100-120000` | Agent-specific timeout in milliseconds. |
| `labels` | `List` | `PydanticUndefined` | `` | Tag this agent with capability labels. |
| `threshold` | `float` | `0.75` | `` | Score threshold to auto-approve. |
| `escalation_channel` | `str` | `audit` | `` | Audit or notification channel for escalations. |
| `rules` | `ReviewerRules` | `PydanticUndefined` | `` |  |
<!-- END:settings:reference -->
