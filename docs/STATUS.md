# Status (rolling)
## Done (v4.3)
- PER-loop bas och spårning (trace_id)
- Outbox → Indexer (p95 ≤ 2s) [QAS-010 i CI]
- Fake Search (p95 < 250 ms) [QAS-003 i CI]
- Contracts lint (OpenAPI/AsyncAPI) i CI
## In progress (v4.3.1)
- Obsidian-first tvåväg (Git-driven watcher + YAML roundtrip)
- Settings som .md + schema + validering i CI
## Next (v4.4)
- LLM spans (OTel/JSONL)
- Merge- och konfliktpolicy (frontmatter/body)
- Broker-backad outbox utan att tappa QAS-010
