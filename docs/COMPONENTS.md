# Components Catalog (Reality-MVP)

Canonical list of current modular building blocks. Keep this aligned with the codebase; no future placeholders beyond explicit OCR stubs below.

## Stores
- **ObjectStore (memory/pg)** — Persists Core-6 envelopes + payloads; `app.stores.*`, access via `app.stores.get_object_store()`. Inputs: `{object_id, kind, source_ref, payload}`. Outputs: persisted record + retrieval via `.get/.list_by_kind`. Config: `STORE_BACKEND` (`memory` default, `pg` optional). Maturity: baseline/stable.
- **VectorIndex (memory/pg)** — Embedding storage + similarity search; `app.stores.*`. Inputs: `{object_id, kind, source_ref, payload, embedding, model}`. Outputs: hits with scores. Config: `STORE_BACKEND`, `INDEX_PERSIST_PATH/LOAD` (memory snapshot). Maturity: baseline/stable.
- **RelationIndex/AMG (memory/pg)** — Relation graph storage; `app.stores.*`. Inputs: relation tuples (supports/extends/contradicts/derived_from). Outputs: neighbors/has_any. Config: `STORE_BACKEND`. Maturity: baseline.

## Ingest/PER agents
- **Normalizer** — Reads source markdown, emits Core-6 envelope + payload; `app.agents.normalizer.*`. Inputs: file path. Outputs: `{event=ingest.normalize.done, core6, payload}` saved via ObjectStore. Maturity: baseline.
- **Classifier** — Tags type/trust/tags; `app.agents.classifier.*`. Inputs: object_id + payload text. Outputs: classification decision recorded in DecisionsStore; env: `LLM_PROVIDER` (mock/default). Maturity: baseline.
- **Chunker** — Splits text into spans; `app.agents.chunker.*`. Inputs: object_id + text. Outputs: chunk set events. Config: chunk sizes/max tokens. Maturity: baseline.
- **Deduper** — Heuristic dup detection; `app.agents.deduper.*`. Inputs: list[object_id], payload text. Outputs: duplicate pairs (no DB writes in tests). Maturity: baseline.
- **CitationChecker** — Checks outbound refs; `app.agents.citation_checker.*`. Inputs: object_id + payload. Outputs: citation report. Maturity: baseline/experimental in CI.
- **Indexer (agent + services)** — Creates embeddings and writes to VectorIndex; `app.agents.indexer.*`, `app.services.indexer`. Inputs: object_id + payload text. Outputs: index events, `index.object.embedded` outbox. Config: embeddings via component client. Maturity: baseline.

## Retrieval & ranking
- **Hybrid retrieval** — BM25 + embeddings + optional rerank; `app.retrieval.hybrid`, `app.retrieval.hook_adapter`. Inputs: query string; store documents (doc_id/text/source_ref/payload). Outputs: ranked hit dicts. Config: `RERANK_ENABLE`, `RERANK_TOP_K`. Maturity: baseline.
- **Rerankers** — Cross-encoder stack with deterministic local/mock fallbacks; `app.components.rerankers` → `app.retrieval.rerank.*`. Inputs: query + `RerankItem` list. Outputs: ordered `RerankResult` ids. Config: `RERANK_PROVIDER` (`none|mock|ce_local|ce_http`). Maturity: baseline.
- **Embeddings** — Entry via `app.components.embeddings`; defaults to `app.index.embeddings` (LLM-backed) with deterministic profile for tests. Inputs: text sequences. Outputs: embedding vectors. Config: `EMBED_MODEL/OLLAMA_EMBED_MODEL` via `app.llm.embeddings`. Maturity: baseline.

## ASK / reasoning
- **ASK API** — `/api/ask` FastAPI route; `app.api.routes.ask`. Inputs: question payload. Outputs: `AskResponse(answer, sources, latency_ms)` using hybrid retrieval, optional reasoning overlay. Config: `REASONING_ENABLE`, `AskSettings` in runtime settings. Maturity: baseline.
- **Reasoning layer** — Optional modes (claims/review/ranking/ask.answer); `app.reasoning.*`. Inputs: question + context. Outputs: structured reasoning runs. Config: `REASONING_ENABLE`, providers via env/settings. Maturity: experimental/opt-in.

## Eval stack
- **DeepEval ASK** — `tests/eval/test_ask_deepeval.py`, cases in `docs/eval/ask_cases.yaml`; uses FastAPI TestClient against `/api/ask`. Config: `EVAL_LLM_MODE`, `LLM_PROVIDER`. Maturity: experimental/opt-in (`@pytest.mark.eval`).
- **Ragas RAG** — `tests/eval/test_rag_ragas.py`, cases in `docs/eval/rag_cases.yaml`; evaluates answer relevancy/faithfulness. Config: `EVAL_LLM_MODE`, ragas deps. Maturity: experimental/opt-in.

## Infra & observability
- **Outbox/events** — `app.outbox.events`, `app.index.outbox`, event types in `app.events.types`. Inputs: structured event dicts. Outputs: JSONL (`INDEX_OUTBOX_PATH`) + handlers (indexer consumer). Maturity: baseline.
- **Status/metrics** — `app.observability.*`, status service, ingest meta, metrics wiring in `app.api.routes.status` and `app.observability.ingest_meta`. Maturity: baseline.
- **Logging/audit** — Agent audit logs (`app.services.audit`, agents), JSONL traces under `logs/`. Maturity: baseline.
- **Event schema** — Canonical outbox envelope in `app/events/schema.py` (`event`, `trace_id`, `source`, `timestamp`, `payload`, `meta`); contract-tested in `tests/architecture/test_events_outbox_contracts.py`. Emitters should write via outbox helpers to keep envelope fields present.

## Dev-layer helpers & governance
- **Architecture tests** — `tests/architecture/test_import_rules.py` enforce layering (no psycopg in API, agents server-agnostic, components entrypoints for embeddings/rerankers).
- **AI development workflow** — `docs/AI_DEVELOPMENT.md`, `docs/DEV_WORKFLOW.md`, `.codex/AGENTS.md` describe coding and review practices.
- **Frontmatter/data model** — `docs/FRONTMATTER.md`, `docs/DATA_MODEL.md` define Core-6 projections and vault expectations (no changes in this catalog).
- **Eval docs** — `docs/eval.md` captures evaluation approach and optional suites.

## OCR extension points (placeholders)
- **Structured OCR** — Stubbed in `app.components.ocr.get_structured_ocr()`; not wired yet. Maturity: planned.
- **Compressive OCR** — Stubbed in `app.components.ocr.get_compressive_ocr()`; not wired yet. Maturity: planned.
