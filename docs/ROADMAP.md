# Roadmap — Strategic Control

## Version Ladder Overview
| Version | Intent |
| --- | --- |
| v4.3 | Establish the PER ingest loop, Outbox wiring, and CI contracts. |
| v4.4 | Harden observability, Store abstraction, and identity plus conflict handling. |
| v4.5A | Stabilize unified ingestion, enforce deterministic memory-first CI, and document promotion rules. |
| v4.5B | Polish ingestion edges, integrate optional hooks, and hold quality at v4.5A while enabling experiments. |
| v4.6 | Deliver retrieval quality upgrades (cross-encoder, diarization adapter, RelationIndex fitness) with measurable gains. |
| v5 | Introduce symbolic reasoning, logic gates, and reflexive agents over the Agent Memory Graph. |

## Current Stable Baseline (v4.5A)
v4.5A is the deployable baseline: Normalizer→PromotionAgent path is verified end-to-end, promotion cooldowns are enforced, and CI is green when `pytest -q -m "not pg"` passes using `STORE_BACKEND=memory` and mock LLMs. Architectural invariants to preserve: Core-6 frontmatter is immutable once normalized, Outbox events remain append-only, PromotionAgent decisions are idempotent, and audit logs stay deterministic JSONL. Any change that violates these invariants or introduces non-deterministic mocks must be postponed to v4.5B+.

## Active Work (v4.5B)
### Unified Ingestion Polish
Scope: tighten Normalizer ↔ Deduper interfaces, ensure every agent emits structured diffs, and confirm retries replay without double writes.
**Done when** all `ingest.object.*` events include `trace_id`, `object_id`, diff payloads, and unit tests cover failure injection for each agent.

### Hook Integration Points
- Rerank hook: wire `apply_optional_rerank()` after hybrid retrieval, gated by `RERANK_ENABLE` with fallback to identity ordering.
- Diarization hook: land adapters so audio/text captures can attach speaker turns before normalization.
- RelationIndex fitness: verify similarity edges are created for dedupe + citation flows.
**Done when** toggling each hook on/off changes only the targeted subsystem, RelationIndex fitness tests assert ≥95% coverage of duplicate paths, and diarization adapters surface in audit logs.

### Operational Acceptance
- Latency guard: ingest→index p95 remains ≤ 2 s while hooks are enabled.
- Promotion safety: PromotionAgent cooldown metrics show <2% replays per day.
- Documentation: ARCHITECTURE, ROADMAP, STATUS updated with newly stabilized behaviors.

## Next Increment (v4.6)
Objectives: ship a real cross-encoder reranker, productionize the diarization adapter, and close the loop on RelationIndex-based trust scoring. Dependencies: selection of hosted cross-encoder (OpenAI or internal), diarization provider access tokens, and storage sizing for RelationIndex snapshots. Open design questions: batching strategy for the cross-encoder, how diarization metadata influences Core-6, and whether RelationIndex needs TTL for stale relations. Test coverage targets: add golden tests for rerank ordering, diarization PER loop fixtures, and regression tests for relation traversal. Performance fitness: rerank-enabled hybrid search must keep QAS-003 p95 < 300 ms, diarization adapter must process 1-hour audio under 4 minutes offline, and RelationIndex rebuild must finish within 10 minutes for 10k objects.

## Forward Outlook (v5.x)
Symbolic reasoning layer adds RDF/OWL/SHACL validation before promotion. Knowledge graph services expose RelationIndex externally for governance queries. Logic gates allow Reviewer/PromotionAgent to assert multi-object policies. Reflexive agents learn from audit feedback to auto-tune PER plans without skipping human checkpoints.

## Governance & CI Contract
- Green means: `pytest -q -m "not pg"` passes, docs lint (markdownlint + vale) is clean, `docs/DIAGRAMS.md` exports without mermaid errors, and audit replay tests remain deterministic.
- Maturity states: inbox → processed → promoted → evergreen. Inbox objects may be dropped, processed objects must retain Core-6, promoted objects require Reviewer approval, and evergreen objects are eligible for publication + search.
- Update ritual: after each increment, Codex opens a PR that regenerates STATUS (CI snapshot + blockers), refreshes ROADMAP acceptance criteria, and cross-links ARCHITECTURE when new agents or stores appear. No increment closes until these docs reflect reality.
