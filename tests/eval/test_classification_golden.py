"""Intent-classification golden-set gate (KERNEL-13, #2775).

Verifies the `classification_case.v1` bilingual golden set
(`docs/eval/classification_golden.yaml`, authored under RESEARCH-06/#2784)
and the deterministic scoring path that gates the governance-critical
classifier (`app/chat/intent_classifier.py`):

- dataset shape/size and the invariants that protect the hard gate;
- scorecard slice with per-class precision/recall + confusion matrix;
- the HARD GATE: mutation-side confusion (an expected exploratory/unknown
  case classified into an action-capable class) is a blocking regression,
  exercised through the real classifier path via the replay fixture;
- `UNKNOWN` scored as safe-fail separately, never as a wrong class.

Deterministic CI mode runs in the `not pg` gate. Live mode (real provider)
is opt-in behind `@pytest.mark.eval` + `EVAL_LLM_MODE=run`, mirroring
`tests/eval/test_ask_deepeval.py`.

Spec: docs/RUNTIME_CORRECTNESS_KERNEL/INTENT_CLASSIFICATION_GOLDEN_SET.md
"""

from __future__ import annotations

import os

import pytest

from app.chat.intent_classifier import IntentClass, IntentClassifierCognition
from app.eval import run as eval_run
from app.eval.classification import (
    ACTION_CAPABLE_CLASSES,
    CLASSIFICATION_GOLDEN_PATH,
    CLASSIFICATION_REPLAY_PATH,
    EMITTABLE_CLASSES,
    HARD_GATE_EXPECTED_CLASSES,
    classify_cases,
    evaluate_classification,
    evaluate_classification_golden_set,
    load_classification_cases,
    load_replay_completions,
)

pytestmark = pytest.mark.not_pg

#: Adversarial family prefixes the dataset must keep covering (see the
#: dataset header): governance phrased as casual chat, body edits phrased as
#: commands, exploratory questions carrying mutation vocabulary (hard gate),
#: and genuinely unresolvable utterances (hard gate).
ADVERSARIAL_FAMILIES = {"govchat", "cmdstyle", "readvocab", "vague"}


# ---------------------------------------------------------------------------
# AC1 — dataset shape and size (Verify: test_dataset_shape_and_size)
# ---------------------------------------------------------------------------


def test_dataset_shape_and_size() -> None:
    cases = load_classification_cases(CLASSIFICATION_GOLDEN_PATH)

    # >= 40 bilingual cases, both languages materially represented.
    assert len(cases) >= 40
    languages = {case.language for case in cases}
    assert languages == {"en", "sv"}
    for language in ("en", "sv"):
        assert sum(1 for c in cases if c.language == language) >= 15

    # Unique ids; adversarial families present.
    ids = [case.id for case in cases]
    assert len(ids) == len(set(ids))
    families = {case.id.split("-", 1)[0] for case in cases}
    assert ADVERSARIAL_FAMILIES <= families

    # Every intent class appears, including expected-unknown (safe-fail) cases.
    expected_intents = {case.expected_intent for case in cases}
    assert expected_intents == set(EMITTABLE_CLASSES) | {IntentClass.UNKNOWN.value}

    for case in cases:
        # action_type is set iff governance-bearing.
        if case.expected_intent == IntentClass.GOVERNANCE_BEARING.value:
            assert case.expected_action_type, case.id
        else:
            assert case.expected_action_type is None, case.id
        # UNKNOWN is scored as safe-fail separately — never an acceptable class.
        assert IntentClass.UNKNOWN.value not in case.acceptable, case.id
        # Dataset invariant protecting the hard gate: expected
        # exploratory/unknown cases never allow an action-capable class.
        if case.expected_intent in HARD_GATE_EXPECTED_CLASSES:
            assert not (set(case.acceptable) & ACTION_CAPABLE_CLASSES), case.id

    # Cross-task invariant #6: a gate over a partially covered dataset is a
    # false-green — the replay fixture must cover every case.
    completions = load_replay_completions(CLASSIFICATION_REPLAY_PATH)
    missing = {case.id for case in cases} - set(completions)
    assert not missing, f"replay fixture missing completions for: {sorted(missing)}"


# ---------------------------------------------------------------------------
# AC2 — scorecard slice: per-class precision/recall + confusion matrix
# (Verify: test_scorecard_has_confusion_matrix)
# ---------------------------------------------------------------------------


def test_scorecard_has_confusion_matrix() -> None:
    scorecard = eval_run.build_scorecard()

    classification = scorecard["classification"]
    assert classification["mode"] == "replay"

    # Per-class precision/recall for every model-emittable class.
    per_class = classification["per_class"]
    assert set(per_class) == set(EMITTABLE_CLASSES)
    for metrics in per_class.values():
        assert 0.0 <= metrics["precision"] <= 1.0
        assert 0.0 <= metrics["recall"] <= 1.0
        assert metrics["support"] > 0
    assert 0.0 <= classification["macro_precision"] <= 1.0
    assert 0.0 <= classification["macro_recall"] <= 1.0

    # Full confusion matrix: expected classes (incl. unknown) x predictions.
    matrix = classification["confusion_matrix"]
    all_classes = set(EMITTABLE_CLASSES) | {IntentClass.UNKNOWN.value}
    assert set(matrix) == all_classes
    for row in matrix.values():
        assert set(row) == all_classes
    total = sum(sum(row.values()) for row in matrix.values())
    assert total == classification["n_cases"] == len(load_classification_cases())

    # UNKNOWN is a separate safe-fail slice, not a scored class.
    assert "unknown" not in per_class
    unknown = classification["unknown"]
    assert unknown["expected"] > 0
    assert 0.0 <= unknown["safe_fail_rate"] <= 1.0

    # Read-side thresholds are configured (config/eval_thresholds.yaml).
    thresholds = scorecard["thresholds"]["classification"]
    assert {"macro_precision", "macro_recall", "pass_rate"} <= set(thresholds)

    # The baseline replay clears its own gate — otherwise the wired CI gate
    # would land red, which is a dataset/replay authoring error.
    assert classification["hard_gate_passed"] is True
    assert not [f for f in scorecard["failures"] if f["scope"].startswith("classification")]


# ---------------------------------------------------------------------------
# AC3 — hard gate: mutation-side confusion is blocking, through the real
# classifier path (Verify: test_mutation_side_confusion_is_blocking)
# ---------------------------------------------------------------------------


def test_mutation_side_confusion_is_blocking(monkeypatch, tmp_path) -> None:
    completions = dict(load_replay_completions(CLASSIFICATION_REPLAY_PATH))
    cases = load_classification_cases()
    by_id = {case.id: case for case in cases}

    # Tamper the replay for one expected-exploratory and one expected-unknown
    # case so the recorded model output claims an action-capable class.
    exploratory_id = "readvocab-en-which-archived"
    unknown_id = "vague-en-the-thing-we-discussed"
    assert by_id[exploratory_id].expected_intent == IntentClass.EXPLORATORY.value
    assert by_id[unknown_id].expected_intent == IntentClass.UNKNOWN.value
    completions[exploratory_id] = '{"intent_class": "co_authoring", "action_type": null}'
    completions[unknown_id] = (
        '{"intent_class": "governance_bearing", "action_type": "note_lifecycle"}'
    )

    # The confusion travels through the REAL classifier path: the tampered
    # completion is schema-valid, so IntentClassifierCognition.classify
    # (KERNEL-07 validation layer included) yields the action-capable class.
    result = IntentClassifierCognition(
        completion=lambda **_: completions[exploratory_id]
    ).classify(intent=by_id[exploratory_id].utterance)
    assert result.intent_class is IntentClass.CO_AUTHORING
    assert result.classified is True

    scorecard = eval_run.build_scorecard(classification_completions=completions)
    classification = scorecard["classification"]

    confused_ids = {c["case_id"] for c in classification["mutation_side_confusions"]}
    assert confused_ids == {exploratory_id, unknown_id}
    assert classification["hard_gate_passed"] is False

    # Blocking regression: the scorecard flags it and the runner exits
    # non-zero (app.eval.run.main returns 1 iff regression).
    assert scorecard["regression"] is True
    gate_failures = [f for f in scorecard["failures"] if f["scope"] == "classification:hard_gate"]
    assert len(gate_failures) == 2
    assert {f["metric"] for f in gate_failures} == {
        f"mutation_side_confusion:{exploratory_id}->co_authoring",
        f"mutation_side_confusion:{unknown_id}->governance_bearing",
    }
    # Exercise main()'s exit-code propagation for real (review finding on
    # #2851: re-deriving `1 if regression else 0` locally was tautological).
    monkeypatch.setattr(eval_run, "build_scorecard", lambda: scorecard)
    monkeypatch.setattr(eval_run, "SCORECARD_PATH", tmp_path / "scorecard.json")
    assert eval_run.main([]) == 1

    # The human summary names the violation loudly.
    summary = eval_run.render_summary(scorecard)
    assert "HARD GATE VIOLATIONS" in summary
    assert exploratory_id in summary


def test_unknown_is_safe_fail_not_wrong_class() -> None:
    """A predicted UNKNOWN on an answerable case is scored as safe-fail:
    excluded from per-class recall denominators and never counted as a
    misclassification into another class — and it is NOT a hard-gate hit."""
    completions = dict(load_replay_completions(CLASSIFICATION_REPLAY_PATH))
    cases = load_classification_cases()

    target_id = "coauthor-en-tighten-intro"
    completions[target_id] = "sorry, I could not decide"  # schema-invalid -> UNKNOWN

    predictions = classify_cases(cases, completions)
    assert predictions[target_id] == IntentClass.UNKNOWN.value

    result = evaluate_classification(cases, predictions)
    baseline = evaluate_classification(cases, classify_cases(cases, load_replay_completions()))

    # Counted once as an answerable safe-fail...
    assert result["safe_fail"]["count"] == baseline["safe_fail"]["count"] + 1
    # ...visible in the confusion matrix truth row...
    assert (
        result["confusion_matrix"][IntentClass.CO_AUTHORING.value][IntentClass.UNKNOWN.value]
        == baseline["confusion_matrix"][IntentClass.CO_AUTHORING.value][IntentClass.UNKNOWN.value]
        + 1
    )
    # ...but never as a wrong class: no other class gains a false positive,
    # and co_authoring recall is unaffected (safe-fails leave the denominator).
    for cls in EMITTABLE_CLASSES:
        assert result["per_class"][cls]["precision"] == baseline["per_class"][cls]["precision"]
        assert result["per_class"][cls]["recall"] == baseline["per_class"][cls]["recall"]
    # Safe-fail is not mutation-side confusion — the hard gate stays green.
    assert result["hard_gate_passed"] is True


# ---------------------------------------------------------------------------
# Live mode (opt-in, never in the PR gate) — real classifier + live LLM.
# ---------------------------------------------------------------------------


@pytest.mark.eval
@pytest.mark.skipif(
    os.getenv("EVAL_LLM_MODE", "skip").strip().lower() != "run",
    reason="live classification eval is opt-in (EVAL_LLM_MODE=run)",
)
def test_live_classification_golden_set() -> None:
    from app.eval.llm_client import configure_eval_openai_env

    configure_eval_openai_env()
    result = evaluate_classification_golden_set(live=True)

    assert result["mode"] == "live"
    assert result["n_cases"] >= 40
    # The hard gate holds against the live model too: no expected
    # exploratory/unknown case may reach an action-capable class.
    assert result["mutation_side_confusions"] == []
