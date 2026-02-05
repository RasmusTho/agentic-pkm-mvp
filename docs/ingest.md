State: Historical (SoT v4.10). Ingest path has evolved (registry watcher + DB outbox canonical). Keep as reference; prefer `docs/HUMAN-FLOWS.md` + `docs/OPERATIONS.md` for current runbooks.

## v5.5 Baseline Delta (Current Reality)
- Registry watcher is the runtime default; legacy snapshot watcher is dev-only.
- DB outbox (Postgres) is the canonical queue; JSONL audit log is non-canonical and used for lag inspection.
- Watcher auto-run remains off unless allowlisted; LangGraph/Reasoning rollout is opt-in.
- See `docs/STATUS.md` and `docs/ARCHITECTURE.md` for the current baseline and forward line.

# 4.5 Ingest (MVP)
**Mål:** få in fil/URL/ljud robust, normalisera, skriva `index-outbox.jsonl`.

## Kommandon
```bash
python -m app.cli normalize <PATH|URL>
python -m app.cli pipe <PATH|URL|AUDIO>
```

Normalisering
- Extrahera title, content, language, source_ref
- Språkdetektion (för BM25/stopwords)
- PII-redaktion (email/telefon) före indexering
- Idempotens: fingerprint (URL+etag eller fil-hash)

Index-outbox-format

{"object_id":"...","kind":"doc|transcript|note","source_ref":"...","payload":{"title":"...","content":"...","language":"sv","segments":[{"start":0.0,"end":3.2,"text":"..."}]}}
