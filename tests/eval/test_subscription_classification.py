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
        from app.model_access.codex_cli import _bounded_schema_snapshot
        _bounded_schema_snapshot(kwargs["output_schema_ref"], kwargs["output_schema"], max_bytes=100000)
        self.calls.append(kwargs)
        cases_by_text = {c.utterance: c for c in load_classification_cases()}
        answers = [{"case_id": item["case_id"],
                    "abstain": cases_by_text[item["intent"]].expected_intent == "unknown",
                    "intent_class": (None if cases_by_text[item["intent"]].expected_intent == "unknown"
                                     else cases_by_text[item["intent"]].expected_intent),
                    "action_type": cases_by_text[item["intent"]].expected_action_type,
                    "rationale": "PRIVATE-COMPLETION-CANARY"}
                   for item in json.loads(kwargs["user_prompt"])]
        if self.invalid == "unsafe_conflicts":
            for answer, item in zip(answers, json.loads(kwargs["user_prompt"])):
                if cases_by_text[item["intent"]].id in {
                    "multi-en-archive-but-keep-writing", "multi-sv-arkivera-men-fortsatta"
                }:
                    answer.update(abstain=False, intent_class="governance_bearing", action_type="note_lifecycle")
        elif self.invalid == "all_abstain":
            for answer in answers:
                answer.update(abstain=True, intent_class=None, action_type=None)
        elif self.invalid == "contradictory":
            answers[0].update(abstain=True, intent_class="governance_bearing", action_type="note_lifecycle")
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
        source_ids = {c.id for c in load_classification_cases()}
        assert not (source_ids & {item["case_id"] for item in json.loads(call["user_prompt"])})
        assert [item["intent"] for item in json.loads(call["user_prompt"])] != [
            c.utterance for c in load_classification_cases()]
        assert run["batch_elapsed_seconds"] >= 0


@pytest.mark.parametrize("failure", ["duplicate", "missing", "provider", "contradictory"])
def test_incomplete_batch_stops_without_partial_quality_or_provider_text(failure):
    executor = FakeExecutor(invalid=failure)
    result = run_comparison(executor)
    assert result["complete"] is False and result["hard_gate_passed"] is False
    assert len(executor.calls) == 1
    assert result["runs"][0]["metrics"] is None
    assert result["runs"][0]["completed_cases"] == 0
    assert "PRIVATE-PROVIDER-ERROR-CANARY" not in json.dumps(result)


@pytest.mark.parametrize("patch", [
    {"abstain": "true"}, {"abstain": 1},
    {"intent_class": "governance_bearing"}, {"action_type": "note_lifecycle"},
    {"rationale": 1}, {"unexpected": True},
    {"abstain": False}, {"abstain": False, "intent_class": "unknown"},
    {"abstain": False, "intent_class": "exploratory", "action_type": "note_lifecycle"},
    {"abstain": False, "intent_class": "governance_bearing"},
])
def test_explicit_abstention_is_validated_before_local_unknown(patch):
    from app.eval.classification import _legacy_comparator
    from app.eval.subscription_classification import validated_decision_completion

    abstention = {"abstain": True, "intent_class": None, "action_type": None, "rationale": None}
    completion = validated_decision_completion(abstention)
    assert _legacy_comparator("a synthetic unresolved request", lambda **kw: completion, "test") == "unknown"
    with pytest.raises(ValueError):
        validated_decision_completion({**abstention, **patch})
    for missing in abstention:
        with pytest.raises(ValueError):
            validated_decision_completion({k: v for k, v in abstention.items() if k != missing})
    concrete = {"abstain": False, "intent_class": "governance_bearing",
                "action_type": "note_lifecycle", "rationale": None}
    valid = validated_decision_completion(concrete)
    assert _legacy_comparator("a synthetic resolved request", lambda **kw: valid, "test") == "governance_bearing"


def test_abstention_protocol_does_not_weaken_quality_scoring():
    from app.eval.subscription_classification import DECISION_INSTRUCTIONS, DECISION_PROTOCOL

    correct = run_comparison(FakeExecutor())
    for run in correct["runs"]:
        assert run["hard_gate_passed"] is True and run["metrics"]["pass_rate"] == 1.0
        assert run["abstained_cases"] == 8
        assert run["case_outcomes"]["multi-en-archive-but-keep-writing"] == "unknown"
        assert run["case_outcomes"]["multi-sv-arkivera-men-fortsatta"] == "unknown"
        assert run["case_outcomes"]["multi-sv-snygga-till-och-arkivera"] == "governance_bearing"
    assert correct["decision_protocol"] == DECISION_PROTOCOL
    assert len(correct["instruction_sha256"]) == len(correct["schema_sha256"]) == 64
    for case in load_classification_cases():
        assert case.id not in DECISION_INSTRUCTIONS and case.utterance not in DECISION_INSTRUCTIONS

    unsafe = run_comparison(FakeExecutor(invalid="unsafe_conflicts"))
    assert unsafe["complete"] is True and unsafe["hard_gate_passed"] is False
    for run in unsafe["runs"]:
        assert {c["case_id"] for c in run["metrics"]["mutation_side_confusions"]} == {
            "multi-en-archive-but-keep-writing", "multi-sv-arkivera-men-fortsatta"}

    vacuous = run_comparison(FakeExecutor(invalid="all_abstain"))
    for run in vacuous["runs"]:
        assert run["abstained_cases"] == 68
        assert run["metrics"]["safe_fail"]["answer_rate"] == 0.0
        assert run["metrics"]["pass_rate"] == 8 / 68
