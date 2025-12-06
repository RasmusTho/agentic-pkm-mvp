# 6.5 Gardrails (kvalitet & prestanda)

## Kvalitetsaspekter
- `min_rerank_score >= 0.25`
- `grounded_claim_ratio >= 0.7`
- `forbidden_content == 0`
- `max_tokens_out <= N`

## LLM eval guardrails (diagnostic)
- ASK relevance: `tests/eval/test_ask_deepeval.py` runs DeepEval answer-relevancy on seed ASK cases (docs/eval/ask_cases.yaml). Soft target: average relevancy ≥ ~0.5–0.7.
- RAG grounding: `tests/eval/test_rag_ragas.py` runs Ragas metrics (answer relevancy + faithfulness/contextual checks) on seed RAG cases (docs/eval/rag_cases.yaml). Soft target: scores ≥ ~0.5 on seed cases.
- These are diagnostic guardrails today (opt-in via `@pytest.mark.eval`); candidates for CI gating once datasets/thresholds stabilize.

## Prestanda
- Per-nod timeout
- Global LLM-semafor (t.ex. 4)
- Circuit breaker vid upprepade fel
- Cache: embeddings + retrieve-result (kort TTL)
