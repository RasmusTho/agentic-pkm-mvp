# Status — Operational Snapshot

| Version | Goal | Delivered | Open | Next | Notes |
| --- | --- | --- | --- | --- | --- |
| v4.4 | Observability + Store abstraction | JSONL audit, Outbox, Core-6 identity | None | Keep doc set frozen | Stable legacy cut |
| v4.5A | Deterministic ingestion baseline | Full PER loop, promotion cooldowns, memory CI | Route ingestion polish to v4.5B | Monitor metrics + guard rails | Current green baseline |
| v4.5B | Unified ingestion polish + hook readiness | P1 rerank hook behind flags + P2 chunk/dedup pipeline | Diarization wiring, RelationIndex fitness harness | Enable hooks in staging with metrics | In development, needs acceptance tests |
| v4.6 | Retrieval quality uplift | Objective B delivered (RelationIndex gate + audit), ce_local/diarization/golden eval in progress | Objective A/C/D hardening, relation coverage ≥95% | Prototype cross-encoder + diarization PER loops | Blocked on provider commitments |
| v5.x | Symbolic reasoning + reflexive agents | Governance concepts, Agent Memory Graph sketches | RDF/OWL/SHACL enforcement, logic gates | Define policy bundles + knowledge graph API | Dependent on v4.6 telemetry |

## CI & Test Markers
- Last CI run: PASS — `pytest -q -m "not pg"` (STORE_BACKEND=memory, LLM_PROVIDER=mock, audit JSONL enabled).
- Mermaid export: PASS — `docker run --rm -v $(pwd)/tmp:/data minlag/mermaid-cli -i /data/diagram.mmd -o /data/diagram.svg`.
- Chunk/dedup coverage: PASS — `pytest -q -m "not pg" -k "chunk_dedup"`.
- Fitness: PASS — `python -m app.fitness.report` (latest sample: QAS-003 p95=0.00033 s, QAS-010 p95=0.0000067 s).
- Golden evaluation: PASS — `pytest -q -m "not pg" -k "golden_metrics"` (precision@3 = 0.67, nDCG@3 = 0.78 aggregate).
- Relation coverage sample: 50% of promoted items (golden relations corpus).

## Metrics Snapshot
- QAS-003 p95: 0.00033 s
- QAS-010 p95: 0.0000067 s
- Golden P@10 / nDCG@10: 0.40 / 0.97 (ce_local), baseline 0.40 / 0.97
- Relation coverage: 50% (golden sample)

## Outstanding Blockers
- Cross-encoder provider contract for v4.6 reranker (decision pending between OpenAI and local model).
- Production diarization sample set requires legal approval for sharing audio traces.
- RelationIndex fitness benchmark tooling lacks test data beyond 10k objects.

## Ready for Tagging
- [x] v4.5A baseline
- [ ] v4.5B polish release (P1 rerank + P2 chunk/dedup complete)
- [ ] v4.6 feature release
