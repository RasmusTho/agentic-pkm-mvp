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
- Intent-classification slice (KERNEL-13, #2775): per-class precision/recall +
  confusion matrix over the bilingual `classification_case.v1` golden set
  (`docs/eval/classification_golden.yaml`), with `UNKNOWN` scored as safe-fail
  separately and a **blocking** mutation-side confusion hard gate — see the
  deterministic runner below and `tests/eval/test_classification_golden.py`.

## Deterministic retrieval/memory/classification metrics runner (`python -m app.eval.run`)

`python -m app.eval.run` (also wired to `make eval`) is a thin, fully offline
CLI entrypoint over `app.eval.golden.evaluate_bilingual_golden_set` plus the
intent-classification golden set (`app.eval.classification`), reusing
`app.eval.benchmark`'s baseline/regression-comparison model — it is not a new
eval framework. It never calls a live LLM; DeepEval/Ragas suites stay opt-in
behind `@pytest.mark.eval` and are a separate, non-default path.

The same runner also executes the categorical provisional-memory authority gate from
`tests/eval/fixtures/provisional_memory_boundary.yaml` through
`app.eval.provisional_memory_boundary`. Its 16 deterministic Swedish/English cases cover benign
read and cited-proposal use plus direct-write poisoning, prompt injection, false authority claims,
provenance loss, citation omission, and attempted APPLY escalation. Any action-tier admission,
uncited proposal influence, hidden trust/review/provenance, write authority, artifact mutation, or
claim-bearing receipt is a hard `provisional_memory:hard_gate` failure. This section is not
threshold-relative and calls no live model; the scorecard records only normalized outcomes, never
random artifact ids or claim text. The composed production API → Markdown/receipt → guarded
recall/ContextEnvelope path is separately locked by
`tests/agent_memory/test_provisional_memory_end_to_end.py`.

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

### Intent-classification slice (`classification_case.v1`, KERNEL-13)

The same runner scores the governance-critical intent classifier
(`app/components/llm/intent_classifier.py`) over the bilingual golden set
`docs/eval/classification_golden.yaml` (≥40 sv/en cases incl. adversarial
families; authored under RESEARCH-06/#2784, rationale in
`docs/eval/classification_golden_rationale.md`):

- **Per-class precision/recall** for the model-emittable classes
  (`co_authoring`, `governance_bearing`, `exploratory`) plus macro averages,
  and a full **confusion matrix** (expected × predicted, incl. `unknown`).
- **`UNKNOWN` is scored as safe-fail separately, never as a wrong class**: a
  predicted `UNKNOWN` on an answerable case leaves per-class recall
  denominators and is reported via `safe_fail` / `answer_rate`; expected-unknown
  cases are scored via `unknown.safe_fail_rate`.
- **HARD GATE (blocking, not thresholded):** any case with expected
  `exploratory`/`unknown` classified into an action-capable class
  (`co_authoring`, `governance_bearing`) sets `regression: true` and a
  `classification:hard_gate` failure — mutation-side confusion is the CW-2
  silent-misroute class this gate exists to block. Read-side confusion is
  thresholded via the `classification` bucket in `config/eval_thresholds.yaml`.

Deterministic CI mode replays recorded model completions
(`docs/eval/classification_replay.yaml`) through the classifier's injectable
completion seam, so KERNEL-07's constrained-output validation layer runs for
real without a live LLM. The gate runs in the `not pg` PR suite (named CI
step "Intent-classification golden gate" in `.github/workflows/ci.yml`) via
`tests/eval/test_classification_golden.py`; live mode
(`EVAL_LLM_MODE=run pytest -q -m eval tests/eval/test_classification_golden.py`)
is opt-in and never part of the PR gate.

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
classification:   # read-side floors only; the mutation-side hard gate has no threshold
  macro_precision: 0.90
  macro_recall: 0.90
  pass_rate: 0.90
  answer_rate: 0.85
  unknown_safe_fail_rate: 0.85
k: 5
```

`python -m app.eval.run`:
- prints a human-readable summary (aggregate, per-language, per-slice,
  memory-recall, and intent-classification metrics incl. the confusion
  matrix, plus a REGRESSION line per failing bucket/metric);
- writes a machine-readable scorecard to `runtime/eval/scorecard.json`
  (gitignored — a regenerable artifact, not repo truth);
- exits non-zero (fail-loud) if any aggregate, per-language, memory-recall,
  or classification read-side metric falls below its configured threshold
  **or** any mutation-side confusion exists (hard gate, unconditional), and
  exits `0` otherwise.

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
  "provisional_memory_boundary": {
    "schema_version": "provisional_memory_boundary.v1",
    "n_cases": 16,
    "languages": ["en", "sv"],
    "hard_gate_passed": true,
    "failures": [],
    "cases": [{"...": "normalized categorical outcome"}]
  },
  "classification": {
    "mode": "replay",
    "n_cases": 68,
    "per_class": {"co_authoring": {"precision": 1.0, "recall": 1.0, "support": 18, "predicted": 18}, "...": "..."},
    "macro_precision": 1.0,
    "macro_recall": 1.0,
    "pass_rate": 1.0,
    "confusion_matrix": {"co_authoring": {"co_authoring": 18, "...": 0}, "...": "..."},
    "unknown": {"expected": 8, "safe_fail_hits": 8, "read_side_landings": 0, "safe_fail_rate": 1.0},
    "safe_fail": {"count": 0, "answer_rate": 1.0},
    "mutation_side_confusions": [],
    "hard_gate_passed": true
  },
  "queries": [{"...": "per-query row..."}],
  "regression": false,
  "failures": []
}
```

### Scorecard compare (`python -m app.eval.run compare`)

KERNEL-14 (#2776) adds a deterministic baseline-vs-candidate compare seam over
two already-produced `eval_scorecard.v1` files:

```bash
python -m app.eval.run compare \
  --baseline tests/eval/fixtures/scorecard_baseline.json \
  --candidate tests/eval/fixtures/scorecard_candidate.json \
  [--tolerance 0.05] [--output runtime/eval/compare.json]
```

It operates purely on the two scorecard files — no golden-set re-run, no live
LLM, no timestamps/RNG: the same scorecard pair always produces byte-identical
output (`tests/eval/test_scorecard_compare.py`). Implementation:
`app/eval/compare.py`, reusing `app/eval/benchmark.py`'s delta/regression math
(`compute_metric_delta`, same default 5 % relative tolerance as
`BenchmarkSuite.compare`).

What it reports — per-slice deltas (baseline → candidate, delta, delta %):

- **aggregate** precision@k / ndcg@k;
- **per-language** (`by_language`: `en`, `sv`);
- **per-route-intent** (`by_slice`: `exact_lexical`, `hybrid_semantic`,
  `recall_into_ask`, `low_trust_citation`);
- **memory-recall** slice;
- **classification** read-side metrics (macro precision/recall, pass rate,
  answer rate, unknown safe-fail rate), **per-class** precision/recall
  (`classification.per_class`, keyed like `by_language`/`by_slice`), plus the
  KERNEL-13 **confusion slice**: hard-gate state on both sides, candidate
  mutation-side confusions, and the non-zero confusion-matrix cell deltas;
- **provisional-memory authority** hard-gate state on both sides, including
  the candidate's normalized categorical failures and bilingual case count.

Every numeric leaf the compare touches — including confusion-matrix cells and
`failures` entries — is checked by a single spec-driven validation walker on
load; the comparison and the renderer consume only the validated view. The
provisional-memory proof is also structurally reconciled: `n_cases` must match
the exact normalized case list, IDs must be unique, metadata must match case
evidence, and every declared family must have both Swedish and English cases.

Verdict (`regression` / `improved` / `neutral`), printed as `VERDICT: ...` and
mirrored in the `--output` JSON artifact (`eval_scorecard_compare.v1`):

- `regression` (exit code 1) when any of: the candidate trips the KERNEL-13
  mutation-side hard gate or the provisional-memory authority hard gate
  (blocking, never tolerance-relative); the candidate
  scorecard failed its own configured floors (`regression: true` — the floors
  come from `config/eval_thresholds.yaml` at scorecard build time, which is how
  compare consumes them); any compared metric worsened by more than the
  relative tolerance; or any per-language / per-route-intent / per-class slice
  present in the baseline is **missing** in the candidate (a disappeared slice
  is the strongest possible regression — the comparison surface must never
  silently shrink; slices only in the candidate are reported but non-blocking).
- `improved` (exit 0) when no regression and at least one metric improved
  beyond the tolerance.
- `neutral` (exit 0) otherwise.
- Malformed input (including a missing or invalid
  `provisional_memory_boundary`, missing sections or keys, non-numeric or NaN/±inf values
  anywhere in the compared surface, malformed confusion/failure entries, wrong
  `schema_version`) is exit code **2** with an `error:` message naming the
  offending path — never conflated with a regression verdict.

**Compare artifact required for Router/Synthesizer changes.** Any PR that
changes the **Router** (intent classifier — `app/components/llm/intent_classifier.py`
model, or the `classifier.v1` prompt version/contract) or the **Synthesizer**
(ASK answer path — ASK model, or the `ask.answer.v1` prompt version/contract,
i.e. `DEFAULT_ASK_SYSTEM_PROMPT`) must attach a compare artifact to the PR:
run the scorecard on `main` (baseline), re-run it on the candidate branch,
run `python -m app.eval.run compare --baseline ... --candidate ...
--output ...`, and include the output (or the printed summary) in the PR body
or as an attached file. A `regression` verdict blocks the change unless the
regression is explicitly justified and accepted in the PR. This is the
frozen-baseline evidence rail for model/prompt swaps (audit §5.3, CW-7);
auto-attaching via CI/skill wiring is deliberately out of scope here.

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
    `tests/eval/test_benchmark.py`, `tests/eval/test_classification_golden.py`);
    broader CI/fitness gates live in `docs/TESTING.md` and the fitness track docs.
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
