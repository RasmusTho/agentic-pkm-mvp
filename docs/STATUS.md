# STATUS — Snapshot (2025-11-02)

Updated snapshot after the lifespan shim + store provider work.

| Component / Area                    | Status | Note |
|------------------------------------|:-----:|------|
| FastAPI lifespan shim              | 🟢 | `app/main.py` runs with a proper lifespan context. No DB wiring in the entrypoint. |
| Router extraction                  | 🟢 | `/agent`, `/interesting`, and `/dashboard` live in routers; main only includes them. |
| Store backend provider             | 🟢 | `get_stores()` auto-detects via `STORE_BACKEND` / `DATABASE_URL`, probes PG, falls back to memory. |
| In-memory Stores                   | 🟢 | Cached factory returns the same instances per process; `reset_memory_stores()` exists for tests. |
| Direct DB imports (guard)          | 🟡 | Policy in place but some legacy modules still import DB/psycopg directly; migration via provider remains. |
| Promotion queue/agent              | 🟡 | Queue + Promotion Agent exist and emit JSONL events; no automatic reindex trigger wired end-to-end yet. |
| Search / index pipeline            | 🟡 | Deterministic embeddings + BM25 hybrid present; weights are static for now (not read from system-settings). |
| Outbox / event log                 | 🟡 | Stores write JSONL and outbox rows; worker exists but is not auto-started in app/CI. |
| Observability / tracing            | 🟡 | JSONL tracer in use; no OTLP/OpenTelemetry exporter wired at the moment. |
| In-memory test harness             | 🟢 | Pytest and smoke can run without Postgres thanks to memory stores and stubs. |
| `system-settings.yaml` schema      | 🟢 | Validated by `tests/system/test_settings_schema.py`; part of smoke. |
| MergeResolverAgent + CLI           | 🟢 | Semantic merge driver CLI exists and is covered by smoke tests. |
| Git merge driver integration       | 🟡 | `.gitattributes` routes `*.md` to `merge=semanticmd`; the driver config needs to be documented/applied locally. |
| NoteHygieneAgent                   | 🟡 | Emits events; no built-in scheduler/worker wiring yet. |
| Classifier v2 guard                | 🟢 | Guard active via `SKIP_CLASSIFIER_TESTS`; full suite to be re-opened with the v2 rewrite. |

## Focus for the next sprint
- Keep main “thin”: only lifespan + `include_router(...)`. All endpoints live in routers. 
- Migrate remaining direct DB usages to go through `app/stores/provider.py`.
- Add a small dev/CI hook to run the outbox worker (manual for now).
- Externalize hybrid search weights into `system-settings.yaml` and read them at runtime with sane defaults.
- Start the Classifier v2 rewrite and remove the skip guard.

## Quick ops notes
- Backend toggle: `STORE_BACKEND=pg|memory` (default: auto). Set `DATABASE_URL=...` for PG.
- Reset in-memory stores during tests:
  ```py
  from app.stores.provider import reset_memory_stores; reset_memory_stores()
   
