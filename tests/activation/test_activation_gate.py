"""Explicit, fail-loud tests for the deterministic Expansion Activation Gate (#2025).

Verification-load-bearing per #1997: every admit / refuse / blocked-reason path
and every fail-loud guard is asserted explicitly. These tests must never be
closed-on-green — a regression in the gate must fail here, loudly.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.activation.gate import (
    REASON_ADMISSIBILITY_UNDECLARED,
    REASON_CONTRADICTED_OR_REJECTED,
    REASON_CROSS_SPHERE_NO_ALLOWANCE,
    REASON_LOOP_PRECONDITION_NOT_GREEN,
    REASON_NO_ADMISSIBLE_CONTEXT,
    REASON_NO_REVERSIBLE_WRITE_PATH,
    REASON_UNDECLARED_CONSUMER,
    ActivationPosture,
    AdmissionTier,
    CandidateContext,
    ConsumingAuthority,
    ConsumingContext,
    TrustArchetype,
    evaluate_activation,
    evaluate_admissibility,
)
from app.agent_memory.candidate import ContradictionState, MemoryType, ReviewState


def _consumer(authority: ConsumingAuthority, scope: str | None = "work") -> ConsumingContext:
    return ConsumingContext(capability_id="ask.may_answer", authority=authority, scope=scope)


# --- Axis composition: ADMIT cases ----------------------------------------


def test_admit_same_scope_accepted_human_authored_reaches_action() -> None:
    decision = evaluate_admissibility(
        CandidateContext(
            artifact_id="a1",
            sphere="work",
            trust_archetype=TrustArchetype.HUMAN_AUTHORED_ACCEPTED,
            review_state=ReviewState.ACCEPTED,
            has_provenance=True,
        ),
        _consumer(ConsumingAuthority.GOVERNED_EXECUTION),
    )
    assert decision.admitted is True
    assert decision.admitted_tier is AdmissionTier.ACTION


def test_read_only_consumer_caps_admission_at_read() -> None:
    decision = evaluate_admissibility(
        CandidateContext(
            artifact_id="a2",
            sphere="work",
            trust_archetype=TrustArchetype.HUMAN_AUTHORED_ACCEPTED,
            review_state=ReviewState.ACCEPTED,
        ),
        _consumer(ConsumingAuthority.READ_ONLY),
    )
    assert decision.admitted is True
    assert decision.admitted_tier is AdmissionTier.READ


def test_cross_sphere_with_shared_participation_admits() -> None:
    decision = evaluate_admissibility(
        CandidateContext(
            artifact_id="a3",
            sphere="research",
            shared_participation=True,
            trust_archetype=TrustArchetype.HUMAN_AUTHORED_ACCEPTED,
            review_state=ReviewState.ACCEPTED,
        ),
        _consumer(ConsumingAuthority.PROPOSAL, scope="work"),
    )
    assert decision.admitted is True
    assert decision.admitted_tier is AdmissionTier.CITED_PROPOSAL


# --- Axis composition: REFUSE / exclude cases -----------------------------


def test_refuse_cross_sphere_without_allowance() -> None:
    decision = evaluate_admissibility(
        CandidateContext(
            artifact_id="b1",
            sphere="rpg",
            trust_archetype=TrustArchetype.HUMAN_AUTHORED_ACCEPTED,
            review_state=ReviewState.ACCEPTED,
        ),
        _consumer(ConsumingAuthority.READ_ONLY, scope="work"),
    )
    assert decision.admitted is False
    assert decision.admitted_tier is AdmissionTier.NONE
    assert decision.reason == REASON_CROSS_SPHERE_NO_ALLOWANCE


def test_refuse_contradicted_or_rejected_at_all_tiers() -> None:
    decision = evaluate_admissibility(
        CandidateContext(
            artifact_id="b2",
            sphere="work",
            contradiction_state=ContradictionState.CONTRADICTED,
        ),
        _consumer(ConsumingAuthority.READ_ONLY),
    )
    assert decision.admitted is False
    assert decision.reason == REASON_CONTRADICTED_OR_REJECTED


def test_refuse_undeclared_consumer() -> None:
    decision = evaluate_admissibility(
        CandidateContext(artifact_id="b3", sphere="work"),
        ConsumingContext(capability_id="ask.may_answer", authority=None, scope="work"),
    )
    assert decision.admitted is False
    assert decision.reason == REASON_UNDECLARED_CONSUMER


# --- Axis-specific ceilings ------------------------------------------------


def test_inferred_memory_never_reaches_action() -> None:
    """Floor: inferred/unreviewed admits to read + cited-proposal, never action."""
    decision = evaluate_admissibility(
        CandidateContext(
            artifact_id="c1",
            sphere="work",
            is_memory=True,
            memory_class=MemoryType.SEMANTIC_MEMORY,
            inferred=True,
        ),
        _consumer(ConsumingAuthority.GOVERNED_EXECUTION),
    )
    assert decision.admitted is True
    assert decision.admitted_tier is AdmissionTier.CITED_PROPOSAL


def test_working_context_class_caps_below_action() -> None:
    decision = evaluate_admissibility(
        CandidateContext(
            artifact_id="c2",
            sphere="work",
            is_memory=True,
            memory_class=MemoryType.WORKING_CONTEXT,
            trust_archetype=TrustArchetype.HUMAN_AUTHORED_ACCEPTED,
            review_state=ReviewState.ACCEPTED,
        ),
        _consumer(ConsumingAuthority.GOVERNED_EXECUTION),
    )
    assert decision.admitted_tier is AdmissionTier.CITED_PROPOSAL


def test_unknown_memory_class_caps_at_read() -> None:
    decision = evaluate_admissibility(
        CandidateContext(
            artifact_id="c3",
            sphere="work",
            is_memory=True,
            memory_class=None,
            trust_archetype=TrustArchetype.HUMAN_AUTHORED_ACCEPTED,
            review_state=ReviewState.ACCEPTED,
        ),
        _consumer(ConsumingAuthority.GOVERNED_EXECUTION),
    )
    assert decision.admitted_tier is AdmissionTier.READ


def test_policy_memory_action_eligible_when_accepted() -> None:
    decision = evaluate_admissibility(
        CandidateContext(
            artifact_id="c4",
            sphere="work",
            is_memory=True,
            memory_class=MemoryType.POLICY_MEMORY,
            trust_archetype=TrustArchetype.HUMAN_AUTHORED_ACCEPTED,
            review_state=ReviewState.ACCEPTED,
        ),
        _consumer(ConsumingAuthority.GOVERNED_EXECUTION),
    )
    assert decision.admitted_tier is AdmissionTier.ACTION


# --- Activation decision + receipt -----------------------------------------


def _ask_posture(**overrides: object) -> ActivationPosture:
    base: dict[str, object] = dict(
        capability_id="ask.answer_synthesis",
        declared_authority=ConsumingAuthority.READ_ONLY,
        admissibility_declared=True,
        loop_precondition_green=True,
        observable=True,
        scope="work",
    )
    base.update(overrides)
    return ActivationPosture(**base)  # type: ignore[arg-type]


def _admissible_candidate() -> CandidateContext:
    return CandidateContext(
        artifact_id="hit-1",
        sphere="work",
        trust_archetype=TrustArchetype.HUMAN_AUTHORED_ACCEPTED,
        review_state=ReviewState.ACCEPTED,
    )


def test_activation_activatable_emits_receipt() -> None:
    decision = evaluate_activation(_ask_posture(), [_admissible_candidate()])
    assert decision.activatable is True
    assert decision.blocked_reasons == []
    assert decision.admitted_artifact_ids == ["hit-1"]
    # receipt is emitted per evaluation
    assert decision.receipt.outcome == "activatable"
    assert decision.receipt.receipt_id
    assert decision.receipt.capability_id == "ask.answer_synthesis"
    assert decision.receipt.admitted_artifact_ids == ["hit-1"]
    assert len(decision.receipt.evaluated) == 1


def test_activation_blocked_when_admissibility_undeclared() -> None:
    decision = evaluate_activation(
        _ask_posture(admissibility_declared=False), [_admissible_candidate()]
    )
    assert decision.activatable is False
    assert REASON_ADMISSIBILITY_UNDECLARED in decision.blocked_reasons
    assert decision.receipt.outcome == "blocked"


def test_activation_blocked_when_loop_precondition_not_green() -> None:
    decision = evaluate_activation(
        _ask_posture(loop_precondition_green=False), [_admissible_candidate()]
    )
    assert decision.activatable is False
    assert REASON_LOOP_PRECONDITION_NOT_GREEN in decision.blocked_reasons


def test_governed_execution_requires_reversible_write_path() -> None:
    decision = evaluate_activation(
        _ask_posture(
            declared_authority=ConsumingAuthority.GOVERNED_EXECUTION,
            reversible_write_path=False,
        ),
        [_admissible_candidate()],
    )
    assert decision.activatable is False
    assert REASON_NO_REVERSIBLE_WRITE_PATH in decision.blocked_reasons


def test_activation_blocked_when_no_admissible_context() -> None:
    # a cross-sphere candidate with no allowance is not admissible
    decision = evaluate_activation(
        _ask_posture(),
        [CandidateContext(artifact_id="x", sphere="rpg")],
    )
    assert decision.activatable is False
    assert REASON_NO_ADMISSIBLE_CONTEXT in decision.blocked_reasons
    assert decision.admitted_artifact_ids == []


def test_activation_decision_is_deterministic() -> None:
    fixed = datetime(2026, 6, 15, tzinfo=timezone.utc)
    a = evaluate_activation(_ask_posture(), [_admissible_candidate()], receipt_id="r1", now=fixed)
    b = evaluate_activation(_ask_posture(), [_admissible_candidate()], receipt_id="r1", now=fixed)
    assert a.model_dump() == b.model_dump()


# --- fail-loud guards ------------------------------------------------------


def test_fail_loud_empty_artifact_id() -> None:
    with pytest.raises(ValueError):
        evaluate_admissibility(
            CandidateContext(artifact_id="", sphere="work"),
            _consumer(ConsumingAuthority.READ_ONLY),
        )


def test_fail_loud_empty_consumer_capability_id() -> None:
    with pytest.raises(ValueError):
        evaluate_admissibility(
            CandidateContext(artifact_id="a", sphere="work"),
            ConsumingContext(capability_id="", authority=ConsumingAuthority.READ_ONLY, scope="work"),
        )


def test_fail_loud_empty_posture_capability_id() -> None:
    with pytest.raises(ValueError):
        evaluate_activation(
            ActivationPosture(capability_id="", declared_authority=ConsumingAuthority.READ_ONLY),
            [],
        )
