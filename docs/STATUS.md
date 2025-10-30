# STATUS — 2025-10-29

_Snapshot of current system health._

| Component | Status | Notes |
|-----------|--------|-------|
| Promotion chain | 🟢 Stable | Intent → Promoted → Indexed |
| MergeResolverAgent | 🟢 Green | Semantic merge (LLM + deterministic fallback); returns status/reason; all tests green |
| NoteHygieneAgent | 🟢 Green | Salvages link-only notes, archives empty notes, moves oversized dumps; tests green |
| Events / CLI | 🟢 Ready | Tools operational |
| Git merge driver | 🟡 Partial | Local semanticmd OK; CI next |
| CI (Smoke + Schema) | 🟡 Partial | Merge tests pending |
| OTel Spans | 🟢 Enabled | Jaeger endpoint pending |
| Outbox / Event Bus | 🟢 Stable | promote.*, merge.*, cleanup.* |

## CI
- Smoke pipeline: `make smoke` (agents + settings + promotion) ✅
- Merge smoke = ✅ local, not yet wired into CI

## Agents: Merge & Hygiene – status
- [x] ARCHITECTURE updated with Merge/Hygiene
- [x] config/agents.yaml tracked
- [x] JSON-scheman validated in CI for promotion & settings (merge/hygiene schema validation may still be TODO)
- [x] Tests: merge green, hygiene green
- [ ] Git-driver active (semanticmd)

## Merge & Hygiene Road to v4.5
- [x] Baseline agents + tests green
- [x] Event log + CLI helpers
- [x] Git merge driver wired
- [ ] LLM judging enabled in CI
- [ ] ASK microflow CLI (A/B/Hybrid)
- [ ] Golden fixtures for HYBRID merges
