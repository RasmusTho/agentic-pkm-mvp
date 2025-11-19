# AI panel example note

```markdown
---
uuid: 123e4567-panel-demo
kind: evergreen
---

# Min anteckning om Agentic PKM

## AI-instruktion
Jag vill förbättra sammanfattningen och säkerställa att den här sidan blir evergreen.

## AI-åtgärder
- [ ] Gör denna anteckning evergreen
- [ ] Skapa en kort executive summary
- [x] Kontrollera länkarna i research-listan

## AI-logg
- 2025-02-18 09:12 – Gjorde: "Kontrollera länkarna i research-listan"
```

Humans edit the instruction and checkbox list directly; once they tick an action the PanelAgent notices the newly checked line, emits a `PanelIntent(kind="action_triggered", action_text="...")`, removes the line from `AI-åtgärder`, and appends a log bullet under `AI-logg`. Instructions stay as-is so the note remains human-first while still giving agents clear intent.
