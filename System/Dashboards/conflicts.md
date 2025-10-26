---
uuid: SYS-DASH-CONFLICTS
kind: dashboard
title: Conflicts Monitor
---
```dataview
TABLE without id file.ctime AS Created, file.link AS Note
FROM "Inbox/Conflicts"
SORT file.ctime desc
```
