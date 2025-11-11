# Roadmap — Strategic Control

## Version Ladder Overview
| Version | Intent | State |
| --- | --- | --- |
| v4.3 | Establish the PER ingest loop, Outbox wiring, and CI contracts. | Delivered |
| v4.4 | Harden observability, Store abstraction, and identity plus conflict handling. | Delivered |
| v4.5A | Stabilize unified ingestion, enforce deterministic memory-first CI, and document promotion rules. | Delivered |
| v4.5B | Fitness guards + ingestion polish, rerank + chunk dedup readiness. | Delivered |
| v4.6 | Retrieval quality upgrades (cross-encoder, diarization adapter, RelationIndex fitness, golden eval). | Active |
| v4.7 | Reasoning layer & reflexive agents over the knowledge graph. | Planned |

## Current Stable Baseline (v4.5A)
v4.5A is the deployable baseline: Normalizer→PromotionAgent path is verified end-to-end, promotion cooldowns are enforced, and CI is green when `pytest -q -m "not pg"` passes using `STORE_BACKEND=memory` and mock LLMs. Architectural invariants to preserve: Core-6 frontmatter is immutable once normalized, Outbox events remain append-only, PromotionAgent decisions are idempotent, and audit logs stay deterministic JSONL. Any change that violates these invariants or introduces non-deterministic mocks must be postponed to v4.5B+.

## Delivered: v4.5B Fitness & Hook Readiness
- Unified chunking + dedup pipeline via `app.ingest.chunk_policy` and `app.ingest.deduper`, surfaced through `app.agents.pipeline.ingest_and_chunk()`.
- Rerank hook integrated after hybrid search with provider matrix and `hook_adapter`.
- CI fitness guards: `app.fitness.metrics.qas003_hybrid_latency()` and `qas010_outbox_to_index_latency()` enforce QAS-003 and QAS-010 thresholds; GitHub smoke workflow prints their JSON reports.
- Documentation aligned (Architecture/Roadmap/Status) and status board lists P1 (rerank) + P2 (chunk/dedup) as delivered.

## Active Work (v4.6)
### Objective A — Cross-Encoder Rerank Provider
Add `ce_local` (deterministic overlap scoring) and `ce_http` (flagged HTTP adapter) behind the existing rerank hook. Providers are invoked only when `RERANK_ENABLE=1` and fall back to `mock_ce`/`none` when unavailable. Acceptance: provider selection tests, HTTP client mocked in CI, golden metrics stay ≥ baseline.

### Objective B — Relation Index v1 + Orphan Gate
Implement in-memory RelationIndex CRUD + `has_any()`, propagate provenance links, and gate promotions with the orphan guard (`PROMOTION_ALLOW_ORPHANS` override). Acceptance: relation coverage metrics and tagging readiness require ≥95% promoted objects linked.

### Objective C — Diarization Hook
`DIARIZE_ENABLE` toggles segmentation; providers include `none`, `mock`, and `external` (HTTP). Metadata preserves `{speaker, text}` entries so ingestion/promotion retain conversation context. Acceptance: mock provider yields ≥2 segments, disabled path is unchanged, no CI dependency on external ASR.

### Objective D — Golden Set + Evaluation Metrics
Ship synthetic corpus (`data/golden/*`), compute Precision@k and nDCG@k, and assert rerank quality never drops below baseline. Evaluation runs inside the not-pg suite and feeds governance dashboards.

### Operational Acceptance
- Latency guard: ingest→index p95 remains ≤ 2 s while hooks and dedup are enabled.
- Promotion safety: PromotionAgent cooldown metrics show <2% replays per day and orphan gate coverage ≥95%.
- Documentation + CHANGELOG updated whenever code changes land.

## Forward Outlook (v4.7)
v4.7 establishes the reasoning layer: symbolic policies (RDF/OWL/SHACL), reflexive agents that learn from promotion outcomes, and logic-gate governance for cross-object decisions. Work begins once v4.6 objectives A–D reach green status.

## Forward Outlook (v5.x)
Symbolic reasoning layer adds RDF/OWL/SHACL validation before promotion. Knowledge graph services expose RelationIndex externally for governance queries. Logic gates allow Reviewer/PromotionAgent to assert multi-object policies. Reflexive agents learn from audit feedback to auto-tune PER plans without skipping human checkpoints.

## Governance & CI Contract
- Green means: `pytest -q -m "not pg"` passes, docs lint (markdownlint + vale) is clean, `docs/DIAGRAMS.md` exports without mermaid errors, and audit replay tests remain deterministic.
- Maturity states: inbox → processed → promoted → evergreen. Inbox objects may be dropped, processed objects must retain Core-6, promoted objects require Reviewer approval, and evergreen objects are eligible for publication + search.
- Update ritual: after each increment, Codex opens a PR that regenerates STATUS (CI snapshot + blockers), refreshes ROADMAP acceptance criteria, and cross-links ARCHITECTURE when new agents or stores appear. No increment closes until these docs reflect reality.
