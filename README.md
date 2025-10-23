# Second-Brain / WS Baseline

**Source of truth** for policies, architecture, and agent behavior is the Canvas
“AI-assisterat Second Brain — Konsoliderad grund”. Files in `data/context/` are the
versioned, machine-readable mirror. WS scope = single node, minimal agents,
BM25+pgvector (later), no reranker, inproc bus.

## Quickstart (WS)
1) docker compose up -d --build
2) open http://localhost:18000/query?q=hello
3) scripts/ingest_ws.py  # writes simple audit
4) scripts/query_ws.py "hello"  # asserts citations
