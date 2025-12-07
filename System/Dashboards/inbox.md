---
uuid: SYS-DASH-INBOX
kind: dashboard
title: Inbox (System changes)
---
State: SoT v4.10 Reality-MVP (current, minimal dashboard).
```dataview
TABLE without id file.ctime AS Created, file.link AS Note
FROM "Inbox"
SORT file.ctime desc
```
