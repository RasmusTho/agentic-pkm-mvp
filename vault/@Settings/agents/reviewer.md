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
| key | type | default | allowed | description |
|-----|------|---------|---------|-------------|
| _pending | _ | _ | _ | Run `python -m app.cli settings compile --auto-heal` to update this table. |
<!-- END:settings:reference -->
