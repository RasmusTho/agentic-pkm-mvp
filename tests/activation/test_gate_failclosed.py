"""Fail-closed activation-gate guards (issue #2148 / #2187).

Covers two production-path invariants on ``evaluate_activation``:

1. Activation requires admission AT the declared authority's tier — a candidate
   admissible only at a lower tier must not satisfy a higher-authority posture
   (``app/activation/gate.py`` admitted-tier filter).
2. Observability defaults to blocked until explicitly declared green
   (``ActivationPosture.observable`` defaults ``False``).
"""

from __future__ import annotations

from app.activation.gate import (
    REASON_NO_ADMISSIBLE_CONTEXT,
    REASON_NOT_OBSERVABLE,
    ActivationPosture,
    AdmissionTier,
    CandidateContext,
    ConsumingAuthority,
    ConsumingContext,
    TrustArchetype,
    evaluate_activation,
    evaluate_admissibility,
)
from app.agent_memory.candidate import ReviewState


def _accepted_candidate(artifact_id: str = "hit-action") -> CandidateContext:
    return CandidateContext(
        artifact_id=artifact_id,
        sphere="work",
        trust_archetype=TrustArchetype.HUMAN_AUTHORED_ACCEPTED,
        review_state=ReviewState.ACCEPTED,
    )


def _reviewed_only_candidate(artifact_id: str = "hit-reviewed") -> CandidateContext:
    # Machine-proposed + merely REVIEWED provenance admits at CITED_PROPOSAL,
    # strictly below the ACTION tier a GOVERNED_EXECUTION posture requires.
    return CandidateContext(
        artifact_id=artifact_id,
        sphere="work",
        trust_archetype=TrustArchetype.MACHINE_PROPOSED,
        review_state=ReviewState.REVIEWED,
    )


def _govexec_posture(**overrides: object) -> ActivationPosture:
    base: dict[str, object] = dict(
        capability_id="cap.govexec",
        declared_authority=ConsumingAuthority.GOVERNED_EXECUTION,
        admissibility_declared=True,
        loop_precondition_green=True,
        reversible_write_path=True,
        observable=True,
        scope="work",
    )
    base.update(overrides)
    return ActivationPosture(**base)  # type: ignore[arg-type]


def test_governed_execution_requires_action_tier_admission() -> None:
    """A candidate admitted only below ACTION must not activate a GOVERNED_EXECUTION posture."""
    reviewed = _reviewed_only_candidate()
    # Sanity: the candidate IS admitted, but at a tier strictly below ACTION.
    decision = evaluate_admissibility(
        reviewed, ConsumingContext(capability_id="cap.govexec", authority=ConsumingAuthority.GOVERNED_EXECUTION, scope="work")
    )
    assert decision.admitted is True
    assert decision.admitted_tier is not AdmissionTier.ACTION

    blocked = evaluate_activation(_govexec_posture(), [reviewed])
    assert blocked.activatable is False
    assert REASON_NO_ADMISSIBLE_CONTEXT in blocked.blocked_reasons
    assert reviewed.artifact_id not in blocked.admitted_artifact_ids

    # Control: an ACTION-tier (ACCEPTED) candidate activates the same posture.
    ok = evaluate_activation(_govexec_posture(), [_accepted_candidate()])
    assert ok.activatable is True
    assert REASON_NO_ADMISSIBLE_CONTEXT not in ok.blocked_reasons


def test_observability_defaults_to_blocked_until_declared() -> None:
    """ActivationPosture.observable defaults False -> undeclared observability blocks."""
    undeclared = ActivationPosture(
        capability_id="ask.answer_synthesis",
        declared_authority=ConsumingAuthority.READ_ONLY,
        admissibility_declared=True,
        loop_precondition_green=True,
        scope="work",
    )
    assert undeclared.observable is False
    decision = evaluate_activation(undeclared, [_accepted_candidate()])
    assert decision.activatable is False
    assert REASON_NOT_OBSERVABLE in decision.blocked_reasons

    # Control: explicitly declaring observability clears that block.
    declared = evaluate_activation(
        ActivationPosture(
            capability_id="ask.answer_synthesis",
            declared_authority=ConsumingAuthority.READ_ONLY,
            admissibility_declared=True,
            loop_precondition_green=True,
            observable=True,
            scope="work",
        ),
        [_accepted_candidate()],
    )
    assert REASON_NOT_OBSERVABLE not in declared.blocked_reasons
