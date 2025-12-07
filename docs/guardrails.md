State: SoT v4.10 Reality-MVP (current core).
# Guardrails — Reality-MVP

## Runtime answer guardrails (current)
- Canonical implementation: `app/quality/guardrails.py` (`enforce_quality`).
- Checks applied by the QA agent pipeline (planner/CLI flows): `min_sources=1`, `max_tokens=800` (word-based), and a forbidden-content regex (`api key|password|secret`, case-insensitive). Results are returned alongside QA answers for clients to consume/log.
- Scope: `/api/ask` uses the ASK graph (retrieve → optional rerank → answer with optional LLM) and does **not** run `enforce_quality` today; it relies on retrieval grounding plus source visibility instead.
- CircuitBreaker and timeout helpers exist in `app/quality/guardrails.py` but are not wired into QA/ASK responses yet.

## Eval guardrails (diagnostic)
- ASK relevance: `tests/eval/test_ask_deepeval.py` runs DeepEval answer relevancy on seed ASK cases (`docs/eval/ask_cases*.yaml`). Soft target today: average ≥ ~0.5–0.7.
- RAG grounding: `tests/eval/test_rag_ragas.py` runs Ragas metrics (answer relevancy + faithfulness/context precision) on `docs/eval/rag_cases.yaml`. Soft target: scores ≥ ~0.5 on the seed cases.
- These suites are opt-in via `@pytest.mark.eval` and **not** part of the default CI; they are diagnostics until datasets/thresholds stabilize.

## Fitness gates (CI, enforced)
- `python -m app.fitness.report` emits QAS-003 (hybrid search latency) and QAS-010 (outbox→index latency) summary lines. `ci-smoke` asserts `GATES.ok=true`, making these thresholds gating in the PR smoke workflow (memory stores, mock LLM, rerank off by default).

## Planned/observed controls (not enforced)
- No active `min_rerank_score` or grounded-claim ratio guardrail is enforced today; rerank is optional and gated by env/settings.
- LLM concurrency/semaphore and breaker wiring are planned; today only the helper is present.
