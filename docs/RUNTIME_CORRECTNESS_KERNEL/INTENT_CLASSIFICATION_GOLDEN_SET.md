---
name: Intent Classification Golden Set
description: A classification_case.v1 bilingual golden set with per-class precision/recall + confusion matrix and a hard CI gate that mutation-side confusion is a blocking regression
task_id: KERNEL-13
source_anchor: "docs/audits/SYSTEM_REDESIGN_CORRECTNESS_KERNEL_2026-07-02.md :: CW-7, §5.2"
parent_capability: RUNTIME_CORRECTNESS_KERNEL
prerequisites: [KERNEL-07]
depends_on: [STRUCTURED_INTENT_OUTPUT_WITH_UNKNOWN.md]
can_parallelize_with: []
---

# Intent Classification Golden Set

## Purpose

The intent classifier (`app/chat/intent_classifier.py::classify`, approx. line 93) is the LLM
decision that gates mutations — misclassification silently converts governance-bearing intent into
body edits (CW-2). It has **zero eval coverage**. The deterministic runner
(`app/eval/run.py::build_scorecard`, `docs/eval/retrieval_bilingual_seed.yaml` shaped as
`retrieval_eval_case.v1`, thresholds in `config/eval_thresholds.yaml`, scorecard `eval_scorecard.v1`)
covers retrieval only (audit **CW-7**, §5.2).

## What This Task Does

- Add a `classification_case.v1` dataset (new file, e.g. `docs/eval/classification_golden.yaml`)
  following the exact shape conventions of the retrieval seed. Per-case fields:
  `id`, `utterance`, `context: {surface, note_state}`, `expected_intent`, `expected_action_type`,
  `acceptable: [...]` (where `UNKNOWN` is scored as safe-fail **separately**, not as a wrong class).
- **≥40 bilingual (sv/en) cases**, including adversarial ones: governance phrased as casual chat
  ("kanske dags att markera den som klar…"), co-authoring phrased as commands, exploratory questions
  that must not route to an action-capable class.
- Extend the runner to compute **per-class precision/recall + a confusion matrix** and write them
  into the scorecard (`build_scorecard` adds a classification slice alongside `by_language` /
  `memory_recall`).
- Add classification thresholds to `config/eval_thresholds.yaml` following the existing bucket shape.
- **HARD GATE:** `P(action-capable class | expected exploratory/UNKNOWN) = 0`. Any mutation-side
  confusion (an exploratory/UNKNOWN case classified into a mutation-capable class such as
  `CO_AUTHORING`) is a **blocking regression**. Read-side confusion is thresholded, not blocking.
- Wire the gate into CI in the **same PR** that lands the dataset (cross-task invariant #6 — a gate
  with an empty dataset is a false-green).

## LLM-mode decision (state explicitly)

The runner stays deterministic in CI. This eval needs the **real classifier path**, so specify two
modes, grounded in how `tests/eval/test_ask_deepeval.py` reads `EVAL_LLM_MODE` via
`app/eval/llm_client.py::configure_eval_openai_env`:
1. **Live mode** (opt-in, `@pytest.mark.eval`, skipped unless `EVAL_LLM_MODE != skip`): runs cases
   against the real classifier + live LLM. Not in the PR gate.
2. **Deterministic CI mode** (default, in `not pg` gate): runs cases against the classifier's
   constrained-output validation layer (KERNEL-07's structured decoding) using a **replay fixture**
   of recorded model outputs per case. The confusion matrix and the hard gate are computed here.

The hard mutation-side gate is asserted in deterministic mode so CI blocks without live LLM access.

## Concretely

```bash
pytest -q tests/eval/test_classification_golden.py           # deterministic CI mode
EVAL_LLM_MODE=live pytest -q -m eval tests/eval/test_classification_golden.py   # opt-in live
```

## Why This Matters

Model/prompt upgrades to the governance-critical classifier are unverifiable today (CW-7); a single
regression can silently convert a "what did I write about X?" into a body edit. This is the single
highest-leverage eval gap in the system.

## Acceptance Criteria

- [ ] `classification_case.v1` dataset exists with ≥40 bilingual cases incl. adversarial ones;
      `UNKNOWN` scored as safe-fail separately.
      Verify: `tests/eval/test_classification_golden.py::test_dataset_shape_and_size`
- [ ] Runner emits per-class precision/recall + confusion matrix into the scorecard.
      Verify: `tests/eval/test_classification_golden.py::test_scorecard_has_confusion_matrix`
- [ ] Hard gate: any expected exploratory/UNKNOWN case classified into a mutation-capable class fails
      the gate, exercised through the real classifier path (deterministic replay).
      Verify: `tests/eval/test_classification_golden.py::test_mutation_side_confusion_is_blocking` — drives `app.chat.intent_classifier.classify` via the replay fixture, asserting a mutation-side confusion trips a non-zero exit / regression flag.
- [ ] Gate wired into CI in the same PR as the dataset.
      Verify: CI workflow diff (the `not pg` classification gate step) in this PR

## How to Verify (Pre-Merge)

1. `pytest -q tests/eval/test_classification_golden.py`.
2. Full `pytest -q -m "not pg"`.
3. `ruff check app tests`; confirm `docs/eval.md` metrics section references the new slice.

## Out of Scope

- Building the structured-output/`UNKNOWN` mechanism (KERNEL-07 delivers it; this task measures it).
- Scorecard baseline-vs-candidate comparison (KERNEL-14).
- Growing the retrieval seed (separate; capture loop is KERNEL-15).

## Related Docs

- `docs/audits/SYSTEM_REDESIGN_CORRECTNESS_KERNEL_2026-07-02.md :: CW-7, §5.2`
- `docs/eval.md`, `docs/eval/retrieval_bilingual_seed.yaml`, `config/eval_thresholds.yaml`
- `app/chat/intent_classifier.py`, `app/eval/run.py`, `app/eval/llm_client.py`

## Related GitHub Issues

One bounded issue (build + measure pairs with KERNEL-07). TCD hint: Sonnet / medium effort (dataset
authoring + runner extension following an established pattern + one hard-gate enforcement test).
Escalate only if the deterministic replay layer cannot faithfully exercise the classifier path.
