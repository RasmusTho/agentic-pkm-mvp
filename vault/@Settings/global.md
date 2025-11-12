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
secrets:
  telemetry_token: ${SECRET:OTEL_TOKEN}
```

## Förklaringar & möjliga värden
<!-- BEGIN:settings:reference -->
| key | type | default | allowed | description |
|-----|------|---------|---------|-------------|
| _pending | _ | _ | _ | Run `python -m app.cli settings compile --auto-heal` to update this table. |
<!-- END:settings:reference -->
