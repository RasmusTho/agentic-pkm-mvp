State: SoT v5.5 Reality-MVP baseline locked (watcher/panel safety + concurrency guardrails).
# Guardrails (Quality & Safety)

## Quality guardrails (runtime)
- **Determinism first**: watcher/panel flows must be idempotent and safe by default.
- **Write safety**: `DEFAULT_WRITE_GUARD` blocks stale writes and prevents silent file corruption.
- **Action safety**: watcher auto-run only when explicitly allowed in frontmatter (`ai_panel_auto_run: watcher`) and when actions are allowlisted via `vault/@Settings/watchers.md`.
- **Dedup + idempotency**: DedupTaskQueue prevents duplicate watcher auto-exec; EventDedupStore skips duplicate `promote.intent.created`.

## LLM eval guardrails (diagnostic)
- ASK relevance: `tests/eval/test_ask_deepeval.py` runs DeepEval answer-relevancy on seed ASK cases (docs/eval/ask_cases.yaml). Soft target: average relevancy ≥ ~0.5–0.7.
- RAG grounding: `tests/eval/test_rag_ragas.py` runs Ragas metrics (answer relevancy + faithfulness/contextual checks) on seed RAG cases (docs/eval/rag_cases.yaml). Soft target: scores ≥ ~0.5 on seed cases.
- These are diagnostic guardrails today (opt-in via `@pytest.mark.eval`); candidates for CI gating once datasets/thresholds stabilize.

## Performance & safety
- Per-node timeout for LLM and ASR calls.
- Global LLM semaphore to avoid overload.
- Circuit breaker on repeated failures.
- Cache: embeddings + retrieval results (short TTL) where safe.
