
uuid: 00000000-0000-0000-0000-000000000102
title: Promotion Agent Settings
origin: user
review_state: evergreen
trust: internal

## Toggles
- [x] enable

## Cooldowns
| key | value |
| --- | --- |
| cooldown_seconds | 120 |
| require_idle_seconds | 45 |
| max_retries | 4 |

```yaml settings
move_policy:
  enabled: true
  window: "02:00-04:00"
  batch_size: 200
  default_target: "2_Cards/Concepts"
  targets:
    - when:
        stage: evergreen
      path: "2_Cards/Evergreen"
labels: ["agent:promotion","stage:governance"]
```

## Förklaringar & möjliga värden
<!-- BEGIN:settings:reference -->
| key | type | default | allowed | description |
|-----|------|---------|---------|-------------|
| _pending | _ | _ | _ | Run `python -m app.cli settings compile --auto-heal` to update this table. |
<!-- END:settings:reference -->
