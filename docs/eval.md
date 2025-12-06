# Eval — LLM quality checks (SoT v4.10)

## Eval stack overview
- Primary LLM eval framework: **DeepEval** (pytest-integrated).
- RAG-focused metrics: **Ragas** (directly, starting with seed RAG evals).
- Optional tools (future/adjacent):
  - **TruLens** for tracing + eval.
  - **promptfoo** for prompt/agent scenario testing and red-teaming (optional CLI tool).

## How eval fits into the test pyramid
- Classic tests: unit/contract/e2e run via `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q -m "not pg"`.
- LLM-eval tests: marked with `@pytest.mark.eval` and **not** included in the fast/default suites.
- Eval tests may call LLMs and can be slower/$$; run them explicitly when validating ASK/retrieval quality.

## How to run eval tests
- Run all eval-marked tests:
  ```bash
  PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q -m "eval"
  ```
- Eval tests rely on a configured LLM backend (e.g., local Ollama via OpenAI-compatible endpoint):
  - `OPENAI_BASE_URL` (default: `http://127.0.0.1:11434/v1`)
  - `OPENAI_API_KEY` (default: `sk-local`)
  - Set `EVAL_LLM_MODE=skip` to skip if no LLM is available.

## Golden cases for ASK
- Seed cases live in `docs/eval/ask_cases.yaml` (3–5 representative ASK queries with expected hints).
- Tests in `tests/eval/test_ask_deepeval.py` load these cases and run DeepEval metrics (e.g., answer relevancy).
- Thresholds are conservative (e.g., 0.5) and should be revisited as retrieval quality improves.

## RAG eval (Ragas, seed suite)
- Seed RAG cases live in `docs/eval/rag_cases.yaml`.
- Tests in `tests/eval/test_rag_ragas.py` run Ragas metrics (answer relevancy, faithfulness/contextual precision when context is available).
- Run just this suite via:
  ```bash
  PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q -m "eval" tests/eval/test_rag_ragas.py
  ```
- Thresholds are conservative (~0.5) and should be tightened as retrieval quality improves; add more cases over time.

## Metrics (initial)
- Answer relevancy / answer-quality style metrics via DeepEval.
- Faithfulness/hallucination metrics can be added once context is surfaced in ASK responses.
- Ragas metrics (precision/recall, context relevance) are seeded via `tests/eval/test_rag_ragas.py`.
