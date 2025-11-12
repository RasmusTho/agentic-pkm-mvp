
uuid: 00000000-0000-0000-0000-000000000102
title: Promotion Agent Settings
origin: user
review_state: evergreen
trust: internal

## Toggles
- [x] enable

```yaml settings
move_policy:
  enabled: true
  window: "02:00-04:00"
  batch_size: 200
labels: ["agent:promotion","stage:governance"]
```
