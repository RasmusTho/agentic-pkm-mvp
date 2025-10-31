# STATUS — 2025-10-30

_Snapshot of current system health._

| Component                        | Status    | Notes                                                                                         |
|----------------------------------|-----------|-----------------------------------------------------------------------------------------------|
| Promotion chain                  | 🟢 Green  | `promote.intent.created` → frontmatter `review_state: promoted` → reindex → searchable       |
| Promotion Agent PER wrapper      | 🟢 Green  | Enforces cooldown/idempotence; emits `promote.done`; can schedule batch file moves           |
| Indexer / Embeddings             | 🟢 Green  | Deterministic embeddings; UUID-stable upsert; hybrid search boosts higher review_state       |
| Hybrid search (`/search`)        | 🟢 Green  | BM25-style lexical + vector cosine; weighting rules from `system-settings.yaml`              |
| Capture Layer                    | 🟡 Planned| Agents mirror external sources into vault + Postgres; emit `capture.object.created` events   |
| system-settings.yaml schema      | 🟢 Green  | Schema-validated in tests; `make smoke` enforces shape                                       |
| Outbox / event propagation       | 🟡 Stable | File/JSONL outbox + Redis fan-out works locally; broker-backed fanout (Kafka/Debezium) TBD   |
| OpenTelemetry / Jaeger tracing   | 🟡 Partial| Spans emitted with `trace_id`; Jaeger path proven manually; not yet asserted in CI           |
| MergeResolverAgent               | 🟢 Green  | Semantic merge with safety rails; returns `status`/`reason`; prevents UUID drift/regression  |
| merge_driver CLI                 | 🟡 Yellow | Exists + tested (unit/smoke). Writes merged text to stdout; exit!=0 on unresolved/conflict.  |
| Git merge driver integration     | 🟡 Planned| We still need to wire the CLI into `.gitattributes`/git config so `%A` is updated automatically |
| NoteHygieneAgent                 | 🟢 Green  | Salvages link-only notes, archives empties, moves oversized dumps; emits `cleanup.done`      |
| Hygiene scheduling               | 🟡 Planned| Needs periodic run config (launchd/cron/worker loop) and CI assertions to guard data safety  |
| CI smoke gate                    | 🟡 Partial| `make smoke` is green locally (settings, promotion, merge, hygiene) but not fully enforced in GH Actions yet |

## Current focus
- Introduce ObjectStore as the canonical persistence boundary. Normalizer / Capture flows are being refactored to write through the Python ObjectStore interface instead of raw psycopg.
- Prove the Store pattern end-to-end with the first agent (Normalizer or capture_ingest CLI). Once stable, roll the same interface out to Reviewer, SetEvaluator, Projector, Promotion Agent, and Indexer.
- Ensure Obsidian edits continue to reflect immediately in ObjectStore so UUID, `review_state`, and provenance stay in sync.

## CI / Smoke status
- ✅ `make smoke` runs:
  - settings schema validation
  - index rules / ignore rules
  - promotion worker roundtrip (intent → promoted → indexed)
  - promotion smoke
  - merge smoke (`merge_note_from_blobs` contract: single frontmatter, no review_state regression, UUID invariant)
  - merge driver CLI roundtrip (`run_merge` exit code, `status`, `reason`)
  - hygiene behaviour
- 🔜 GitHub Actions needs to enforce (at least): settings schema, promotion smoke, merge smoke, merge driver CLI smoke.

## Outstanding work (targets for v4.4)
- Wire `app/cli/merge_driver.py` into git so semantic merge becomes the default for `.md`.  
  - Ensure merged markdown actually lands in `%A`.  
  - Non-zero exit → git stops and asks a human.
- Finish ObjectStore refactor for ingestion so agents no longer call the database directly. Capture/Normalizer path is first.
- Add hygiene as a scheduled maintenance step with audit + `trace_id`. Add smoke assertions so it can’t silently delete real content.
- Extend smoke/CI to assert Promotion Agent emits spans (`trace_id`, `promote.done`) so promotion remains observable.
- Draft ADR for broker-backed outbox (Debezium/Kafka). Goal: end-to-end latency ≤2s for ingestion/promotion → indexed.
- Define interfaces/stubs for VectorIndex and RelationIndex / KnowledgeGraphStore so agents can call them without worrying about backend moves.
- Enforce UUID as canonical identity (remove remaining surrogate IDs) and update tests accordingly.
- Update docs (`docs/ARCHITECTURE.md`, `docs/ROADMAP.md`) to reflect SoT v4.4 direction. ✅ (this change)
- Begin preparing tests that mock Stores so agents can run in isolation without spinning up Postgres.

## Alignment / Constraints
- Auditability and provenance (`trace_id`, `source_ref`, `review_state`) cannot regress during the store rollout.
- Outbox-driven event choreography remains the bridge between persistence and async processing; QAS-010 (outbox → index ≤ 2s) stays in force.
- Human-first review and promotion flow via Obsidian + Promotion Agent is unchanged. SetEvaluator, Reviewer, Projector, Indexer, and Promotion Agent stay live in the pipeline.
- Performance envelopes such as QAS-003 (search p95 < 250 ms) remain hard constraints while Stores evolve.
- The Store layer is an architectural evolution within SoT v4.4. It does not replace PER loops, the Outbox pattern, or the “människa först” governance model.

## Confidence
- Core ingestion → index → search → promote is solid.
- Merge safety is trustworthy locally: we don't silently drop UUID or downgrade review_state, and we always produce `reason`.
- Hygiene actions are consistent with policy in tests.
- Observability is instrumented but not yet enforced in CI.

Overall system state: 🟢 progressing toward v4.4 hardening.
