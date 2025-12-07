State: Legacy (archived); superseded by SoT v4.10 Reality-MVP.
# ADR: Agent memory v1 (Postgres JSONB)

Decision (historical): Use Postgres JSONB + GIN as an agent memory store with a simple adapter and PER reflect hook.

Context in SoT v4.10:
- Reality-MVP does **not** ship a dedicated agent-memory store. The active path is `ObjectStore` (memory/pg) plus lightweight decisions/memory helpers.
- Retrieval relies on hybrid search over stored objects, not an agent-specific memory table.
- Architectural constraints and Core-6 metadata live in `docs/DATA_MODEL.md`; agent-memory tables are not part of the current schema.

Current implementation:
- No PG JSONB agent-memory table exists in v4.10; in-memory fallbacks in `app/memory/store.py` are used for small decision caches only.
- PER-loop hooks are not wired to a memory store.

Status: Legacy reference only. For current behaviour, see `docs/DATA_MODEL.md`, `docs/INGEST.md`, and `app/store/object_store.py`.
