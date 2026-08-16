---
uuid: 00000000-0000-0000-0000-000000000007
title: Text to Speech
origin: user
review_state: evergreen
trust: internal
---
# Text to Speech Settings

Local voice selection is vault-shared. The default fallback posture is local-only;
browser and cloud policies are lab-tier experiments, and cloud remains refused by
the production synthesis path.

```yaml settings
voices:
  sv: sv_SE-lisa-medium
  en_us: bf_isabella
  en_gb: bf_isabella
fallback_policy: local_only
```
