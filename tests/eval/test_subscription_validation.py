import copy
from collections import Counter
from difflib import SequenceMatcher
import hashlib
import json
from pathlib import Path

import pytest
import yaml

from app.eval.classification import load_classification_cases
from app.eval.subscription_classification import CORPORA, HOLDOUT_PATH, MODELS
from app.eval.subscription_validation import run_validation, summarize_validation, validation_plan
from tests.eval.test_subscription_classification import FakeExecutor


class MixedExecutor(FakeExecutor):
    def __init__(self, *, mutate=None, invalid=None):
        cases = [c for path in CORPORA.values() for c in load_classification_cases(path)]
        super().__init__(cases=cases, invalid=invalid)
        self.mutate = mutate

    def execute(self, **kwargs):
        result = super().execute(**kwargs)
        if self.mutate and len(self.calls) == 4:
            data = json.loads(result.response_text)
            items = json.loads(kwargs["user_prompt"])
            for answer, item in zip(data["answers"], items):
                if item["intent"] == self.cases[68 + 32].utterance:
                    answer["decision"] = self.mutate
            result.response_text = json.dumps(data)
        return result


def test_holdout_integrity_and_independence():
    cases = load_classification_cases(HOLDOUT_PATH)
    source = load_classification_cases()
    assert len(cases) == 64 and len({c.id for c in cases}) == 64
    assert Counter((c.expected_intent, c.language) for c in cases) == {
        (cls, lang): 8 for cls in ("co_authoring", "governance_bearing", "exploratory", "unknown")
        for lang in ("sv", "en")}
    assert Counter((c.expected_action_type, c.language) for c in cases
                   if c.expected_intent == "governance_bearing") == {
        (action, lang): 2 for action in ("maturity_transition", "frontmatter_update", "note_lifecycle", "cross_note")
        for lang in ("sv", "en")}
    assert all(c.acceptable == () for c in cases)
    normalized = [" ".join(c.utterance.casefold().split()) for c in cases]
    assert len(set(normalized)) == 64
    assert not (set(normalized) & {" ".join(c.utterance.casefold().split()) for c in source})
    assert max(SequenceMatcher(None, c.utterance.casefold(), s.utterance.casefold()).ratio()
               for c in cases for s in source) < 0.70
    # Text disjointness is a mechanical screen, not proof of semantic independence.
    manifest = yaml.safe_load(HOLDOUT_PATH.read_text())
    assert len(manifest["author_notes"]) >= 64


@pytest.fixture(scope="module")
def correct_trials():
    return run_validation(MixedExecutor())["trials"]


def test_repeated_validation_preserves_failures_and_variation(correct_trials):
    good = summarize_validation(correct_trials)
    assert good["complete"] and good["pre_registered_gate_passed"] and good["perfect_repeatability"]
    assert len(good["checks"]) == 30
    assert {g["observations"] for g in good["groups"]} == {320, 340}
    executor = MixedExecutor(mutate="frontmatter_update")
    saved = []
    result = run_validation(executor, on_trial=saved.append)
    summary = result["summary"]
    assert len(executor.calls) == 30 and len(saved) == 10
    assert summary["complete"] and not summary["pre_registered_gate_passed"]
    assert not summary["perfect_repeatability"]
    bad = [c for c in summary["checks"] if not c["passed"]]
    assert len(bad) == 1 and bad[0]["mutation_side_errors"][0]["case_id"] == "holdout-033"
    group = next(g for g in summary["groups"] if g["model"] == MODELS[0] and g["corpus"] == "holdout")
    assert group["passed_observations"] == 319
    assert group["stable_correct_cases"] == 63
    assert group["unstable_cases"]["holdout-033"] == ["governance_bearing", *(["exploratory"] * 4)]
    assert group["all_repeats_passed"] is False


@pytest.mark.parametrize("tamper", ["duplicate", "corpus", "prompt", "schema", "seed", "score", "model", "route", "order", "fingerprint"])
def test_invalid_or_partial_trials_cannot_claim_robustness(correct_trials, tamper):
    trials = copy.deepcopy(correct_trials)
    r = trials[0]["receipt"]
    if tamper == "duplicate":
        trials[1] = trials[0]
    elif tamper == "corpus":
        r["dataset"]["sha256"] = "0" * 64
    elif tamper == "prompt":
        r["instruction_sha256"] = "0" * 64
    elif tamper == "schema":
        r["schema_sha256"] = "0" * 64
    elif tamper == "seed":
        r["shuffle_seed"] = 999
    elif tamper == "score":
        r["runs"][0]["metrics"]["pass_rate"] = 0.0
    elif tamper == "model":
        r["runs"][0]["model"] = MODELS[1]
    elif tamper == "route":
        r["runs"][0]["reasoning_effort"] = "high"
    elif tamper == "fingerprint":
        r["input_sha256"] = "0" * 64
    elif tamper == "order":
        trials[3]["receipt"]["input_sha256"] = trials[0]["receipt"]["input_sha256"]
    with pytest.raises(ValueError):
        summarize_validation(trials)
    partial = summarize_validation(correct_trials[:2])
    assert partial["complete"] is False and partial["pre_registered_gate_passed"] is False
    assert partial["perfect_repeatability"] is False
    assert all(g["stable_correct_cases"] is None for g in partial["groups"])


def test_transport_failure_stops_and_keeps_receipt_without_retry():
    executor = MixedExecutor(invalid="provider")
    saved = []
    result = run_validation(executor, on_trial=saved.append)
    assert len(executor.calls) == 1 and len(saved) == 1
    assert result["summary"]["complete"] is False
    assert result["summary"]["pre_registered_gate_passed"] is False
    assert "PRIVATE-PROVIDER-ERROR-CANARY" not in json.dumps(result)


def test_frozen_plan_keeps_existing_protocol_and_authority():
    from app.eval.subscription_classification import DECISION_INSTRUCTIONS, DECISION_PROTOCOL, EFFORT, MODELS
    frozen = yaml.safe_load(HOLDOUT_PATH.read_text())["frozen_protocol"]
    assert hashlib.sha256(DECISION_INSTRUCTIONS.encode()).hexdigest() == frozen["instruction_sha256"]
    assert DECISION_PROTOCOL == frozen["protocol"]
    assert EFFORT == frozen["effort"] and list(MODELS) == frozen["models"]
    plan = validation_plan()
    assert len(plan["trials"]) == 10
    assert plan["instruction_sha256"] == hashlib.sha256(DECISION_INSTRUCTIONS.encode()).hexdigest()
    assert plan["thresholds"] == yaml.safe_load(Path("config/eval_thresholds.yaml").read_text())["classification"]


def test_acceptable_alternative_variation_is_not_perfect_repeatability(correct_trials):
    from app.eval.classification import evaluate_classification
    trials = copy.deepcopy(correct_trials)
    cases = load_classification_cases()
    case = next(c for c in cases if c.acceptable)
    run = trials[0]["receipt"]["runs"][0]
    run["case_outcomes"][case.id] = case.acceptable[0]
    run["metrics"].update(evaluate_classification(cases, run["case_outcomes"]))
    summary = summarize_validation(trials)
    assert summary["complete"] is True and summary["pre_registered_gate_passed"] is True
    assert summary["perfect_repeatability"] is False
    assert summary["checks"][0]["accepted_alternative_cases"] == 1
    assert case.id in summary["groups"][0]["unstable_cases"]


def test_plan_drift_refuses_before_inference(monkeypatch):
    import app.eval.subscription_validation as module
    plan = validation_plan()
    drifted = copy.deepcopy(plan)
    drifted["source_sha256"]["app/eval/subscription_classification.py"] = "0" * 64
    plans = iter([plan, drifted])
    monkeypatch.setattr(module, "validation_plan", lambda: next(plans))
    executor = MixedExecutor()
    with pytest.raises(ValueError, match="experiment changed"):
        run_validation(executor)
    assert executor.calls == []


def test_runtime_metadata_drift_stops_before_next_trial():
    class DriftExecutor(MixedExecutor):
        def execute(self, **kwargs):
            result = super().execute(**kwargs)
            if len(self.calls) >= 4:
                result.cli_version = "unexpected-runtime"
            return result

    executor = DriftExecutor()
    saved = []
    with pytest.raises(ValueError, match="mixed runtime identity"):
        run_validation(executor, on_trial=saved.append)
    assert len(executor.calls) == 6 and len(saved) == 2
    assert saved[-1]["receipt"]["runs"][0]["cli_version"] == "unexpected-runtime"
