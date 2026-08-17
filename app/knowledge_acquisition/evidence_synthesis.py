"""Evidence-bound rendering helpers for YouTube source-note v2 proposals.

This module deliberately has no persistence or note-write side effects.  It turns the
structured output of the synthesis and claims extractors into renderable proposal
content only after checking that every assertion names a resolvable transcript span.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class RenderedEvidence:
    """Safe-to-render evidence proposal content and visible degradation details."""

    synthesis_sentences: tuple[str, ...]
    claims: tuple[Mapping[str, Any], ...]
    dropped: tuple[str, ...]
    coverage: float
    confidence: float
    system_language: str


def system_language_for(source_language: object) -> str:
    """D6: generated prose is Swedish only for Swedish-original sources."""

    language = str(source_language or "").strip().casefold()
    return "sv" if language == "sv" or language.startswith("sv-") else "en"


def caption_quality_confidence_cap(acquisition_method: object) -> float:
    """Return the maximum evidence confidence allowed by caption provenance."""

    method = str(acquisition_method or "").strip().casefold()
    if method == "captions_manual":
        return 1.0
    if method == "captions_auto":
        return 0.75
    if method == "asr":
        return 0.6
    return 0.5


def render_evidence_anchored(
    *,
    synthesis_sentences: Sequence[Mapping[str, Any]],
    claims: Sequence[Mapping[str, Any]],
    normalized: Mapping[str, Any],
    model_confidence: float,
) -> RenderedEvidence:
    """Drop, rather than soften, assertions without resolvable source anchors.

    The returned ``dropped`` values are deliberately visible to the caller so a
    proposal can report its degraded coverage without ever presenting uncited text
    as a source claim.
    """

    segments = normalized.get("segments")
    if not isinstance(segments, list):
        segments = []
    rendered_sentences: list[str] = []
    rendered_claims: list[Mapping[str, Any]] = []
    dropped: list[str] = []

    for sentence in synthesis_sentences:
        text = sentence.get("text") if isinstance(sentence, Mapping) else None
        if isinstance(text, str) and text.strip() and _has_resolvable_anchor(sentence, segments):
            rendered_sentences.append(text.strip())
        else:
            dropped.append("synthesis_sentence")

    for claim in claims:
        if isinstance(claim, Mapping) and _claim_is_structurally_distinct(claim) and _has_resolvable_anchor(claim, segments):
            rendered_claims.append(dict(claim))
        else:
            dropped.append("claim")

    asserted = len(synthesis_sentences) + len(claims)
    retained = len(rendered_sentences) + len(rendered_claims)
    coverage = retained / asserted if asserted else 0.0
    cap = caption_quality_confidence_cap(normalized.get("acquisition_method"))
    confidence = min(_finite_unit_interval(model_confidence), cap)
    return RenderedEvidence(
        synthesis_sentences=tuple(rendered_sentences),
        claims=tuple(rendered_claims),
        dropped=tuple(dropped),
        coverage=coverage,
        confidence=confidence,
        system_language=system_language_for(normalized.get("language")),
    )


def _has_resolvable_anchor(item: Mapping[str, Any], segments: Sequence[object]) -> bool:
    anchors = item.get("anchors")
    if not isinstance(anchors, list) or not anchors:
        return False
    for anchor in anchors:
        if not isinstance(anchor, Mapping):
            return False
        index = anchor.get("segment_index")
        if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(segments):
            return False
        segment = segments[index]
        if not isinstance(segment, Mapping):
            return False
        start, end = anchor.get("start"), anchor.get("end")
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)) or start > end:
            return False
        segment_start, segment_end = segment.get("start"), segment.get("end")
        if not isinstance(segment_start, (int, float)) or not isinstance(segment_end, (int, float)):
            return False
        if start < segment_start or end > segment_end:
            return False
    return True


def _claim_is_structurally_distinct(claim: Mapping[str, Any]) -> bool:
    source = claim.get("source_wording")
    paraphrase = claim.get("system_paraphrase")
    return (
        isinstance(source, str)
        and bool(source.strip())
        and isinstance(paraphrase, str)
        and bool(paraphrase.strip())
        and source.strip() != paraphrase.strip()
    )


def _finite_unit_interval(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    return max(0.0, min(1.0, float(value)))
