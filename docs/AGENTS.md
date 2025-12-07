State: SoT v4.10 Reality-MVP (current core).
# 6.0 Agentloop (deterministisk)

## ASK AgentState (Reality-MVP)
- `trace_id`: propagated through ASK runs.
- `query`: user question.
- `hits`: retrieval results `{object_id, score, origin, zone, trust, title, path, snippet, payload}`.
- `answer`: composed answer text (LLM-backed when enabled; otherwise top-hit snippet).
- `reasoning`: optional reasoning trace.

Flow: `query → retrieve (hybrid search) → rerank (ask_score + reranker) → answer (LLM optional)`. The canonical implementation lives in `app/agents/ask/graph.py` and is invoked by `/api/ask`.

## Graf
`retrieve -> draft -> self-check -> final` (max 2 iterationer)

## Promptstruktur
- Instructions
- Context (quoted excerpts with source IDs)
- Question
- Requirements (format, language, citation requirements)

## Svarskontrakt
- `Summary`
- `Sources` (list: doc_id + timestamps when relevant)

## Agent Matrix (Reality-MVP)

| Agent | Role | Primary Human Flow | State (active/parked) |
| --- | --- | --- | --- |
| Normalizer | Normalize/parse vault files into canonical objects | Capture & Ingest | Active |
| Classifier | Propose types/facets and intent labels | Capture & Ingest / Panel Interaction | Active |
| Chunker | Split content for indexing | Capture & Ingest | Active |
| Deduper | Prevent duplicate objects/embeddings | Capture & Ingest | Active |
| CitationChecker | Validate citations for ASK answers | ASK | Active |
| Indexer | Write embeddings to VectorIndex | Capture & Ingest / ASK | Active |
| ASK Agent | Retrieve, rerank, and draft answers | ASK | Active |
| PanelAgent | Translate AI panels into intents/events | Panel Interaction | Active |
| Promotion Agent | Apply promotion/evergreen actions | Review & Promotion | Active |
| Reviewer | Human-aligned review of objects/promotions | Review & Promotion | Active |
| SetEvaluator | Score/rank candidates for promotion/sets | Review & Promotion / ASK (ranking) | Active |
| MergeResolverAgent | Resolve conflicts/merges across sources | Capture & Ingest | Parked (future) |
| NoteHygieneAgent | Suggest cleanups and consistency fixes | Capture & Ingest / Panel Interaction | Parked (future) |
