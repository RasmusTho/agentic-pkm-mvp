Here’s the full docs/STATUS.md in English:

# STATUS — Snapshot (2025-11-02)

_Updated status after the lifespan shim + store provider work._

| Component / Area                          | Status | Note |
|-------------------------------------------|--------|------|
| FastAPI lifespan shim                     | 🟢     | `app/main.py` uses a proper lifespan; stub repository/service are monkey-patched in tests and cleaned up on shutdown. |
| Router extraction                         | 🟡     | API endpoints still live in the shim; `docs/ROADMAP.md` tracks moving them into real routers. |
| Store backend provider                    | 🟢     | `get_stores()` detects `STORE_BACKEND`/`DATABASE_URL`, does a quick `psycopg` connect probe, and falls back to memory. |
| In-memory Stores                          | 🟢     | Cached factory (`_memory_stores()`) reuses the same instances; `reset_memory_stores()` exists for test isolation. |
| Direct DB imports                         | 🟡     | Guards documented, but some legacy code still imports DB directly under `app/store/...`; migration via provider remains. |
| Promotion worker/agent                    | 🟡     | JSONL queue updates front matter + optional file moves; no triggered reindex/outbox flow yet. |
| Search / index pipeline                   | 🟡     | Deterministic embeddings + pgvector upsert; hybrid scoring uses fixed weights, not `system-settings.yaml`. |
| Outbox / event log                        | 🟡     | `ObjectStore.save_object` writes to `outbox` (when PG reachable) and `events.jsonl`; no automatic consumer yet. |
| Observability / tracing                   | 🟡     | OTLP export via `opentelemetry` only when package + settings present; default spans are no-op. |
| In-memory test harness                    | 🟢     | Pytest runs entirely without Postgres thanks to memory stores + stub index. |
| `system-settings.yaml` schema             | 🟢     | Validated against JSON Schema in `tests/system/test_settings_schema.py`; included in `make smoke`. |
| MergeResolverAgent + CLI                  | 🟢     | Semantic merge + `app/cli/merge_driver.py` provides status/reason with safe exit codes. |
| Git merge driver integration              | 🟡     | CLI not yet wired via `.gitattributes`; tracked as a next step. |
| NoteHygieneAgent                          | 🟡     | Emits `cleanup.done` into `events.jsonl`; no scheduler or PG-backed outbox yet. |
| Classifier v2 guard                       | 🟡     | Tests are guarded via `SKIP_CLASSIFIER_TESTS=1`; rewrite planned in the upcoming sprint. |

## Focus for the next sprint
- Extract `/agent`, `/interesting`, `/dashboard` into real routers; keep the shim only importing them.
- Consolidate store usage via `app/stores/provider.py`; phase out direct `PgObjects`/`MemoryObjects` instantiation.
- Instrument basic event logging (`trace_id`, topic) around store writes.
- Clean up `_legacy/` imports after the new wiring lands.
- Kick off Classifier v2 and reopen the test suite.

## CI / Smoke mode
- ✅ `make smoke` runs focused contract tests:
  - `tests/system/test_settings_schema.py`
  - Index rules + ignores (three curated tests under `tests/index/`)
  - Promotion chain (queue logic, reconciling, batch move, e2e intent→index)
  - Merge smoke (`tests/smoke/test_merge_smoke.py`)
- ⏳ GitHub Actions needs to reflect this bundle; currently the suite runs manually locally.

## Open risks
- Promotion → index is still manual; without auto-reindex, promoted material may miss the search view.
- Outbox lacks a consumer, so downstream agents don’t trigger without an external process.
- Tracing is best-effort: without `opentelemetry`, spans are no-op — the observability plan needs follow-through.

---

## Quick ops notes
- **Backend toggle:** `STORE_BACKEND=pg|memory` (default: auto); set `DATABASE_URL=...` for Postgres.
- **Reset in-memory stores (tests):**
  
  from app.stores.provider import reset_memory_stores
  reset_memory_stores()

	•	Classifier tests: set SKIP_CLASSIFIER_TESTS=0 to re-enable the v2 tests.

Sprint Definition of Done (v4.5 slice)
	•	Routers extracted: /agent, /interesting, /dashboard live in
app/api/routers/{agent.py,interesting.py,dashboard.py} and are included from app/main.py.
	•	Store provider used everywhere; no direct DB imports outside stores/db/alembic (guard green).
	•	Store writes emit event-log entries with at least trace_id and topic.
	•	CI: smoke workflow is green in GitHub Actions.

Fitness functions (guardrails)
	•	QAS-003 Search latency: p95 ≤ 250 ms for top-10 queries on the test corpus.
	•	QAS-010 Outbox→Index delay: ≤ 2 s from outbox write until the object is searchable in the index.

Docs follow-ups
	•	Update ARCHITECTURE.md (Store abstraction + Vector/Relation index),
ROADMAP.md (router extraction), and the Promotion Agent section to reflect the current design.

