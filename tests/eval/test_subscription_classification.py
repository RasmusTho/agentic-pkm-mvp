import json
from types import SimpleNamespace

import pytest

from app.eval.classification import load_classification_cases
from app.eval.subscription_classification import MODELS, preflight_targets, run_comparison


class FakeExecutor:
    def __init__(self, *, missing=None, invalid=None):
        self.missing = missing
        self.invalid = invalid
        self.calls = []

    def list_catalog_models(self):
        return [{"model": m, "hidden": False, "structuredOutputSupported": True,
                 "supportedReasoningEfforts": [{"reasoningEffort": "low"}]} for m in MODELS
                if m != self.missing]

    def execute(self, **kwargs):
        self.calls.append(kwargs)
        answers = [{"case_id": c.id, "intent_class": c.expected_intent,
                    "action_type": c.expected_action_type, "rationale": "PRIVATE-COMPLETION-CANARY"}
                   for c in load_classification_cases()]
        if self.invalid == "duplicate":
            answers[-1] = answers[0]
        elif self.invalid == "missing":
            answers.pop()
        elif self.invalid == "provider":
            raise RuntimeError("PRIVATE-PROVIDER-ERROR-CANARY")
        return SimpleNamespace(response_text=json.dumps({"answers": answers}),
                               cli_version="fixture-version", safe_profile_ref="fixture-profile")


def test_preflight_refuses_unavailable_targets_before_inference():
    executor = FakeExecutor(missing=MODELS[-1])
    with pytest.raises(ValueError):
        run_comparison(executor)
    assert executor.calls == []
    with pytest.raises(ValueError):
        preflight_targets(FakeExecutor(), (MODELS[0], MODELS[0]))
    with pytest.raises(ValueError):
        preflight_targets(FakeExecutor(), ("gpt-5.4-mini",))
    for field, value in (("hidden", True), ("structuredOutputSupported", False),
                         ("supportedReasoningEfforts", [])):
        executor = FakeExecutor()
        catalog = executor.list_catalog_models()
        catalog[-1][field] = value
        executor.list_catalog_models = lambda: catalog
        with pytest.raises(ValueError):
            run_comparison(executor)
        assert executor.calls == []


def test_subscription_receipt_is_content_free_and_billing_unavailable():
    executor = FakeExecutor()
    result = run_comparison(executor)
    assert result["complete"] is True
    assert len(executor.calls) == 3
    assert result["baseline"] == {"model": "gpt-5.4-mini", "available": False, "evaluated": False}
    rendered = json.dumps(result)
    assert "PRIVATE-COMPLETION-CANARY" not in rendered
    for c in load_classification_cases():
        assert c.utterance not in rendered
    for run, call in zip(result["runs"], executor.calls):
        assert run["completed_cases"] == len(load_classification_cases())
        assert run["cost"] is None and run["usage"] is None and run["served_model"] is None
        assert run["model"] == call["model"]
        assert call["reasoning_effort"] == "low"
        assert all(set(c) == {"case_id", "intent"} for c in json.loads(call["user_prompt"]))
        assert "expected_intent" not in call["user_prompt"]
        assert run["batch_elapsed_seconds"] >= 0


@pytest.mark.parametrize("failure", ["duplicate", "missing", "provider"])
def test_incomplete_batch_stops_without_partial_quality_or_provider_text(failure):
    executor = FakeExecutor(invalid=failure)
    result = run_comparison(executor)
    assert result["complete"] is False and result["hard_gate_passed"] is False
    assert len(executor.calls) == 1
    assert result["runs"][0]["metrics"] is None
    assert result["runs"][0]["completed_cases"] == 0
    assert "PRIVATE-PROVIDER-ERROR-CANARY" not in json.dumps(result)
