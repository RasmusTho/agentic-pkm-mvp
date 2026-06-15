"""Expansion Activation Gate (#2025).

Deterministic, fail-loud implementation of the inbound admit-by predicate and
the dormant->active activation decision. See :mod:`app.activation.gate`.
"""

from app.activation.gate import (
    AdmissibilityDecision,
    AdmissionTier,
    ActivationDecision,
    ActivationPosture,
    AxisOutcome,
    CandidateContext,
    ConsumingAuthority,
    ConsumingContext,
    GateDecisionReceipt,
    TrustArchetype,
    evaluate_activation,
    evaluate_admissibility,
)

__all__ = [
    "AdmissibilityDecision",
    "AdmissionTier",
    "ActivationDecision",
    "ActivationPosture",
    "AxisOutcome",
    "CandidateContext",
    "ConsumingAuthority",
    "ConsumingContext",
    "GateDecisionReceipt",
    "TrustArchetype",
    "evaluate_activation",
    "evaluate_admissibility",
]
