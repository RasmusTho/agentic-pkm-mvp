from __future__ import annotations

from hashlib import sha256
from typing import Literal

from pydantic import BaseModel, Field

from app.source_understanding.p0 import SourceAnchor, SourceUnderstandingPacket


IntegrationPosture = Literal["retrieved_context", "agent_speculation", "context_unavailable"]
ActionHandoffTarget = Literal["act_panel_governance"]


class VaultContextReference(BaseModel):
    artifact_id: str
    source_ref: str
    title: str
    freshness: str = "fresh"
    trust_posture: str = "source reference only"


class IntegrationCandidate(BaseModel):
    posture: IntegrationPosture
    source_anchor: SourceAnchor
    rationale: str
    vault_reference: VaultContextReference | None = None
    degraded_reason: str | None = None
    review_needed: bool = True


class SourceUnderstandingActionProposal(BaseModel):
    proposal_id: str
    proposal_class: Literal["proposal"] = "proposal"
    status: str = "non-authoritative review-needed action proposal"
    label: str
    source_anchor: SourceAnchor
    source_freshness: str
    proposal_identity: str
    review_needed: bool = True
    task_created: bool = False
    commitment_created: bool = False
    approval_granted: bool = False
    urgency: str | None = None
    durable_writes: bool = False
    memory_writes: bool = False


class ActionHandoff(BaseModel):
    target: ActionHandoffTarget = "act_panel_governance"
    proposal_id: str
    proposal_identity: str
    source_anchor: SourceAnchor
    source_freshness: str
    status: str = "handoff metadata only; governed confirmation required before action"
    durable_writes: bool = False
    memory_writes: bool = False
    receipt_created: bool = False


class SourceUnderstandingIntegrationActionLenses(BaseModel):
    lens_title: str = "Source Understanding Integration/Action Lenses"
    status: str = "non-authoritative source-bounded integration/action projection"
    scope: str
    source: SourceAnchor
    integration: list[IntegrationCandidate]
    actions: list[SourceUnderstandingActionProposal]
    review_posture: list[str]
    durable_writes: bool = False
    memory_writes: bool = False
    canonical_artifact_created: bool = False
    task_created: bool = False
    commitment_created: bool = False
    receipt_created: bool = False
    mutation_intents: list[str] = Field(default_factory=list)


def _proposal_id(packet: SourceUnderstandingPacket, label: str, index: int) -> str:
    basis = "|".join([packet.source.source_id, packet.source.source_ref, packet.scope, label, str(index)])
    return f"su-action-{sha256(basis.encode('utf-8')).hexdigest()[:16]}"


def _integration_candidates(
    packet: SourceUnderstandingPacket,
    vault_context: list[VaultContextReference] | None,
) -> list[IntegrationCandidate]:
    if not vault_context:
        return [
            IntegrationCandidate(
                posture="context_unavailable",
                source_anchor=packet.source,
                rationale=(
                    "No retrieved vault context was supplied; integration links are unavailable "
                    "rather than fabricated."
                ),
                degraded_reason="vault context unavailable",
            )
        ]
    candidates = [
        IntegrationCandidate(
            posture="retrieved_context",
            source_anchor=packet.source,
            vault_reference=ref,
            rationale=(
                f"Retrieved context {ref.title!r} may help compare or place this source; "
                "review the source and vault artifact before stabilizing the connection."
            ),
        )
        for ref in vault_context
    ]
    candidates.append(
        IntegrationCandidate(
            posture="agent_speculation",
            source_anchor=packet.source,
            rationale=(
                "Agent speculation: the supplied source may connect to nearby concepts, but no "
                "additional vault artifact is asserted for this candidate."
            ),
        )
    )
    return candidates


def _action_label(packet: SourceUnderstandingPacket, fallback_index: int) -> str:
    if packet.possible_next_steps and fallback_index < len(packet.possible_next_steps):
        return packet.possible_next_steps[fallback_index]
    if packet.claims:
        return f"Review source claim: {packet.claims[0].claim}"
    return "Review source understanding packet"


def _action_proposals(
    packet: SourceUnderstandingPacket,
    *,
    source_freshness: str,
) -> list[SourceUnderstandingActionProposal]:
    labels = [
        label
        for label in [_action_label(packet, 0), "Review before creating any task or stabilized artifact."]
        if label
    ]
    proposals: list[SourceUnderstandingActionProposal] = []
    for index, label in enumerate(labels[:3]):
        proposal_id = _proposal_id(packet, label, index)
        proposals.append(
            SourceUnderstandingActionProposal(
                proposal_id=proposal_id,
                label=label,
                source_anchor=packet.source,
                source_freshness=source_freshness,
                proposal_identity=proposal_id,
            )
        )
    return proposals


def build_integration_action_lenses(
    packet: SourceUnderstandingPacket,
    *,
    vault_context: list[VaultContextReference] | None = None,
    source_freshness: str = "fresh",
) -> SourceUnderstandingIntegrationActionLenses:
    """Build read-only Integration and Action lenses from a P0 packet.

    Integration candidates are grounded in explicit caller-supplied vault context or
    degrade. Action candidates are proposal-class review objects only; generation does
    not create tasks, commitments, notes, relations, metadata, memory, or receipts.
    """

    scope_label = "selected passage" if packet.scope == "selected_passage" else "whole document"
    return SourceUnderstandingIntegrationActionLenses(
        scope=packet.scope,
        source=packet.source,
        integration=_integration_candidates(packet, vault_context),
        actions=_action_proposals(packet, source_freshness=source_freshness),
        review_posture=[
            f"Integration and Action lenses are bounded to the supplied {scope_label}.",
            "Integration candidates distinguish retrieved context from agent speculation.",
            "Action candidates are proposal-class review objects, not tasks, approvals, urgency, or commitments.",
            "No canonical note, relation, metadata, memory, receipt, task, or commitment was written.",
            packet.source.limitation or "Source identity is present; freshness and source review remain required.",
        ],
    )


def build_action_handoff(
    proposal: SourceUnderstandingActionProposal,
    *,
    target: ActionHandoffTarget = "act_panel_governance",
) -> ActionHandoff:
    return ActionHandoff(
        target=target,
        proposal_id=proposal.proposal_id,
        proposal_identity=proposal.proposal_identity,
        source_anchor=proposal.source_anchor,
        source_freshness=proposal.source_freshness,
    )


__all__ = [
    "ActionHandoff",
    "IntegrationCandidate",
    "SourceUnderstandingActionProposal",
    "SourceUnderstandingIntegrationActionLenses",
    "VaultContextReference",
    "build_action_handoff",
    "build_integration_action_lenses",
]
