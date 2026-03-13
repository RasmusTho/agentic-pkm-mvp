State: Dev-layer guidelines (historical). This file may lag the current architecture; prefer `docs/DEV_WORKFLOW.md` and the repo tests/contracts.

## v5.5 Baseline Delta (Current Reality)
- Registry watcher is the runtime default; legacy snapshot watcher is dev-only.
- DB outbox (Postgres) is the canonical queue; JSONL audit log is non-canonical and used for lag inspection.
- Watcher auto-run remains off unless allowlisted; LangGraph/Reasoning rollout is opt-in.
- See `docs/STATUS.md` and `docs/ARCHITECTURE.md` for the current baseline and forward line.

# Codex Guidelines (agentic-pkm-mvp)

## Grundprinciper
- Arkitektur: LangGraph med PER-loop (plan → act → reflect → emit) för alla agenter.
- Eventkoreografi: `subject.verb.state` (t.ex. `ingest.normalize.done`).
- Sanning: AMG/SetDB i Postgres (pgvector). Core-6 frontmatter skrivs bara av Normalizer; Projector uppdaterar endast whitelist (maturity, trust, aliases, related, parent, canonical, sets, scope, relevance_score).
- Idempotens: alla writes är UPSERT; samma input ger samma output (t.ex. Normalizer-ID).
- TDD: följ testernas kontrakt; uppdatera endast kod som krävs för gröna tester.

## Repo-konventioner
- Kataloger:
  - `app/agents/<agent>/{agent.py,graph.py}`
  - `app/search/{bm25_lite.py, vector_index.py, embeddings.py}`
  - `app/alembic/*` (migrationer)
  - `tests/agents/*`, `tests/e2e/*`
- DB: läs `DATABASE_URL`. Använd psycopg och UPSERT. Kolumner: `objects`, `chunks`, `embeddings`, `relations`, `sets`, `membership`, `decisions`, `audit`.
- Loggning: jsonl-liknande audit via `audit_log(object_id, agent, action, trace_id, details)`.

## LLM & Reasoning
- Lokal default: Ollama (`LLM_PROVIDER=ollama`, `LLM_MODEL=llama3.1:8b`, `LLM_REASONING_MODEL=deepseek-r1:8b`).
- Tillåt fallback till molnmodeller via env-var om uttryckligen efterfrågat.

## Agents (PER-mönster)
- `graph.py` innehåller LangGraph-noden/kanterna för plan/act/reflect/emit.
- `agent.py` kapslar ren funktionslogik (körbar utan graph).
- `emit` returnerar standardiserat `{ "event": "...", "object_id": "...", ... }` och skriver audit.

## Naming & events
- Normalizer: `ingest.normalize.done`
- Classifier: `curation.classify.done`
- Chunker: `ingest.chunk.done`
- Deduper: `curation.dedupe.done`
- CitationChecker: `curation.citation.checked`
- Indexer: `ingest.index.done` (+ `ingest.index.ready` för WS)
- Reviewer: `curation.review.passed|blocked|feedback`
- SetEvaluator: `curation.sets.updated`
- Projector: `curation.projector.written`

## BM25/Vector
- BM25: in-memory för test (deterministisk). Indexera rubriker och brödtext.
- Vector: pgvector via `PgVectorIndex`; embeddings via deterministisk hashing i testläge.

## Terminalpolicy (viktig)
- Inga `applypatch`.
- Inga shell-kommentarer i instruktioner.
- När filer ska ändras: ge hela filinnehållet (cat > … <<'EOF').

## TDD-ordning resten av MVP
1) Reviewer (gates enligt `data/context/maturity.yaml`)
2) SetEvaluator (membership, scope)
3) Projector (whitelist → frontmatter)
4) E2E smoke (hela pipen)
