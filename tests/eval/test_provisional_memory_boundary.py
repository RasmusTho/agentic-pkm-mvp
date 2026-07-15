from __future__ import annotations

from dataclasses import replace

import pytest
from pydantic import ValidationError

from app.activation.gate import ConsumingAuthority
from app.eval.provisional_memory_boundary import (
    BoundaryObservation,
    ProvisionalBoundaryCase,
    evaluate_provisional_memory_boundary,
    gate_boundary_observation,
)

pytestmark = pytest.mark.not_pg


def test_bilingual_provisional_memory_boundary() -> None:
    result = evaluate_provisional_memory_boundary()

    assert result["hard_gate_passed"] is True
    assert result["failures"] == []
    assert result["languages"] == ["en", "sv"]
    assert result["n_cases"] == 16
    assert all(case["passed"] for case in result["cases"])


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
