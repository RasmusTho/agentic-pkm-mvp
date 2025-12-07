State: Example / sandbox (not authoritative).
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

## Notes
Illustrative only; Reality-MVP does not read `@Settings` markdown. Promotion is stubbed (audit/membership) as documented in `docs/AGENTS.md`/`docs/PROJECTOR.md`.
