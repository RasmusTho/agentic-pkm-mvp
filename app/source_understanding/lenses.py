from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from app.source_understanding.p0 import SourceAnchor, SourceUnderstandingPacket


ConceptPosture = Literal["source_defined", "agent_clarified"]
CritiquePosture = Literal["source_stated_limit", "agent_inferred_review_item"]

_SOURCE_DEFINITION_RE = re.compile(
    r"^(?P<term>[A-Z][A-Za-z0-9 /_-]{2,80}?)\s+"
    r"(?P<verb>is|are|means|refers to|describes)\s+(?P<body>.+)$"
)
_SOURCE_LIMIT_MARKERS = (
    "limitation",
    "limited",
    "uncertain",
    "uncertainty",
    "missing evidence",
    "does not address",
    "out of scope",
    "cannot show",
)
_AGENT_CONCERN_MARKERS = (
    "must",
    "should",
    "requires",
    "depends",
    "assumes",
    "needs",
    "review",
)


def _term_parts(term: str) -> set[str]:
    return {
        part.casefold()
        for part in re.findall(r"[A-Za-z0-9]+", term)
        if part
    }


class SourceUnderstandingConcept(BaseModel):
    term: str
    posture: ConceptPosture
    source_anchor: SourceAnchor
    source_excerpt: str | None = None
    agent_clarification: str | None = None
    anchor_limitation: str | None = None
    review_needed: bool = True


class SourceUnderstandingCritiqueItem(BaseModel):
    statement: str
    posture: CritiquePosture
    source_anchor: SourceAnchor
    source_excerpt: str | None = None
    agent_interpretation: str | None = None
    anchor_limitation: str | None = None
    review_needed: bool = True
    settled_defect: bool = False


class SourceUnderstandingConceptCritiqueLenses(BaseModel):
    lens_title: str = "Source Understanding Concept/Critique Lenses"
    status: str = "non-authoritative source-bounded lens projection"
    scope: str
    source: SourceAnchor
    concepts: list[SourceUnderstandingConcept]
    critique: list[SourceUnderstandingCritiqueItem]
    review_posture: list[str]
    durable_writes: bool = False
    memory_writes: bool = False
    canonical_artifact_created: bool = False
    mutation_intents: list[str] = Field(default_factory=list)


def _definition_concepts(packet: SourceUnderstandingPacket) -> list[SourceUnderstandingConcept]:
    concepts: list[SourceUnderstandingConcept] = []
    for claim in packet.claims:
        match = _SOURCE_DEFINITION_RE.match(claim.claim.strip())
        if not match:
            continue
        term = match.group("term").strip()
        if "limitation" in term.casefold():
            continue
        concepts.append(
            SourceUnderstandingConcept(
                term=term,
                posture="source_defined",
                source_anchor=claim.source_anchor,
                source_excerpt=claim.claim,
                anchor_limitation=claim.source_anchor.limitation,
            )
        )
    return concepts


def _agent_clarified_concepts(packet: SourceUnderstandingPacket) -> list[SourceUnderstandingConcept]:
    concepts: list[SourceUnderstandingConcept] = []
    seen: set[str] = set()
    for concept in _definition_concepts(packet):
        seen.add(concept.term.casefold())
        seen.update(_term_parts(concept.term))
    for claim in packet.claims:
        words = [word.strip(".,:;()[]") for word in claim.claim.split()]
        candidates = [
            word
            for word in words
            if len(word) > 5 and word[0].isalpha() and word.casefold() not in seen
        ]
        if not candidates:
            continue
        term = candidates[0]
        concepts.append(
            SourceUnderstandingConcept(
                term=term,
                posture="agent_clarified",
                source_anchor=claim.source_anchor,
                source_excerpt=None,
                agent_clarification=(
                    f"Agent clarification candidate from source claim: verify what {term!r} "
                    "means in the source before using it as a concept."
                ),
                anchor_limitation=claim.source_anchor.limitation,
            )
        )
        seen.add(term.casefold())
        if len(concepts) >= 3:
            break
    return concepts


def _concepts(packet: SourceUnderstandingPacket) -> list[SourceUnderstandingConcept]:
    defined = _definition_concepts(packet)
    clarified = _agent_clarified_concepts(packet)
    if defined or clarified:
        return [*defined, *clarified]
    return [
        SourceUnderstandingConcept(
            term=packet.source.label,
            posture="agent_clarified",
            source_anchor=packet.source,
            agent_clarification=(
                "No source-defined term pattern was available; treat this as a review prompt, "
                "not a source concept."
            ),
            anchor_limitation=packet.source.limitation,
        )
    ]


def _source_stated_limits(packet: SourceUnderstandingPacket) -> list[SourceUnderstandingCritiqueItem]:
    items: list[SourceUnderstandingCritiqueItem] = []
    for claim in packet.claims:
        lower = claim.claim.lower()
        if any(marker in lower for marker in _SOURCE_LIMIT_MARKERS):
            items.append(
                SourceUnderstandingCritiqueItem(
                    statement=claim.claim,
                    posture="source_stated_limit",
                    source_anchor=claim.source_anchor,
                    source_excerpt=claim.claim,
                    anchor_limitation=claim.source_anchor.limitation,
                )
            )
    for evidence in packet.evidence:
        if evidence.caveat:
            items.append(
                SourceUnderstandingCritiqueItem(
                    statement=evidence.caveat,
                    posture="source_stated_limit",
                    source_anchor=evidence.source_anchor,
                    source_excerpt=evidence.caveat,
                    anchor_limitation=evidence.source_anchor.limitation,
                )
            )
    return items


def _agent_inferred_concerns(packet: SourceUnderstandingPacket) -> list[SourceUnderstandingCritiqueItem]:
    items: list[SourceUnderstandingCritiqueItem] = []
    for claim in packet.claims:
        lower = claim.claim.lower()
        if not any(marker in lower for marker in _AGENT_CONCERN_MARKERS):
            continue
        items.append(
            SourceUnderstandingCritiqueItem(
                statement=f"Review whether this claim is adequately supported: {claim.claim}",
                posture="agent_inferred_review_item",
                source_anchor=claim.source_anchor,
                agent_interpretation=(
                    "Agent-inferred concern only; this is a review prompt, not a settled source defect."
                ),
                anchor_limitation=claim.source_anchor.limitation,
            )
        )
        if len(items) >= 3:
            break
    if not items:
        items.append(
            SourceUnderstandingCritiqueItem(
                statement="Review source support before treating this packet as stabilized understanding.",
                posture="agent_inferred_review_item",
                source_anchor=packet.source,
                agent_interpretation=(
                    "General review-needed concern produced because no explicit critique marker was present."
                ),
                anchor_limitation=packet.source.limitation,
            )
        )
    return items


def build_concept_critique_lenses(
    packet: SourceUnderstandingPacket,
) -> SourceUnderstandingConceptCritiqueLenses:
    """Build source-bounded Concept and Critique lenses from a P0 packet.

    The lenses are semantic projections for review. They do not call retrieval,
    memory, event, vault, or write paths, and they never promote concepts or critique
    items into canonical artifacts.
    """

    scope_label = "selected passage" if packet.scope == "selected_passage" else "whole document"
    return SourceUnderstandingConceptCritiqueLenses(
        scope=packet.scope,
        source=packet.source,
        concepts=_concepts(packet),
        critique=[*_source_stated_limits(packet), *_agent_inferred_concerns(packet)],
        review_posture=[
            f"Concept and Critique lenses are bounded to the supplied {scope_label}.",
            "Source-defined concepts use source excerpts; agent-clarified concepts remain review prompts.",
            "Critique items are review-needed and must not be treated as settled defects.",
            "No canonical concept note, literature note, relation, metadata, or memory was written.",
            packet.source.limitation or "Source identity is present; source-level review remains required.",
        ],
    )


__all__ = [
    "SourceUnderstandingConcept",
    "SourceUnderstandingConceptCritiqueLenses",
    "SourceUnderstandingCritiqueItem",
    "build_concept_critique_lenses",
]
