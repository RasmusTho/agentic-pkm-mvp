---
name: Eval Scorecard Compare
description: A baseline-vs-candidate scorecard compare command producing per-slice deltas and a verdict, required as a PR artifact for Router/Synthesizer model or prompt changes
task_id: KERNEL-14
source_anchor: "docs/audits/SYSTEM_REDESIGN_CORRECTNESS_KERNEL_2026-07-02.md :: §5.3"
parent_capability: RUNTIME_CORRECTNESS_KERNEL
prerequisites: [KERNEL-13]
depends_on: [INTENT_CLASSIFICATION_GOLDEN_SET.md]
can_parallelize_with: []
---

# Eval Scorecard Compare

## Purpose

`app/eval/benchmark.py` has an embryonic `BenchmarkSuite.compare()` (approx. line 140,
`BaselineComparison` with a fixed 5% threshold) but no formalized baseline-vs-candidate scorecard
workflow. Model/prompt swaps for the classifier (Router) or ASK (Synthesizer) are unverifiable: there
is no `eval compare` producing a per-slice verdict against a frozen baseline (audit **§5.3**).
Note: the audit's `evaluate_vs_baseline("ce_local", k=10)` phrasing is imprecise — the actual API is
`BenchmarkSuite.compare()`; the deterministic runner is `app/eval/run.py::build_scorecard`
(scorecard `eval_scorecard.v1`, written to `runtime/eval/scorecard.json`).

## What This Task Does

- Add a `compare` seam over two `eval_scorecard.v1` files. `app/eval/run.py::main` (approx. line 136)
  currently takes **no subcommands** — it always builds+writes the scorecard. Read its arg handling
  and add a subcommand seam so `python -m app.eval.run compare --baseline <scorecard.json>
  --candidate <scorecard.json>` works (argparse subparsers, or a dispatch on `argv[0]`; either is
  acceptable — keep it minimal and consistent with the existing `main`).
- Produce **per-slice deltas**: aggregate, per-language (`by_language`), per-route-intent
  (`by_slice`), `memory_recall`, and the classification confusion slice from KERNEL-13. Reuse
  `benchmark.py`'s delta/regression math where sensible rather than re-implementing.
- Emit a **verdict** per thresholds: `regression` / `improved` / `neutral`. Deterministic on a
  fixture scorecard pair (same inputs → same verdict; no live LLM in the compare itself — it operates
  on already-produced scorecards).
- Document in `docs/eval.md` (writeback) that any **Router or Synthesizer model or prompt-version
  change** must attach a compare artifact to the PR.
- Update the prompt-contract mirror docs (`docs/settings/prompts/classifier.v1.md`,
  `docs/settings/prompts/ask.answer.v1.md`) to reference the **pinned output schema version** each
  prompt produces (invariant I-C3: prompt version ↔ schema version bound).

## Concretely

```bash
python -m app.eval.run compare --baseline tests/eval/fixtures/scorecard_baseline.json \
                                --candidate tests/eval/fixtures/scorecard_candidate.json
pytest -q tests/eval/test_scorecard_compare.py
```

## Why This Matters

Ground truth for comparative evaluation in a probabilistic system is the frozen baseline scorecard
(§5.3). Without a formal compare, a classifier or ASK prompt change ships with no evidence it did not
regress the governance-critical decision — exactly the unverifiable-upgrade risk in CW-7.

## Acceptance Criteria

- [ ] `python -m app.eval.run compare --baseline <f> --candidate <f>` produces per-slice deltas
      (aggregate, per_language, per-route-intent, memory_recall, classification confusion).
      Verify: `tests/eval/test_scorecard_compare.py::test_per_slice_deltas`
- [ ] The verdict (regression/improved/neutral) is deterministic on a fixture scorecard pair.
      Verify: `tests/eval/test_scorecard_compare.py::test_verdict_deterministic`
- [ ] `docs/eval.md` states that Router/Synthesizer model or prompt-version changes require a compare
      artifact on the PR.
      Verify: doc writeback at `docs/eval.md :: Scorecard compare`
- [ ] Prompt-contract mirrors reference the pinned output schema version they produce.
      Verify: doc writeback at `docs/settings/prompts/classifier.v1.md :: Output schema version` and `docs/settings/prompts/ask.answer.v1.md :: Output schema version`

## How to Verify (Pre-Merge)

1. `pytest -q tests/eval/test_scorecard_compare.py`.
2. Full `pytest -q -m "not pg"`.
3. `python -m app.eval.run compare ...` on the fixture pair; confirm the printed verdict matches the
   test.
4. `ruff check app tests`.

## Out of Scope

- The classification golden set itself (KERNEL-13).
- Auto-attaching the compare artifact to PRs (documented requirement; the CI/skill wiring is a
  separate concern if pursued).
- Changing threshold values in `config/eval_thresholds.yaml` (compare consumes them).

## Related Docs

- `docs/audits/SYSTEM_REDESIGN_CORRECTNESS_KERNEL_2026-07-02.md :: §5.3`
- `docs/eval.md :: Scorecard shape (eval_scorecard.v1)`, `app/eval/run.py`, `app/eval/benchmark.py`
- `docs/settings/prompts/classifier.v1.md`, `docs/settings/prompts/ask.answer.v1.md` (I-C3 mirrors)

## Related GitHub Issues

One bounded issue. TCD hint: Sonnet / medium effort (CLI seam + delta/verdict over existing scorecard
shape + doc writeback). Escalate only if the `run.py` arg refactor turns out to entangle the existing
default-run behavior.
