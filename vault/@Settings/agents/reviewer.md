---
uuid: 00000000-0000-0000-0000-000000000103
title: Reviewer Agent Settings
origin: user
review_state: evergreen
trust: internal
---
State: Example / sandbox (not authoritative).
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

## Notes
Example only; reviewer thresholds live in code/tests (`docs/AGENTS.md`, `docs/agents/AGENT_SPEC.md`). Runtime does not parse this file.
