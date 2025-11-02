
docs/STATUS.md

# STATUS — Snapshot (2025-10-31)

_Snapshot of current system health._

| Component                                 | Status   | Notes                                                                                          |
|-------------------------------------------|----------|------------------------------------------------------------------------------------------------|
| Promotion chain                           | 🟢 Green | `promote.intent.created` → front matter `review_state: promoted` → reindex → searchable        |
| Promotion Agent PER wrapper               | 🟢 Green | Cooldown/idempotence; emits `promote.done`; can schedule batch file moves                      |
| Indexer / Embeddings                      | 🟢 Green | Deterministic embeddings; UUID-stable upsert; hybrid search boosts higher `review_state`       |
| Hybrid search (`/search`)                 | 🟢 Green | BM25 + vector cosine; weighting rules from `system-settings.yaml`                              |
| ObjectStore ingestion                     | 🟢 Green | capture_ingest writes Markdown + calls `save_object(emit_outbox=True)` with app UUID           |
| UUID policy                               | 🟢 Green | UUID is writable, NOT NULL, UNIQUE, and matches Obsidian front matter / Stores                 |
| RelationIndex / relations table           | 🟢 Green | `RelationIndex.link/neighborhood` usable for provenance                                        |
| Offline test harness (in-memory Stores)   | 🟢 Green | Pytest runs without Postgres; mirrors SoT reference model                                      |
| system-settings.yaml schema               | 🟢 Green | Schema-validated in tests; enforced in smoke gates                                             |
| Outbox / event propagation                | 🟡 Stable| Table emits via ObjectStore; consumer loop still manual; broker-backed ADR pending             |
| OpenTelemetry / Jaeger tracing            | 🟡 Partial| Spans emitted with `trace_id`; Jaeger path proven manually; not yet asserted in CI             |
| MergeResolverAgent                        | 🟢 Green | Semantic merge with safety rails; returns `status`/`reason`; prevents UUID drift/regression    |
| merge_driver CLI                          | 🟡 Yellow| Exists + tested; writes merged text to stdout; exit!=0 on unresolved/conflict                  |
| Git merge driver integration              | 🟡 Planned| Wire CLI into `.gitattributes`/git config so `%A` is updated automatically                     |
| NoteHygieneAgent                          | 🟢 Green | Salvages link-only notes, archives empties, moves oversized dumps; emits `cleanup.done`        |
| Hygiene scheduling                        | 🟡 Planned| Periodic run config (launchd/cron/worker loop) + CI assertions                                 |

## v4.5 Addendum

**Components (delta)**
- OCR Adapter: **In Progress** — structure-aware Markdown + table JSON
- AV Pipeline (Step A): **In Progress** — detect/normalize/ASR → `segments.jsonl`
- Cross-encoder Rerank: **Planned** — query-time rerank for top-N
- RelationIndex v1 (speakers/entities): **Planned**

**Events now in use (superset)**
- `ocr.document.completed`, `text.chunk.created`, `index.embedding.created`
- `av.ingest.detected`, `av.audio.extracted`, `av.asr.completed`, `av.diarization.completed`
- `promote.done` | `promote.pending_move` | `promote.error`

**Fitness targets**
- **QAS-003**: `search_p95_ms ≤ 250`
- **QAS-010**: `outbox→index ≤ 2s`
- **RAG-accuracy@n**: eval suite (text + AV) tracked in CI

## Current focus
- Harden Store layer; Outbox consumer drives Indexer/Reviewer by UUID + `trace_id`.
- Migrate retrieval to include lightweight cross-encoder rerank.
- Keep legacy event aliases active while migrating agents/logs to canonical `subject.verb.state`.
- Keep Obsidian + ObjectStore mirrors in sync (UUID + `review_state` invariants).

## CI / Smoke status
- ✅ `make smoke` runs:
  - settings schema validation
  - index rules / ignore rules
  - promotion worker roundtrip (intent → promoted → indexed)
  - promotion smoke
  - merge smoke (front matter preserved, UUID stable, `status`/`reason` present, no regression)
  - merge driver CLI roundtrip
  - hygiene behaviour
- 🔜 GitHub Actions must enforce at least: settings schema, promotion smoke, merge smoke, merge driver CLI smoke.

## Outstanding work (targets for v4.4→v4.5)
- Wire `app/cli/merge_driver.py` into git so semantic merge becomes default for `.md`.
- Add Hygiene as scheduled maintenance with audit + `trace_id`; add CI assertions.
- Extend CI to cover Store contracts and Outbox payload shapes.
- Finalise event schemas; add schema lint in CI.
- Broker-backed Outbox ADR; keep SLA ≤2s end-to-end.
- Build minimal eval suite for OCR/AV so QAS-003/QAS-010 guardrails include mixed media.

## Alignment / Constraints
- Auditability and provenance cannot regress during store/ingestion evolution.
- Outbox choreography remains the bridge between persistence and async processing.
- Human-first review and promotion flows remain unchanged.
- Performance envelopes (QAS-003: p95 < 250 ms) remain hard constraints.

## Confidence
- Core ingestion → ObjectStore → Outbox → index → search loop is solid and UUID-stable.
- Merge safety is trustworthy; hygiene actions consistent with policy.
- Observability is instrumented; CI enforcement is the next step.