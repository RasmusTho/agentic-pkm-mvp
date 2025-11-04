
docs/STATUS.md

# STATUS — Snapshot (2025-11-02)

_Snapshot of current system health after the lifespan shim + store provider work._

| Component                      | Status     | Notes                                                                                                                                                                     |
|--------------------------------|------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| FastAPI lifespan shim          | 🟢 Green   | `app/main.py` runs inside a proper lifespan; stub providers are monkey-patched in tests and cleaned up on shutdown.                                                       |
| Router extraction              | 🟡 Planned | Endpoints still live in the shim; tracked in `docs/ROADMAP.md` to move them into dedicated routers.                                                                       |
| Store backend provider         | 🟢 Green   | `get_stores()` inspects `STORE_BACKEND`/`DATABASE_URL`, probes `psycopg`, and falls back to in-memory factories when Postgres is unavailable.                              |
| In-memory Stores               | 🟢 Green   | Cached `_memory_stores()` factory reuses instances; `reset_memory_stores()` keeps pytest isolation.                                                                        |
| Direct DB imports              | 🟡 Yellow  | Guards exist but some legacy modules still import DB implementations directly; migration continues via the provider.                                                       |
| Promotion chain                | 🟢 Green   | `promote.intent.created` → front matter `review_state: promoted` → reindex → searchable.                                                                                  |
| Promotion worker/agent         | 🟡 Yellow  | JSONL queue updates front matter and optional file moves; automatic reindex/outbox flow still manual.                                                                      |
| Promotion Agent PER wrapper    | 🟢 Green   | Cooldown and idempotence enforced; emits `promote.done` and can schedule batch file moves.                                                                                 |
| ObjectStore ingestion          | 🟢 Green   | `capture_ingest` writes Markdown and calls `save_object(emit_outbox=True)` with the app UUID.                                                                              |
| Outbox / event propagation     | 🟡 Stable  | Table emits via ObjectStore and `events.jsonl`; consumer loop is still manual while broker-backed ADR remains pending.                                                     |
| UUID policy                    | 🟢 Green   | UUID stays writable, NOT NULL, UNIQUE, matching Obsidian front matter and Store records.                                                                                  |
| RelationIndex / relations      | 🟢 Green   | `RelationIndex.link/neighborhood` supports provenance queries.                                                                                                            |
| Index / search pipeline        | 🟡 Stable  | Deterministic embeddings with UUID-stable upsert; BM25 + vector weighting now comes from `system-settings.yaml`; cross-encoder rerank and automated reindex triggers next. |
| Hybrid search (`/search`)      | 🟢 Green   | BM25 + vector cosine blend with weighting sourced from `system-settings.yaml`.                                                                                            |
| Offline / in-memory harness    | 🟢 Green   | Pytest runs entirely without Postgres using memory stores and the SoT reference model.                                                                                    |
| `system-settings.yaml` schema  | 🟢 Green   | Validated in tests and enforced via `make smoke`.                                                                                                                         |
| OpenTelemetry / tracing        | 🟡 Partial | Spans emit `trace_id`; OTLP/Jaeger path is proven manually but not yet asserted in CI and depends on optional packages.                                                   |
| MergeResolverAgent             | 🟢 Green   | Semantic merge provides `status`/`reason` and prevents UUID drift or regression.                                                                                          |
| merge_driver CLI               | 🟡 Yellow  | CLI exists and is tested; writes merged text to stdout and exits non-zero when conflicts remain.                                                                          |
| Git merge driver integration   | 🟡 Planned | Need to wire the CLI into `.gitattributes` so `%A` updates automatically.                                                                                                  |
| NoteHygieneAgent               | 🟢 Green   | Cleans link-only notes, archives empties, emits `cleanup.done`; scheduling/outbox consumer still pending.                                                                 |
| Hygiene scheduling             | 🟡 Planned | Periodic run configuration (launchd/cron/worker loop) plus CI assertions outstanding.                                                                                     |
| Classifier v2 guard            | 🟡 Yellow  | Tests guarded via `SKIP_CLASSIFIER_TESTS=1`; rewrite scheduled for the upcoming sprint.                                                                                   |

## v4.5 Addendum

**Components (delta)**
- OCR Adapter: **In Progress** — structure-aware Markdown + table JSON.
- AV Pipeline (Step A): **In Progress** — detect/normalize/ASR → `segments.jsonl`.
- Cross-encoder Rerank: **Planned** — query-time rerank for top-N.
- RelationIndex v1 (speakers/entities): **Planned**.

**Events now in use (superset)**
- `ocr.document.completed`, `text.chunk.created`, `index.embedding.created`
- `av.ingest.detected`, `av.audio.extracted`, `av.asr.completed`, `av.diarization.completed`
- `promote.done` | `promote.pending_move` | `promote.error`

**Fitness targets / guardrails**
- **QAS-003**: `search_p95_ms ≤ 250`.
- **QAS-010**: `outbox→index ≤ 2s`.
- **RAG-accuracy@n**: eval suite (text + AV) tracked in CI.

## Current focus
- Harden Store layer; Outbox consumer drives Indexer/Reviewer by UUID + `trace_id`.
- Migrate retrieval to include lightweight cross-encoder rerank.
- Keep legacy event aliases active while migrating agents/logs to canonical `subject.verb.state`.
- Keep Obsidian + ObjectStore mirrors in sync (UUID + `review_state` invariants).
- Extract `/agent`, `/interesting`, `/dashboard` into routers while keeping the lifespan shim lean.
- Consolidate store usage via `app/stores/provider.py`; phase out direct `PgObjects`/`MemoryObjects`.
- Instrument event logging (`trace_id`, topic) around store writes.
- Clean up `_legacy/` imports after the new wiring lands.
- Kick off Classifier v2 and reopen the test suite.

## CI / Smoke status
- ✅ `make smoke` runs:
  - Settings schema validation (`tests/system/test_settings_schema.py`).
  - Index rules / ignore rules (three curated tests under `tests/index/`).
  - Promotion worker roundtrip (intent → promoted → indexed).
  - Promotion smoke suite.
  - Merge smoke (front matter preserved, UUID stable, `status`/`reason` present, no regression).
  - Merge driver CLI roundtrip.
  - Hygiene behaviour.
- 🔜 GitHub Actions must enforce the full smoke bundle (settings schema, promotion smoke, merge smoke, merge driver CLI smoke).

## Outstanding work (targets for v4.4→v4.5)
- Wire `app/cli/merge_driver.py` into git so semantic merge becomes default for `.md`.
- Add Hygiene as scheduled maintenance with audit + `trace_id`; add CI assertions.
- Extend CI to cover Store contracts and Outbox payload shapes.
- Finalise event schemas; add schema lint in CI.
- Broker-backed Outbox ADR; keep SLA ≤2s end-to-end.
- Build minimal eval suite for OCR/AV so QAS-003/QAS-010 guardrails include mixed media.

## Sprint Definition of Done (v4.5 slice)
- Routers extracted: `/agent`, `/interesting`, `/dashboard` live in `app/api/routers/{agent.py,interesting.py,dashboard.py}` and are imported from `app/main.py`.
- Store provider used everywhere; no direct DB imports outside stores/db/alembic (guard must be green).
- Store writes emit event-log entries with at least `trace_id` and topic.
- CI: smoke workflow is green in GitHub Actions.

## Alignment / Constraints
- Auditability and provenance cannot regress during store/ingestion evolution.
- Outbox choreography remains the bridge between persistence and async processing.
- Human-first review and promotion flows remain unchanged.
- Performance envelopes (`QAS-003: p95 < 250 ms`) remain hard constraints.

## Open risks
- Promotion → index remains manual; without auto-reindex, promoted material may miss the search view.
- Outbox lacks a consumer, so downstream agents do not trigger without an external process.
- Tracing is best-effort: without `opentelemetry`, spans downgrade to no-op; observability plan still pending.

## Quick ops notes
- **Backend toggle:** `STORE_BACKEND=pg|memory` (default: auto); set `DATABASE_URL=...` for Postgres.
- **Reset in-memory stores (tests):**
  ```python
  from app.stores.provider import reset_memory_stores
  reset_memory_stores()
  ```
- **Classifier tests:** set `SKIP_CLASSIFIER_TESTS=0` to re-enable the v2 tests.

## Confidence
- Core ingestion → ObjectStore → Outbox → index → search loop is solid and UUID-stable.
- Merge safety is trustworthy; hygiene actions remain consistent with policy.
- Observability is instrumented; CI enforcement is the next step.

## Docs follow-ups
- Update `ARCHITECTURE.md` (Store abstraction + Vector/Relation index), `ROADMAP.md` (router extraction), and the Promotion Agent section to reflect the current design.
