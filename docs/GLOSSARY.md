# Glossary

Kortfattade definitioner för återkommande begrepp.

<!-- SECTION:GLOSSARY:BEGIN -->
- **Outbox** – JSONL-fil (`INDEX_OUTBOX_PATH`) där ingestion och transcribe skriver händelser innan indexering. Se `app/index/outbox.py`.
- **Embedding** – Flyttalssvector från `app/llm/embeddings.py` (Ollama `/api/embeddings` eller mock). Lagrade in-memory i `MemoryHybridStore`.
- **BM25** – Lexikal scorer från `rank_bm25.BM25Okapi`, används i hybrid retrieval.
- **Rerank** – Ytterligare modell (planerad) som sorterar retrieval-resultat. Se docs/ROADMAP.md för nästa steg med cross-encoder.
- **Span** – `@span("node")` från `app/obs/log.py` som loggar latency/trace-id per funktion.
- **Guardrails** – Regler i `app/quality/guardrails.py` som förhindrar förbjudet innehåll, säkrar källor och håller tokenbudget.
- **Circuit breaker** – `CircuitBreaker`-klassen i `app/quality/guardrails.py` som begränsar antalet fel inom ett tidsfönster.
- **Index outbox JSONL** – Rader med `{object_id, kind, source_ref, payload}`. Se `docs/INVENTORY.md`.
- **Hybrid store** – In-memory kombination av BM25 + embedding + fuzzy overlap (`app/retrieval/hybrid.py`).
- **Health CLI** – `python -m app.cli health --json`, kontrollerar ffmpeg, yt-dlp, outbox-path och Ollama reachability.
<!-- SECTION:GLOSSARY:END -->
