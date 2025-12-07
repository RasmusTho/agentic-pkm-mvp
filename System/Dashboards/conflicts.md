---
uuid: SYS-DASH-CONFLICTS
kind: dashboard
title: Conflicts Monitor
---
State: SoT v4.10 Reality-MVP (current, minimal dashboard).
```dataview
TABLE without id file.ctime AS Created, file.link AS Note
FROM "Inbox/Conflicts"
SORT file.ctime desc
```
