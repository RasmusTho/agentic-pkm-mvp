# STATUS — 2025-10-29

_Snapshot of current system health._

| Component | Status | Notes |
|----------- | ------- | ------|
| Promotion chain | 🟢 Stable | Intent → Promoted → Indexed |
| MergeResolverAgent | 🟢 Baseline | LLM judging off by default |
| NoteHygieneAgent | 🟢 Baseline | Archive + events green |
| Events / CLI | 🟢 Ready | Tools operational |
| Git merge driver | 🟡 Partial | Local semanticmd OK; CI next |
| CI (Smoke + Schema) | 🟡 Partial | Merge tests pending |
| OTel Spans | 🟢 Enabled | Jaeger endpoint pending |
| Outbox / Event Bus | 🟢 Stable | promote.*, merge.*, cleanup.* |

### Merge & Hygiene Road to v4.5
- [x] Baseline agents + tests green  
- [x] Event log + CLI helpers  
- [x] Git merge driver wired  
- [ ] LLM judging enabled in CI  
- [ ] ASK microflow CLI (A/B/Hybrid)  
- [ ] Golden fixtures for HYBRID merges  
