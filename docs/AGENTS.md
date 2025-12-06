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
- Instruktioner
- Kontext (citerade utdrag med käll-ID)
- Fråga
- Krav (format, språk, källhänvisning)

## Svarskontrakt
- `Sammanfattning`
- `Källor` (lista: doc_id + ev. tidsstämplar)
