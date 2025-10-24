# Second-Brain / Walking Skeleton (WS)
**Source of truth** is the Canvas “AI-assisterat Second Brain — Konsoliderad grund”.
`data/context/` mirrors Canvas policies; WS runs single node (Docker) with minimal agents,
BM25-lite (inside API for now), pgvector via Postgres, no reranker, inproc bus.

- Start WS: `docker compose up -d --build` then `GET http://localhost:18000/query?q=hello`
- Golden set: `golden/*`
- Context: `data/context/*.yaml`
- WS overview: `docs/OVERVIEW_WS.md`
- Legacy docs archived at `docs/legacy/` (kept for reference; superseded by WS + Canvas).

### LangGraph (POC, decoupled)
This repo includes a small LangGraph demo under `app/langgraph/` to explore future agent flows.
It is **not** wired into WS runtime yet. Run: `python app/langgraph/ws_graph.py`

## SoT v4.1 – MVP Ingestion (TDD)
- End-to-end: Ingestor → Normalizer → Classifier → Chunker → Deduper → CitationChecker → Indexer → Reviewer → SetEvaluator → Projector
- Core-6 i DB (AMG), projector speglar whitelist.
- Index: pgvector + in-memory BM25Lite (MVP).

## Dokumentation
- docs/SoT-v4.1.md
- docs/PLAN.md
- docs/TESTS.md
- docs/FRONTMATTER.md
- docs/ARCHITECTURE.md
- docs/EVENTS.md
- docs/SCORECARDS.md
