# STATUS — Snapshot (2025-11-08)

## Active Version: v4.5

✅ Completed components:
- Search service locked to FT-first hybrid ordering for deterministic retrieval.
- Ingest delegation restored (`app/search/service.py::ingest_object` → `app.ingest.ingest_object`) with fallback for minimal harnesses.
- CI smoke validation (memory + pg matrix) installs runtime requirements, migrates Postgres, and runs code-fence/pytest gates.

🧩 Next focus (v4.6):
- Formalize Store interfaces (ObjectStore / VectorIndex / RelationIndex) and document contracts.
- Wire Indexer agent to Outbox-driven indexing (`index.object.embedded`) end-to-end.
- Promotion v2: move policy refinements + `pending_move` events feeding PER loops.

## Known limitations
- None beyond roadmap items; see [`docs/ROADMAP.md`](docs/ROADMAP.md).
   
