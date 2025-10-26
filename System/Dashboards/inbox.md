---
uuid: SYS-DASH-INBOX
kind: dashboard
title: Inbox (System changes)
---
```dataview
TABLE without id file.ctime AS Created, file.link AS Note
FROM "Inbox"
SORT file.ctime desc
```
