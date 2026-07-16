---
uuid: 00000000-0000-0000-0000-000000000001
title: Global Settings
origin: user
review_state: evergreen
trust: internal
---
## Toggles
- [x] enable
- [ ] dry_run

## Timeouts
| key        | value |
|------------|-------|
| timeout_ms | 8000  |

## Runtime
```yaml settings
log_level: INFO
profile: default
```

## Förklaringar & möjliga värden
<!-- BEGIN:settings:reference -->
### Reference — Global

| key | type | default | allowed | description |
|-----|------|---------|---------|-------------|
| `enable` | `bool` | `True` | `` | Enable this component for runtime pipelines. |
| `dry_run` | `bool` | `False` | `` | Skip persistence and side-effects when true. |
| `note_moves_enable` | `bool` | `False` | `` | Allow agents to move or rename notes as part of ingestion and promotion. |
| `timeout_ms` | `int` | `8000` | `100-60000` | Per-operation timeout in milliseconds. |
| `log_level` | `str` | `INFO` | `DEBUG, INFO, WARNING, ERROR` | Log level for agents (DEBUG|INFO|WARNING|ERROR). |
| `profile` | `str` | `default` | `` | Active configuration profile name. |
| `secrets` | `Dict` | `PydanticUndefined` | `` | Secret references resolved at compile time. |
<!-- END:settings:reference -->
