State: Example note. This is illustrative content for panels; it does not define runtime behavior.

## v5.5 Baseline Delta (Current Reality)
- Registry watcher is the runtime default; legacy snapshot watcher is dev-only.
- DB outbox (Postgres) is the canonical queue; JSONL audit log is non-canonical and used for lag inspection.
- Watcher auto-run remains off unless allowlisted; LangGraph/Reasoning rollout is opt-in.
- See `docs/STATUS.md` and `docs/ARCHITECTURE.md` for the current baseline and forward line.

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
