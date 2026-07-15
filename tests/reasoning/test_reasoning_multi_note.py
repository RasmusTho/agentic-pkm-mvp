# Reasoning multi-note entrypoint:
#   app/reasoning/multi.py:run_multi_note_reasoning(...)
from __future__ import annotations

import pytest

from app.reasoning.multi import run_multi_note_reasoning
from app.reasoning.schema import Claim, Evidence, Inference, ReasoningOutput
from app.reasoning.store import reset_reasoning_store
from app.stores import get_object_store
from tests.helpers.pkm_alpha_helper import load_pkm_alpha_subset_for_reasoning, reset_memory_stores

pytestmark = [pytest.mark.not_pg, pytest.mark.alpha_llm]


@pytest.fixture
def memory_object_store(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("REASONING_ENABLE", "1")
    reset_memory_stores()
    yield get_object_store()
    reset_reasoning_store()
    reset_memory_stores()


def _reasoning_item_mentions_both_sources(item, ids: set[str]) -> bool:
    text_fields = []
    for attr in ("rationale", "text", "reason"):
        val = getattr(item, attr, None)
        if isinstance(val, str):
            text_fields.append(val)
    combined = " ".join(text_fields)
    return all(str(source_id) in combined for source_id in ids)


def test_reasoning_multi_note_synthesizes_across_pkm_alpha(memory_object_store) -> None:
    ids = load_pkm_alpha_subset_for_reasoning(memory_object_store)
    concept_id = ids["concept"]
    project_id = ids["project"]

    result = run_multi_note_reasoning([concept_id, project_id])

    assert result is not None
    assert result.inferences or result.claims
    assert any(
        _reasoning_item_mentions_both_sources(item, {concept_id, project_id})
        for item in (result.inferences or result.claims or [])
    )


def test_multi_note_provider_failure_is_degraded_without_synthetic_claims(
    memory_object_store, monkeypatch: pytest.MonkeyPatch
) -> None:
    ids = load_pkm_alpha_subset_for_reasoning(memory_object_store)
    object_ids = [ids["concept"], ids["project"]]

    monkeypatch.setattr(
        "app.reasoning.multi.run_reasoning_claims_for_object",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("provider unavailable")),
    )

    failed = run_multi_note_reasoning(object_ids)

    assert failed.outcome == "provider_failure"
    assert failed.degraded is True
    assert failed.degraded_reason == "provider_failure"
    assert failed.claims == []
    assert failed.evidence == []
    assert failed.inferences == []

    monkeypatch.setattr(
        "app.reasoning.multi.run_reasoning_claims_for_object",
        lambda *_args, **_kwargs: ReasoningOutput(),
    )

    empty = run_multi_note_reasoning(object_ids)

    assert empty.outcome == "empty_output"
    assert empty.degraded is True
    assert empty.degraded_reason == "empty_provider_output"
    assert empty.claims == []
    assert empty.evidence == []
    assert empty.inferences == []

    missing = run_multi_note_reasoning(["not-a-stored-object"])

    assert missing.outcome == "missing_input"
    assert missing.degraded is True
    assert missing.degraded_reason == "missing_input"
    assert missing.claims == []
    assert missing.evidence == []
    assert missing.inferences == []

    empty_request = run_multi_note_reasoning([])

    assert empty_request.outcome == "missing_input"
    assert empty_request.degraded is True
    assert empty_request.degraded_reason == "missing_input"
    assert empty_request.claims == []
    assert empty_request.evidence == []
    assert empty_request.inferences == []


def test_multi_note_success_preserves_real_provider_output(
    memory_object_store, monkeypatch: pytest.MonkeyPatch
) -> None:
    ids = load_pkm_alpha_subset_for_reasoning(memory_object_store)
    object_ids = [ids["concept"], ids["project"]]

    def provider_result(object_id: str, *, trace_id: str | None = None) -> ReasoningOutput:
        del trace_id
        suffix = "concept" if object_id == ids["concept"] else "project"
        claim_id = f"claim-{suffix}"
        return ReasoningOutput(
            claims=[
                Claim(
                    id=claim_id,
                    object_uuid=object_id,
                    text=f"Real provider claim for {suffix}",
                    modality="assertion",
                    confidence=0.9,
                )
            ],
            evidence=[
                Evidence(
                    id=f"evidence-{suffix}",
                    object_uuid=object_id,
                    source_ref=f"{suffix}.md",
                    kind="document",
                    strength=0.8,
                )
            ],
            inferences=[
                Inference(
                    id=f"inference-{suffix}",
                    premises=[claim_id],
                    conclusion_id=claim_id,
                    type="support",
                    rationale=f"Provider rationale for {suffix}",
                )
            ],
        )

    monkeypatch.setattr("app.reasoning.multi.run_reasoning_claims_for_object", provider_result)

    result = run_multi_note_reasoning(object_ids)

    assert result.outcome == "success"
    assert result.degraded is False
    assert result.degraded_reason is None
    assert {claim.id for claim in result.claims} == {"claim-concept", "claim-project"}
    assert {evidence.id for evidence in result.evidence} == {
        "evidence-concept",
        "evidence-project",
    }
    assert {"inference-concept", "inference-project"}.issubset(
        {inference.id for inference in result.inferences}
    )


def test_multi_note_missing_input_preserves_only_real_provider_cognition(
    memory_object_store, monkeypatch: pytest.MonkeyPatch
) -> None:
    ids = load_pkm_alpha_subset_for_reasoning(memory_object_store)
    available_ids = [ids["concept"], ids["project"]]

    def provider_result(object_id: str, *, trace_id: str | None = None) -> ReasoningOutput:
        del trace_id
        return ReasoningOutput(
            claims=[
                Claim(
                    id=f"claim-{object_id}",
                    object_uuid=object_id,
                    text=f"Provider claim for {object_id}",
                    modality="assertion",
                    confidence=0.9,
                )
            ]
        )

    monkeypatch.setattr("app.reasoning.multi.run_reasoning_claims_for_object", provider_result)

    result = run_multi_note_reasoning(
        [available_ids[0], "not-a-stored-object", available_ids[1]]
    )

    assert result.outcome == "missing_input"
    assert result.degraded is True
    assert {claim.id for claim in result.claims} == {
        f"claim-{available_ids[0]}",
        f"claim-{available_ids[1]}",
    }
    assert result.inferences == []
