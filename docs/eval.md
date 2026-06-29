State: SoT v5.5 baseline (descriptive, opt-in). Eval suites are optional and may call external/local LLM endpoints.

## v5.5 Baseline Delta (Current Reality)
- Registry watcher is the runtime default; legacy snapshot watcher is dev-only.
- DB outbox (Postgres) is the canonical queue; JSONL audit log is non-canonical and used for lag inspection.
- Watcher auto-run defaults on (`WATCHER_AUTO_EXEC=1`); set `WATCHER_AUTO_EXEC=0` for emit-only mode. LangGraph/Reasoning rollout remains opt-in.
- See `docs/STATUS.md` and `docs/ARCHITECTURE.md` for the current baseline and forward line.

# Eval — LLM Quality Checks (Opt-in)

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
- Eval tests rely on a configured OpenAI-compatible endpoint (typically Ollama):
  - `EVAL_LLM_MODE=run|skip` (default: `skip`)
  - `EVAL_LLM_BASE_URL` (default: `http://127.0.0.1:11434/v1`)
  - `EVAL_LLM_API_KEY` (default: `sk-local`)
  - `EVAL_LLM_MODEL` (default: `llama3.1:8b`)

Implementation note: the eval harness configures `OPENAI_BASE_URL` / `OPENAI_API_KEY` for DeepEval/Ragas compatibility (see `app/eval/llm_client.py`).

## Golden cases for ASK
- Seed cases live in `docs/eval/ask_cases.yaml` plus `docs/eval/ask_cases_bilingual.yaml` (English + Swedish probes).
- Tests in `tests/eval/test_ask_deepeval.py` load these cases and run DeepEval metrics (e.g., answer relevancy).
- Thresholds are conservative (e.g., 0.5) and should be revisited as retrieval quality improves; bilingual coverage reflects the English-first + Swedish-important profile.

## RAG eval (Ragas, seed suite)
- Seed RAG cases live in `docs/eval/rag_cases.yaml`.
- Tests in `tests/eval/test_rag_ragas.py` run Ragas metrics (answer relevancy, faithfulness/contextual precision when context is available).
- Run just this suite via:
  ```bash
  PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q -m "eval" tests/eval/test_rag_ragas.py
  ```
- Thresholds are conservative (~0.5) and should be tightened as retrieval quality improves; add more cases over time.

### Deterministic retrieval eval-case schema

The deterministic retrieval golden seed uses the versioned
`retrieval_eval_case.v1` schema in `docs/eval/retrieval_bilingual_seed.yaml`.
This seed is human-labeled fixture data, not an LLM-judge output; Ragas and
DeepEval remain opt-in layers on top of deterministic cases.

Required top-level shape:

```yaml
schema_version: retrieval_eval_case.v1
cases:
  - id: exact-en-settings-yaml
    language: en  # required: sv|en
    query: "Where is the canonical system settings YAML?"
    relevant_artifact_ids:
      - bg-doc-settings-en
    route_intent: exact_lexical
    provenance_expectation: "source_ref points to vault/_system/settings/system-settings.yaml"
    trust_expectation: own
```

Required case fields:

| Field | Contract |
| --- | --- |
| `id` | Stable case id, unique within the seed. |
| `language` | Required language tag; allowed values are `sv` and `en`. |
| `query` | User-facing retrieval/ASK query in the tagged language. |
| `relevant_artifact_ids` | Non-empty list of resolvable ids in the paired golden corpus. |
| `route_intent` | Descriptive route label. Current deterministic seed labels are `exact_lexical`, `hybrid_semantic`, `recall_into_ask`, and `low_trust_citation`; this is not a final route taxonomy. |
| `provenance_expectation` | Human-readable expectation for source/provenance visibility. |
| `trust_expectation` | Human-readable trust/review-state expectation for retrieved evidence. |

The 11-case bilingual seed covers Swedish and English across the current route
mix: exact/lexical lookup, hybrid semantic retrieval, recall-into-ASK, and
low-trust citation checks. Its paired deterministic ground truth lives under
`data/golden/bilingual_corpus.jsonl` and
`data/golden/bilingual_judgments.json`; the judgment file uses the separate
`retrieval_bilingual_judgments.v1` schema because it is a graded `queries`
object, not the top-level eval-case YAML shape. Corpus trust/review metadata is
also mirrored into each row's `payload` so existing hybrid-store loading paths
preserve low-trust citation expectations. The existing precision@k/ndcg@k
runner continues to read `data/golden/corpus.jsonl` plus
`data/golden/judgments.json`; the bilingual sibling is additive and backward
compatible until the runner/CLI is intentionally extended.

## Metrics (initial)
- Answer relevancy / answer-quality style metrics via DeepEval.
- Faithfulness/hallucination metrics can be added once context is surfaced in ASK responses.
- Ragas metrics (precision/recall, context relevance) are seeded via `tests/eval/test_rag_ragas.py`.

## Scorecards And Targets

Scorecards are currently aspirational rather than enforced runtime truth.

- Current reality:
  - CI/fitness gates live in `docs/TESTING.md` and the fitness track docs.
  - Eval suites under `tests/eval/` remain opt-in.
- Useful scorecard shape to preserve:

```yaml
ingestion_quality:
  frontmatter_core6_complete: true
  chunk_semantics_ok: true
retrieval_answering:
  faithfulness: ">= 0.8"
  provenance: ">= 0.8"
```

- No runtime component consumes scorecard targets today.
- If scorecards become enforceable, add a parser and explicit CI gate rather than treating this document as self-enforcing.
