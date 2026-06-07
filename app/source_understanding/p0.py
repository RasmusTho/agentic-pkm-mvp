from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field


class SourceAnchor(BaseModel):
    source_id: str
    source_ref: str
    label: str
    start_line: int | None = None
    end_line: int | None = None
    limitation: str | None = None


class SourceUnderstandingRequest(BaseModel):
    source_id: str = Field(min_length=1)
    source_ref: str = Field(min_length=1)
    title: str = Field(min_length=1)
    text: str = Field(min_length=1)
    scope: Literal["whole_document", "selected_passage"] = "selected_passage"
    selection_start_line: int | None = None
    selection_end_line: int | None = None


class SourceUnderstandingClaim(BaseModel):
    claim: str
    centrality: Literal["primary", "supporting"]
    source_anchor: SourceAnchor
    agent_interpretation: str
    review_needed: bool = True


class SourceUnderstandingEvidence(BaseModel):
    claim: str
    evidence_type: Literal["source_text", "source_structure", "anchor_limitation"]
    evidence_summary: str
    source_anchor: SourceAnchor
    strength: Literal["direct", "limited"] = "direct"
    caveat: str | None = None


class SourceUnderstandingPacket(BaseModel):
    packet_title: str = "Source Understanding Packet"
    scope: Literal["whole_document", "selected_passage"]
    source: SourceAnchor
    status: str = "non-authoritative understanding projection"
    orientation: list[str]
    structure: list[str]
    claims: list[SourceUnderstandingClaim]
    evidence: list[SourceUnderstandingEvidence]
    review_posture: list[str]
    possible_next_steps: list[str]
    mutation_intents: list[str] = Field(default_factory=list)
    durable_writes: bool = False
    memory_writes: bool = False


_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


def _clean_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _sentences(text: str) -> list[str]:
    compact = " ".join(_clean_lines(text))
    return [part.strip() for part in _SENTENCE_RE.split(compact) if part.strip()]


def _source_anchor(request: SourceUnderstandingRequest, *, limitation: str | None = None) -> SourceAnchor:
    return SourceAnchor(
        source_id=request.source_id,
        source_ref=request.source_ref,
        label=request.title,
        start_line=request.selection_start_line,
        end_line=request.selection_end_line,
        limitation=limitation,
    )


def _anchor_limitation(request: SourceUnderstandingRequest) -> str | None:
    if request.scope == "selected_passage":
        if request.selection_start_line is None or request.selection_end_line is None:
            return "Selection text is available, but exact source line anchors were not supplied."
        return "Selected-passage scope only; this packet must not claim whole-document coverage."
    if request.selection_start_line is None and request.selection_end_line is None:
        return "Whole-document source reference supplied without claim-level line anchors."
    return None


def _structure(lines: list[str], request: SourceUnderstandingRequest) -> list[str]:
    if not lines:
        return ["No source structure could be extracted from the supplied text."]
    headings = [line for line in lines if line.startswith("#")]
    if headings:
        return [f"Source section marker: {line.lstrip('#').strip()}" for line in headings[:4]]
    if request.scope == "selected_passage":
        return [f"Selected passage contains {len(lines)} non-empty line(s)."]
    return [f"Source document contains {len(lines)} non-empty line(s) in the supplied excerpt."]


def _claim_candidates(sentences: list[str]) -> list[str]:
    markers = ("must", "should", "is ", "are ", "requires", "preserves", "distinguishes")
    candidates = [sentence for sentence in sentences if any(marker in sentence.lower() for marker in markers)]
    return (candidates or sentences)[:3]


def build_source_understanding_packet(request: SourceUnderstandingRequest) -> SourceUnderstandingPacket:
    """Build the P0 source-understanding packet for one supplied source/selection.

    This is a deterministic, read-only projection seam. It preserves source identity,
    reports anchor limitations honestly, and does not call write, memory, index, or
    promotion paths.
    """

    lines = _clean_lines(request.text)
    sentences = _sentences(request.text)
    limitation = _anchor_limitation(request)
    anchor = _source_anchor(request, limitation=limitation)
    scope_label = "selected passage" if request.scope == "selected_passage" else "whole document"
    claim_texts = _claim_candidates(sentences)
    claims = [
        SourceUnderstandingClaim(
            claim=claim,
            centrality="primary" if index == 0 else "supporting",
            source_anchor=anchor,
            agent_interpretation=(
                "Agent interpretation: this appears to be a source claim in the supplied "
                f"{scope_label}; verify against the source before stabilizing it."
            ),
            review_needed=True,
        )
        for index, claim in enumerate(claim_texts)
    ]
    evidence = [
        SourceUnderstandingEvidence(
            claim=claim.claim,
            evidence_type="source_text" if not limitation else "anchor_limitation",
            evidence_summary=f"Evidence is drawn from the supplied {scope_label}, not from hidden context.",
            source_anchor=anchor,
            strength="limited" if limitation else "direct",
            caveat=limitation,
        )
        for claim in claims
    ]
    return SourceUnderstandingPacket(
        scope=request.scope,
        source=anchor,
        orientation=[
            f"This packet orients to {request.title} as a {scope_label}.",
            "It separates source content from agent interpretation and keeps human review required.",
        ],
        structure=_structure(lines, request),
        claims=claims,
        evidence=evidence,
        review_posture=[
            "Well-supported items still require source review before becoming stabilized notes.",
            "Agent interpretation is explicitly non-authoritative.",
            "No canonical artifact, relation, task, commitment, or hidden memory was written.",
            limitation or "Source identity is present; claim-level review remains required.",
        ],
        possible_next_steps=[
            "Create stabilized literature-note proposal through a later governed handoff.",
            "Defer.",
            "Ask for Concept/Critique/Integration/Action follow-up later.",
        ],
    )


__all__ = [
    "SourceAnchor",
    "SourceUnderstandingRequest",
    "SourceUnderstandingPacket",
    "build_source_understanding_packet",
]
