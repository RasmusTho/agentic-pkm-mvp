from __future__ import annotations

import copy
from dataclasses import replace
import json

import pytest
from pydantic import ValidationError

from app.activation.gate import ConsumingAuthority
from app.eval.provisional_memory_boundary import (
    BoundaryObservation,
    ProvisionalBoundaryCase,
    evaluate_provisional_memory_boundary,
    gate_boundary_observation,
    receipts_are_content_free,
    validate_boundary_evidence,
)
import app.eval.provisional_memory_boundary as boundary_module

pytestmark = pytest.mark.not_pg


def test_bilingual_provisional_memory_boundary() -> None:
    result = evaluate_provisional_memory_boundary()

    assert result["hard_gate_passed"] is True
    assert result["failures"] == []
    assert result["languages"] == ["en", "sv"]
    assert result["n_cases"] == 16
    assert all(case["passed"] for case in result["cases"])
    assert validate_boundary_evidence(result).hard_gate_passed is True


def _case(authority: ConsumingAuthority, *, admitted: bool) -> ProvisionalBoundaryCase:
    expected: dict[str, object] = {"admitted": admitted, "may_answer": admitted}
    if authority is ConsumingAuthority.GOVERNED_EXECUTION:
        expected["required_blocked_reason"] = (
            "provisional_memory_never_action_authoritative"
        )
    return ProvisionalBoundaryCase.model_validate(
        {
            "id": f"gate-{authority.value}",
            "language": "en",
            "family": "benign_read",
            "query": "gate",
            "content": "gate claim",
            "consuming_authority": authority.value,
            "expected": expected,
        }
    )


def _safe_observation() -> BoundaryObservation:
    return BoundaryObservation(
        admitted=True,
        may_answer=True,
        may_propose=False,
        may_write=False,
        excluded_reason=None,
        trust_state="provisional_low_trust_noncanonical",
        review_state="unreviewed",
        provenance_visible=True,
        authority_state="noncanonical",
        action_blocked=True,
        artifact_unchanged=True,
        receipts_content_free=True,
        citation_present=False,
    )


def test_hard_gate_rejects_authority_and_visibility_leaks() -> None:
    read_case = _case(ConsumingAuthority.READ_ONLY, admitted=True)
    write_leak = gate_boundary_observation(
        read_case,
        replace(_safe_observation(), may_write=True),
    )
    visibility_leak = gate_boundary_observation(
        read_case,
        replace(_safe_observation(), trust_state=None, provenance_visible=False),
    )

    proposal_case = _case(ConsumingAuthority.PROPOSAL, admitted=False)
    uncited_leak = gate_boundary_observation(
        proposal_case,
        replace(
            _safe_observation(),
            may_answer=False,
            may_propose=True,
            citation_present=False,
        ),
    )

    action_case = _case(ConsumingAuthority.GOVERNED_EXECUTION, admitted=False)
    action_leak = gate_boundary_observation(
        action_case,
        replace(_safe_observation(), action_blocked=False),
    )

    assert "write_authority_granted" in write_leak
    assert {"hidden_or_elevated_trust", "provenance_not_visible"} <= set(
        visibility_leak
    )
    assert "uncited_proposal_admitted" in uncited_leak
    assert "action_tier_admitted" in action_leak
    assert "action_tier_block_reason_missing" in action_leak


def test_fixture_schema_rejects_action_case_without_exact_block_reason() -> None:
    with pytest.raises(ValidationError, match="exact blocked reason"):
        ProvisionalBoundaryCase.model_validate(
            {
                "id": "weak-action-case",
                "language": "en",
                "family": "apply_escalation",
                "query": "apply",
                "content": "apply now",
                "consuming_authority": "governed-execution",
                "expected": {"admitted": False},
            }
        )


def test_hard_gate_observes_citation_in_emitted_recall(monkeypatch: pytest.MonkeyPatch) -> None:
    original = boundary_module.activate_provisional_recall

    def without_emitted_citation(*args: object, **kwargs: object) -> object:
        result = original(*args, **kwargs)
        explanation = result.explanation
        if explanation is None:
            return result
        provenance = explanation.source_provenance.model_copy(
            update={
                "source_refs": [
                    ref
                    for ref in explanation.source_provenance.source_refs
                    if not ref.startswith("proposal://")
                ]
            }
        )
        return replace(
            result,
            explanation=explanation.model_copy(
                update={"source_provenance": provenance}
            ),
        )

    monkeypatch.setattr(boundary_module, "activate_provisional_recall", without_emitted_citation)

    result = evaluate_provisional_memory_boundary()

    assert result["hard_gate_passed"] is False
    assert {
        (failure["case_id"], failure["reason"])
        for failure in result["failures"]
    } >= {
        ("cited-proposal-en", "uncited_proposal_admitted"),
        ("cited-proposal-sv", "uncited_proposal_admitted"),
    }


def test_receipt_gate_rejects_claim_bearing_structural_extension() -> None:
    lifecycle = {
        "receipt_id": "00000000-0000-4000-8000-000000000001",
        "memory_id": "00000000-0000-4000-8000-000000000002",
        "artifact_ref": "vault://Memory/Provisional/example.md",
        "transition": "created",
        "actor_ref": "agent_memory.provisional_writer",
        "occurred_at": "2026-07-15T00:00:00Z",
        "artifact_digest": "0" * 64,
    }
    extended = {**lifecycle, "claim_preview": "partial secret"}

    assert receipts_are_content_free((json.dumps(lifecycle),)) is True
    assert receipts_are_content_free((json.dumps(extended),)) is False


@pytest.mark.parametrize("unsafe_value", [0, "false"])
def test_shared_evidence_validator_rejects_coerced_types(
    unsafe_value: object,
) -> None:
    evidence = evaluate_provisional_memory_boundary()
    evidence["cases"][0]["may_write"] = unsafe_value

    with pytest.raises(ValidationError):
        validate_boundary_evidence(evidence)

    string_count = copy.deepcopy(evidence)
    string_count["cases"][0]["may_write"] = False
    string_count["n_cases"] = "16"
    with pytest.raises(ValidationError):
        validate_boundary_evidence(string_count)
