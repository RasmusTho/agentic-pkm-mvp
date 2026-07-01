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
      - bg-doc-settings-sv
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
| `relevant_artifact_ids` | Non-empty list of resolvable ids in the paired golden corpus. For paired graded judgments, this must match every doc id with positive relevance for the same case id. |
| `route_intent` | Descriptive route label. Current deterministic seed labels are `exact_lexical`, `hybrid_semantic`, `recall_into_ask`, and `low_trust_citation`; this is not a final route taxonomy. |
| `provenance_expectation` | Human-readable expectation for source/provenance visibility. |
| `trust_expectation` | Human-readable trust/review-state expectation for retrieved evidence. |

The 11-case bilingual seed covers Swedish and English across the current route
mix: exact/lexical lookup, hybrid semantic retrieval, recall-into-ASK, and
low-trust citation checks. Its paired deterministic ground truth lives under
`data/golden/bilingual_corpus.jsonl` and
`data/golden/bilingual_judgments.json`; the judgment file uses the separate
`retrieval_bilingual_judgments.v1` schema because it is a graded `queries`
object, not the top-level eval-case YAML shape. Corpus trust metadata and
canonical `review_state` values are also mirrored into each row's `payload` so
existing hybrid-store loading paths preserve low-trust citation expectations
without writing legacy review-state values such as `processed` or `promoted`;
workflow, promotion, or maturity markers belong in separate metadata fields.
`app.eval.golden.evaluate_golden_set` continues to read `data/golden/corpus.jsonl` plus
`data/golden/judgments.json` for the original monolingual seed.
`app.eval.golden.evaluate_bilingual_golden_set` reads the bilingual seed
(`data/golden/bilingual_corpus.jsonl` + `data/golden/bilingual_judgments.json`)
and is the one wired into the `python -m app.eval.run` CLI entrypoint below
(#2320); the two seeds and runners are independent and both remain in the repo.

## Metrics (initial)
- Answer relevancy / answer-quality style metrics via DeepEval.
- Faithfulness/hallucination metrics can be added once context is surfaced in ASK responses.
- Ragas metrics (precision/recall, context relevance) are seeded via `tests/eval/test_rag_ragas.py`.

## Deterministic retrieval/memory metrics runner (`python -m app.eval.run`)

`python -m app.eval.run` (also wired to `make eval`) is a thin, fully offline
CLI entrypoint over `app.eval.golden.evaluate_bilingual_golden_set`, reusing
`app.eval.benchmark`'s baseline/regression-comparison model — it is not a new
eval framework. It never calls a live LLM; DeepEval/Ragas suites stay opt-in
behind `@pytest.mark.eval` and are a separate, non-default path.

What it reports, all computed over the W2-EVAL-01 bilingual seed
(`docs/eval/retrieval_bilingual_seed.yaml` +
`data/golden/bilingual_corpus.jsonl` / `data/golden/bilingual_judgments.json`):

- **Aggregate** precision@k / ndcg@k across all seed cases.
- **Per-language** precision@k / ndcg@k (`en`, `sv`).
- **Per-slice** precision@k / ndcg@k, sliced by `route_intent`
  (`exact_lexical`, `hybrid_semantic`, `recall_into_ask`, `low_trust_citation`).
- **Memory-recall slice**: the combined `recall_into_ask` +
  `low_trust_citation` route_intents, scored against the same deterministic
  ground truth — this is the recall-into-ASK / low-trust-citation slice
  required by W2.

`k` (top-k cutoff) defaults to the value in `config/eval_thresholds.yaml`.

### Thresholds and the regression gate

Thresholds live in `config/eval_thresholds.yaml` (schema
`eval_thresholds.v1`), not hardcoded in the runner. They are conservative
floors for the current baseline retrieval quality, not aspirational targets:

```yaml
schema_version: eval_thresholds.v1
aggregate:
  precision_at_k: 0.15
  ndcg_at_k: 0.60
per_language:
  precision_at_k: 0.10
  ndcg_at_k: 0.55
memory_recall:
  precision_at_k: 0.10
  ndcg_at_k: 0.60
k: 5
```

`python -m app.eval.run`:
- prints a human-readable summary (aggregate, per-language, per-slice, and
  memory-recall metrics, plus a REGRESSION line per failing bucket/metric);
- writes a machine-readable scorecard to `runtime/eval/scorecard.json`
  (gitignored — a regenerable artifact, not repo truth);
- exits non-zero (fail-loud) if any aggregate, per-language, or memory-recall
  metric falls below its configured threshold, and exits `0` otherwise.

Raise a threshold only after intentionally improving retrieval and
re-measuring the golden set — never to make a regression pass.

### Scorecard shape (`eval_scorecard.v1`)

```json
{
  "schema_version": "eval_scorecard.v1",
  "k": 5,
  "thresholds": { "...": "..." },
  "aggregate": {"precision@k": 0.22, "ndcg@k": 0.93, "count": 11},
  "by_language": {"en": {"...": "..."}, "sv": {"...": "..."}},
  "by_slice": {"exact_lexical": {"...": "..."}, "...": "..."},
  "memory_recall": {"precision@k": 0.20, "ndcg@k": 1.0, "count": 5},
  "memory_recall_route_intents": ["low_trust_citation", "recall_into_ask"],
  "queries": [{"...": "per-query row..."}],
  "regression": false,
  "failures": []
}
```

### Makefile target

`make eval` runs `python -m app.eval.run` (this was previously stale, pointing
at a non-existent module — #2320 repaired it now that the module exists).

## Scorecards And Targets

The `eval_scorecard.v1` shape above is now enforced runtime truth for the
deterministic retrieval/memory gate (`python -m app.eval.run` / `make eval`);
its thresholds live in `config/eval_thresholds.yaml`.

For the separate LLM-judge (DeepEval/Ragas) suites, scorecards remain
aspirational rather than enforced:

- Current reality:
  - CI/fitness gates for the deterministic runner live in the tests listed
    above (`tests/eval/test_eval_run_route.py`, `tests/eval/test_golden_metrics.py`,
    `tests/eval/test_benchmark.py`); broader CI/fitness gates live in
    `docs/TESTING.md` and the fitness track docs.
  - LLM-judge eval suites under `tests/eval/` remain opt-in.
- Useful scorecard shape to preserve for the LLM-judge suites:

```yaml
ingestion_quality:
  frontmatter_core6_complete: true
  chunk_semantics_ok: true
retrieval_answering:
  faithfulness: ">= 0.8"
  provenance: ">= 0.8"
```

- No runtime component consumes the LLM-judge scorecard targets today.
- If those scorecards become enforceable, add a parser and explicit CI gate
  following the same pattern as the deterministic runner above.
