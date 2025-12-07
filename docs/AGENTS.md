State: SoT v4.10 Reality-MVP (current core).
# Agents — Reality-MVP

## ASK AgentState (current behavior)
- `trace_id`: propagated through ASK runs.
- `query`: user question.
- `hits`: retrieval results `{object_id, score, origin, zone, trust, title, path, snippet, payload}`.
- `answer`: composed answer text; defaults to the top-hit snippet, swaps to an LLM draft when `REASONING_ENABLE=1`.
- `reasoning`: optional reasoning trace (empty when reasoning is disabled).

Execution path (single pass): `query → retrieve (hybrid search) → rerank (ask_score + reranker when configured) → answer`. The canonical graph lives in `app/agents/ask/graph.py` and is invoked by `/api/ask`. There is no self-check loop in the current Reality-MVP path.

Prompting/answering: context is built from the top reranked hits (bounded by `max_context_docs` in ask settings). With reasoning disabled the answer is the top snippet; with reasoning enabled an LLM answer is attempted with the same context.

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
| Promotion Agent | Apply promotion/evergreen actions | Review & Promotion | Active (flag/entrypoint wiring varies) |
| Reviewer | Human-aligned review of objects/promotions | Review & Promotion | Active |
| SetEvaluator | Score/rank candidates for promotion/sets | Review & Promotion / ASK (ranking) | Active |
| MergeResolverAgent | Resolve conflicts/merges across sources | Capture & Ingest | Parked (future) |
| NoteHygieneAgent | Suggest cleanups and consistency fixes | Capture & Ingest / Panel Interaction | Parked (future) |
