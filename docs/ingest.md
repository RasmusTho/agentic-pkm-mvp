State: Historical / partially outdated (e.g. SoT v4.2). See ARCHITECTURE SoT v4.10 for current intent.
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
