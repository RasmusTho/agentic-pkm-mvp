
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
### Reference — Promotion

| key | type | default | allowed | description |
|-----|------|---------|---------|-------------|
| `enable` | `bool` | `True` | `` | Enable this agent. |
| `dry_run` | `bool` | `False` | `` | Disable writes for this agent. |
| `timeout_ms` | `int` | `8000` | `100-120000` | Agent-specific timeout in milliseconds. |
| `labels` | `List` | `PydanticUndefined` | `` | Tag this agent with capability labels. |
| `cooldown_seconds` | `int` | `90` | `` | Minimum seconds since last edit before promotion. |
| `require_idle_seconds` | `int` | `30` | `` | Minimum idle seconds to avoid churn. |
| `max_retries` | `int` | `3` | `` | Queue retries before giving up on a promotion item. |
| `move_policy` | `MovePolicy` | `PydanticUndefined` | `` |  |
<!-- END:settings:reference -->
