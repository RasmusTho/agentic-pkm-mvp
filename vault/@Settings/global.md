uuid: 00000000-0000-0000-0000-000000000001
title: Global Settings
origin: user
review_state: evergreen
trust: internal
---
State: Example / sandbox (not authoritative).
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

## Notes
This file is illustrative; current runtime does not parse `@Settings` markdown. Use env vars and code defaults (`docs/SETTINGS.md`, `docs/LLM.md`).
