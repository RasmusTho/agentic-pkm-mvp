# SoT v4.1 – MVP Ingestion (app/*)
- AMG/SetDB lever i Postgres (pgvector för embeddings).
- Core-6 (id, type, title, created, updated, origin) lagras i DB payload; projector speglar endast whitelist.
- Event-koreografi: in-proc queue (WS), eventtyper: ingest.*, curation.*.
