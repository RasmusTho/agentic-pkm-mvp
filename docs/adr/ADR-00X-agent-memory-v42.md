State: Legacy (archived); superseded by SoT v4.10 Reality-MVP.
# ADR: Agent memory v4.2 (scoped PG memory)

Decision (historical): Postgres-based agent memory with named scopes, unified adapter API, transactional reflection, and edge storage.

Context in SoT v4.10:
- Reality-MVP omits scoped agent-memory tables; only `ObjectStore` + decisions/memory helpers are active.
- Promotion, ASK, and panel flows rely on stored objects and hybrid retrieval, not a separate memory graph.
- Current data model is documented in `docs/DATA_MODEL.md` and implemented in `app/store/object_store.py` with in-memory/pg fallback.

Current implementation:
- No scoped PG memory or edge store is present; in-memory caches in `app/memory/store.py` are minimal and not durable.
- PER/reflect hooks do not persist to a memory graph.

Status: Legacy reference. Keep for historical rationale; do not treat as current contract. See SoT docs for active storage patterns.
