# SoT v4.1 – MVP Ingestion
## Mål
1. End-to-end: Ingestor → Normalizer → Classifier → Chunker → Deduper → CitationChecker → Indexer → Reviewer → SetEvaluator → Projector på litet korpusprov.
2. Full audit/trace per steg (trace_id följer objekt).
3. BM25 + pgvector; chunk-proveniens (id+offsets) verifierad.
4. Reviewer: seed→note auto vid confidence ≥ 0.7; annars feedback.
5. Projector: endast whitelist (maturity, trust, aliases, related, parent, canonical, sets, scope, relevance_score). Core-6 orörd.

## Scope
In scope: agenter (PER-loop), events, indexering, scorecards, audit, minimal WS-routing.
Out of scope: reranker, autoskalning, fjärr-connectors (utöver bas), AnswerComposer/QueryRouter-förfining.

## Ramverk & Repo
Python 3.11+, LangGraph-bas. Postgres 16 + pgvector, BM25 lite in-memory. In-proc events.
app/search/embeddings.py och app/search/vector_index.py (PgVectorIndex) används; BM25 finns i app/search/bm25_lite.py.

## Definition of Done
- Unit + contract-tester för alla agenter.
- E2E-smoke: 3 filer → index → reviewer → projector → audit/trace komplett.
- DB-tabeller enligt SoT v4.1: objects, chunks, embeddings, relations, sets, membership, decisions, audit.
- CI: pytest + snabb e2e (≤2 min på <500 dokument).

## TDD-ordning
1) Normalizer → 2) Classifier → 3) Chunker → 4) Deduper → 5) CitationChecker → 6) Indexer → 7) Reviewer → 8) SetEvaluator → 9) Projector → 10) E2E

## Event & Audit
Event: type, payload_ref, attrs{object_id,maturity,trust,scope}, trace_id
Audit: event_id | object_id | agent | action | ts | trace_id | details(json)

## Scorecards
ingestion_quality: frontmatter_core6_complete, chunk_semantics_ok
retrieval_answering: faithfulness ≥ 0.8, provenance ≥ 0.8
