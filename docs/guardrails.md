# 6.5 Gardrails (kvalitet & prestanda)

## Kvalitetsaspekter
- `min_rerank_score >= 0.25`
- `grounded_claim_ratio >= 0.7`
- `forbidden_content == 0`
- `max_tokens_out <= N`

## Prestanda
- Per-nod timeout
- Global LLM-semafor (t.ex. 4)
- Circuit breaker vid upprepade fel
- Cache: embeddings + retrieve-result (kort TTL)
