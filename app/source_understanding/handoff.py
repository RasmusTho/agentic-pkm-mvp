from __future__ import annotations

from hashlib import sha256
from typing import Literal

from pydantic import BaseModel, Field

from app.source_understanding.p0 import SourceAnchor, SourceUnderstandingPacket


ReviewChoiceId = Literal["apply", "defer", "reject", "revise"]
ReviewChoiceEffect = Literal["governed_mutation", "runtime_only"]
StabilizedNoteKind = Literal["literature_note", "concept_note"]


class GovernedApplyPath(BaseModel):
    available: bool = False
    route_name: str = "stabilized_note_proposal_apply"
    write_guard_action: str = "source_understanding.stabilized_note.apply"
    receipt_posture: str = "governed mutation receipt required before canonical artifact change"


class StabilizedNoteReviewChoice(BaseModel):
    choice_id: ReviewChoiceId
    label: str
    effect: ReviewChoiceEffect
    available: bool = True
    requires_human_review: bool = True
    requires_governed_mutation_path: bool = False
    mutates_durable_surfaces: bool = False
    governed_route: str | None = None
    unavailable_reason: str | None = None


class StabilizedNoteProposal(BaseModel):
    proposal_id: str
    proposal_kind: Literal["stabilized_note_proposal"] = "stabilized_note_proposal"
    target_note_kind: StabilizedNoteKind
    status: str = "non-authoritative staged stabilized-note proposal"
    source: SourceAnchor
    packet_scope: str
    source_anchors: list[SourceAnchor]
    anchor_limitations: list[str] = Field(default_factory=list)
    packet_provenance: list[str]
    draft_title: str
    draft_body: str
    review_choices: list[StabilizedNoteReviewChoice]
    durable_writes: bool = False
    memory_writes: bool = False
    canonical_artifact_created: bool = False
    mutation_intents: list[str] = Field(default_factory=list)


class StabilizedNoteReviewResult(BaseModel):
    proposal_id: str
    choice_id: ReviewChoiceId
    status: Literal["degraded_unavailable", "requires_governed_apply", "runtime_only_recorded"]
    durable_writes: bool = False
    memory_writes: bool = False
    canonical_artifact_created: bool = False
    governed_route: str | None = None
    receipt_required: bool = False
    message: str


def _proposal_id(packet: SourceUnderstandingPacket, target_note_kind: StabilizedNoteKind) -> str:
    basis = "|".join(
        [
            packet.source.source_id,
            packet.source.source_ref,
            packet.scope,
            target_note_kind,
            packet.claims[0].claim if packet.claims else "",
        ]
    )
    return f"su-proposal-{sha256(basis.encode('utf-8')).hexdigest()[:16]}"


def _unique_anchors(packet: SourceUnderstandingPacket) -> list[SourceAnchor]:
    anchors: list[SourceAnchor] = []
    seen: set[tuple[str, str, int | None, int | None, str | None]] = set()
    for anchor in [packet.source] + [claim.source_anchor for claim in packet.claims] + [
        evidence.source_anchor for evidence in packet.evidence
    ]:
        key = (
            anchor.source_id,
            anchor.source_ref,
            anchor.start_line,
            anchor.end_line,
            anchor.limitation,
        )
        if key not in seen:
            anchors.append(anchor)
            seen.add(key)
    return anchors


def _draft_body(packet: SourceUnderstandingPacket) -> str:
    claims = "\n".join(f"- Source claim: {claim.claim}" for claim in packet.claims)
    evidence = "\n".join(
        f"- Evidence: {item.evidence_summary} ({item.source_anchor.source_ref})"
        for item in packet.evidence
    )
    limitations = [
        limitation
        for limitation in [packet.source.limitation, *(item.caveat for item in packet.evidence)]
        if limitation
    ]
    limitation_block = "\n".join(f"- Limitation: {item}" for item in dict.fromkeys(limitations))
    sections = [
        "Non-authoritative draft for human review.",
        claims or "- Source claim: No claim was extracted from the packet.",
        evidence or "- Evidence: No evidence item was extracted from the packet.",
    ]
    if limitation_block:
        sections.append(limitation_block)
    sections.append("Do not promote this draft without explicit governed approval.")
    return "\n\n".join(sections)


def _review_choices(apply_path: GovernedApplyPath) -> list[StabilizedNoteReviewChoice]:
    if apply_path.available:
        apply_choice = StabilizedNoteReviewChoice(
            choice_id="apply",
            label="Apply through governed stabilized-note path",
            effect="governed_mutation",
            requires_governed_mutation_path=True,
            mutates_durable_surfaces=True,
            governed_route=(
                f"{apply_path.route_name}: WriteGuard action "
                f"{apply_path.write_guard_action}; {apply_path.receipt_posture}"
            ),
        )
    else:
        apply_choice = StabilizedNoteReviewChoice(
            choice_id="apply",
            label="Apply through governed stabilized-note path",
            effect="governed_mutation",
            available=False,
            requires_governed_mutation_path=True,
            mutates_durable_surfaces=False,
            unavailable_reason=(
                "No governed stabilized-note apply path is available in this runtime slice; "
                "the proposal was staged for review only."
            ),
        )
    return [
        apply_choice,
        StabilizedNoteReviewChoice(
            choice_id="defer",
            label="Defer",
            effect="runtime_only",
            mutates_durable_surfaces=False,
        ),
        StabilizedNoteReviewChoice(
            choice_id="reject",
            label="Reject",
            effect="runtime_only",
            mutates_durable_surfaces=False,
        ),
        StabilizedNoteReviewChoice(
            choice_id="revise",
            label="Revise proposal",
            effect="runtime_only",
            mutates_durable_surfaces=False,
        ),
    ]


def stage_stabilized_note_proposal(
    packet: SourceUnderstandingPacket,
    *,
    target_note_kind: StabilizedNoteKind = "literature_note",
    apply_path: GovernedApplyPath | None = None,
) -> StabilizedNoteProposal:
    """Stage a non-authoritative stabilized-note proposal from a P0 packet.

    This is a pure handoff builder. It creates review material only and never writes a
    canonical note, relation, memory, metadata field, or receipt.
    """

    path = apply_path or GovernedApplyPath()
    anchors = _unique_anchors(packet)
    limitations = list(
        dict.fromkeys(anchor.limitation for anchor in anchors if anchor.limitation)
    )
    return StabilizedNoteProposal(
        proposal_id=_proposal_id(packet, target_note_kind),
        target_note_kind=target_note_kind,
        source=packet.source,
        packet_scope=packet.scope,
        source_anchors=anchors,
        anchor_limitations=limitations,
        packet_provenance=[
            packet.status,
            "Source Understanding P0 packet",
            "Agent interpretation remains review-required and non-authoritative.",
        ],
        draft_title=f"Stabilized note proposal: {packet.source.label}",
        draft_body=_draft_body(packet),
        review_choices=_review_choices(path),
    )


def resolve_stabilized_note_review_choice(
    proposal: StabilizedNoteProposal,
    choice_id: ReviewChoiceId,
) -> StabilizedNoteReviewResult:
    choices = {choice.choice_id: choice for choice in proposal.review_choices}
    choice = choices[choice_id]
    if choice.choice_id == "apply":
        if not choice.available:
            return StabilizedNoteReviewResult(
                proposal_id=proposal.proposal_id,
                choice_id=choice_id,
                status="degraded_unavailable",
                message=choice.unavailable_reason
                or "Apply is unavailable; no canonical artifact was promoted.",
            )
        return StabilizedNoteReviewResult(
            proposal_id=proposal.proposal_id,
            choice_id=choice_id,
            status="requires_governed_apply",
            governed_route=choice.governed_route,
            receipt_required=True,
            message=(
                "Apply requires the governed mutation path before any canonical "
                "stabilized note can be created."
            ),
        )
    return StabilizedNoteReviewResult(
        proposal_id=proposal.proposal_id,
        choice_id=choice_id,
        status="runtime_only_recorded",
        message=f"{choice.label} selected for the review surface only; no durable artifact changed.",
    )


__all__ = [
    "GovernedApplyPath",
    "StabilizedNoteProposal",
    "StabilizedNoteReviewChoice",
    "StabilizedNoteReviewResult",
    "stage_stabilized_note_proposal",
    "resolve_stabilized_note_review_choice",
]
