State: Legacy (archived); agent-specific memory is not part of SoT v4.10.
# How-to: Agent memory (historical)

Reality-MVP does not ship a dedicated agent-memory store or the v4.2 SetDB API. Active storage is:
- `ObjectStore` (memory/pg) for objects + metadata,
- `VectorIndex` for embeddings,
- lightweight decisions/memory helpers for classifications/review (`app/memory/store.py`).

If you need current behavior, see `docs/DATA_MODEL.md`, `docs/INGEST.md`, and retrieval in `docs/RETRIEVAL.md`. Treat this page as historical context only.
