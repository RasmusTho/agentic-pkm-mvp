# Status — Operational Snapshot

| Version | Goal | Delivered | Open | Next | Notes |
| --- | --- | --- | --- | --- | --- |
| v4.4 | Observability + Store abstraction | JSONL audit, Outbox, Core-6 identity | None | Keep doc set frozen | Stable legacy cut |
| v4.5A | Deterministic ingestion baseline | Full PER loop, promotion cooldowns, memory CI | Route ingestion polish to v4.5B | Monitor metrics + guard rails | Current green baseline |
| v4.5B | Fitness guards + ingestion polish | Delivered 2025-02-14 — rerank hooks, chunk/dedup, CI gates | — | Prep v4.6 rollout, keep fitness monitors green | Ready for tagging |
| v4.6 | Retrieval quality uplift (Objectives A–D active) | Objective B delivered (RelationIndex gate + audit), ce_local/diarization/golden eval in progress | Objective A/C/D hardening, relation coverage ≥95%; issues #55–#58 track work | Prototype cross-encoder + diarization PER loops | Blocked on provider commitments |
| v5.x | Symbolic reasoning + reflexive agents | Governance concepts, Agent Memory Graph sketches | RDF/OWL/SHACL enforcement, logic gates | Define policy bundles + knowledge graph API | Dependent on v4.6 telemetry |

## v4.5B Delivery Summary (2025-02-14)
- Fitness gates enforced with deterministic QAS-003 hybrid-search and QAS-010 outbox→index probes.
- Cross-encoder providers (`ce_local`, `ce_http`) hardened with deterministic fallback paths and golden-set evaluation.
- RelationIndex `has_any()` plus Promotion orphan gate enforced by default; overrides require reason and are audited.
- Diarization hook integrated; speaker metadata flows into chunking when `DIARIZE_ENABLE=1`.
- Golden evaluation pipeline (P@k, nDCG@k) wired into CI summary.
- Doc-integrity gating and v4.6 PR/issue templates active for every submission.

## CI & Test Markers
- Last CI run: PASS — `pytest -q -m "not pg"` (STORE_BACKEND=memory, LLM_PROVIDER=mock, audit JSONL enabled).
- Mermaid export: PASS — `docker run --rm -v $(pwd)/tmp:/data minlag/mermaid-cli -i /data/diagram.mmd -o /data/diagram.svg`.
- Chunk/dedup coverage: PASS — `pytest -q -m "not pg" -k "chunk_dedup"`.
- Fitness: PASS — `python -m app.fitness.report` (latest sample: QAS-003 p95=0.000149 s, QAS-010 p95=0.000006 s).
- Golden evaluation: PASS — `pytest -q -m "not pg" -k "golden_metrics"` (ce_local vs baseline at P@10/nDCG@10 parity).
- Relation coverage sample: 50% of promoted items (golden relations corpus).

## Metrics Snapshot
- QAS-003 p95: 0.000149 s
- QAS-010 p95: 0.000006 s
- Golden P@10 / nDCG@10: 0.20 / 0.97 (ce_local), baseline 0.20 / 0.97 (no regression yet)
- Relation coverage: 50% (golden sample)

### Latest CI Snapshot
CI SUMMARY LATENCY QAS003=0.000149s QAS010=0.000006s  
CI SUMMARY EVAL P10=0.200 NDCG10=0.969 BASE_P10=0.200 BASE_NDCG10=0.969  
CI SUMMARY EVAL DELTA DP10=+0.000 DnDCG10=+0.000 RELATION_TARGET=60%  
CI SUMMARY RELATION COVERAGE=50.00%

## Outstanding Blockers
- Cross-encoder provider contract for v4.6 reranker (decision pending between OpenAI and local model).
- Production diarization sample set requires legal approval for sharing audio traces.
- RelationIndex fitness benchmark tooling lacks test data beyond 10k objects.

## Ready for Tagging
- [x] v4.5A baseline
- [ ] v4.5B polish release (P1 rerank + P2 chunk/dedup complete)
- [ ] v4.6 feature release
