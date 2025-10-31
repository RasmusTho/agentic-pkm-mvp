# STATUS — 2025-10-30

_Snapshot of current system health._

| Component                        | Status    | Notes                                                                                         |
|----------------------------------|-----------|-----------------------------------------------------------------------------------------------|
| Promotion chain                  | 🟢 Green  | `promote.intent.created` → frontmatter `review_state: promoted` → reindex → searchable       |
| Promotion Agent PER wrapper      | 🟢 Green  | Enforces cooldown/idempotence; emits `promote.done`; can schedule batch file moves           |
| Indexer / Embeddings             | 🟢 Green  | Deterministic embeddings; UUID-stable upsert; hybrid search boosts higher review_state       |
| Hybrid search (`/search`)        | 🟢 Green  | BM25-style lexical + vector cosine; weighting rules from `system-settings.yaml`              |
| ObjectStore ingestion            | 🟢 Green  | capture_ingest CLI writes Markdown + calls `save_object(emit_outbox=True)` with app UUID     |
| UUID policy                      | 🟢 Green  | UUID is writable, NOT NULL, UNIQUE, and matches Obsidian frontmatter / Stores                |
| RelationIndex / relations table  | 🟢 Green  | `relations` table live; `RelationIndex.link/neighborhood` usable for provenance              |
| Capture Layer                    | 🟢 Green  | Human capture validated end-to-end via Store + Outbox                                        |
| system-settings.yaml schema      | 🟢 Green  | Schema-validated in tests; `make smoke` enforces shape                                       |
| Outbox / event propagation       | 🟡 Stable | Outbox table emits via ObjectStore; consumer loop still manual; broker-backed ADR pending    |
| OpenTelemetry / Jaeger tracing   | 🟡 Partial| Spans emitted with `trace_id`; Jaeger path proven manually; not yet asserted in CI           |
| MergeResolverAgent               | 🟢 Green  | Semantic merge with safety rails; returns `status`/`reason`; prevents UUID drift/regression  |
| merge_driver CLI                 | 🟡 Yellow | Exists + tested (unit/smoke). Writes merged text to stdout; exit!=0 on unresolved/conflict.  |
| Git merge driver integration     | 🟡 Planned| We still need to wire the CLI into `.gitattributes`/git config so `%A` is updated automatically |
| NoteHygieneAgent                 | 🟢 Green  | Salvages link-only notes, archives empties, moves oversized dumps; emits `cleanup.done`      |
| Hygiene scheduling               | 🟡 Planned| Needs periodic run config (launchd/cron/worker loop) and CI assertions to guard data safety  |
| CI smoke gate                    | 🟡 Partial| `make smoke` is green locally (settings, promotion, merge, hygiene) but not fully enforced in GH Actions yet |

## Current focus
- Harden the new Store layer: capture_ingest is live on ObjectStore; Promotion Agent migration (load/update/save with `emit_outbox=False` + RelationIndex links) is next.
- Wire Indexer / Reviewer to consume the Outbox table by UUID + `trace_id` instead of ad-hoc polling.
- Keep Obsidian + ObjectStore mirrors in sync so human edits keep the UUID / `review_state` contract intact.

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
- Add hygiene as a scheduled maintenance step with audit + `trace_id`. Add smoke assertions so it can’t silently delete real content.
- Extend smoke/CI to cover Store contracts: ObjectStore/VectorIndex/RelationIndex API tests and Outbox payload shape must stay green in CI.
- Migrate Promotion Agent to ObjectStore (`get_object` → mutate → `save_object(emit_outbox=False)`) and emit RelationIndex provenance edges on promotion.
- Enforce the “no direct INSERT into `objects`/`outbox`” rule in code review tooling.
- Draft ADR for broker-backed outbox (Debezium/Kafka). Goal: end-to-end latency ≤2s for ingestion/promotion → indexed.
- Build the Outbox consumer loop that drives Indexer / Reviewer using UUID + `trace_id`.
- Begin preparing tests that mock Stores so agents can run in isolation without spinning up Postgres.

## Alignment / Constraints
- Auditability and provenance (`trace_id`, `source_ref`, `review_state`) cannot regress during the store rollout.
- Outbox-driven event choreography remains the bridge between persistence and async processing; QAS-010 (outbox → index ≤ 2s) stays in force.
- Human-first review and promotion flow via Obsidian + Promotion Agent is unchanged. SetEvaluator, Reviewer, Projector, Indexer, and Promotion Agent stay live in the pipeline.
- Performance envelopes such as QAS-003 (search p95 < 250 ms) remain hard constraints while Stores evolve.
- The Store layer is an architectural evolution within SoT v4.4. It does not replace PER loops, the Outbox pattern, or the “människa först” governance model, but its guardrails (ObjectStore/VectorIndex/RelationIndex only) are now policy.

## Confidence
- Core ingestion → ObjectStore → Outbox → index → search loop is solid and UUID-stable.
- Merge safety is trustworthy locally: we don't silently drop UUID or downgrade review_state, and we always produce `reason`.
- Hygiene actions are consistent with policy in tests.
- Observability is instrumented but not yet enforced in CI.

Overall system state: 🟢 progressing toward v4.4 hardening.
