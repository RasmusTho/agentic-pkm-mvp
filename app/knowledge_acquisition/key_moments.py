"""Timestamp-only key-moment selection for YouTube Source Note v2 (YSNV2-09, #4116).

Moments are derived solely from durable, source-bound evidence already on the machine side:
the persisted normalized transcript (segments and chapters) and, when present, the persisted
``claims`` extraction.  Candidate generation is generous (every transcript segment is a
candidate); selection is bounded by a source-duration budget, a minimum-gap diversity rule, and
evidence relevance (claim or chapter support), so the timeline is never sampled evenly.

This stage performs no media acquisition, network access, or file write.  Each moment is a
timestamp link plus transcript anchors, rationale, and lineage; it carries no frame field or
placeholder.  Frame capture (YSNV2-11, #4118) is a separate stage that may later reference a
moment by its stable ``moment_id``; its absence or failure leaves these moments unchanged.

The result is persisted as a rebuildable, derived ObjectStore projection whose identity derives
from its ancestors, so an unchanged rebuild resolves to the same artifact.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence
from uuid import NAMESPACE_URL, uuid5

from app.knowledge_acquisition.evidence_synthesis import (
    system_language_for,
    validate_generated_language,
    validate_resolvable_anchor,
)
from app.knowledge_acquisition.extraction_persistence import (
    ExtractionPersistenceError,
    PersistedExtraction,
    PersistedTranscript,
    _create_immutable,
    _metadata_bundle,
    _parse_iso,
)
from app.knowledge_acquisition.raw_record import raw_record_object_id

KEY_MOMENTS_ARTIFACT_KIND = "knowledge_acquisition.key_moments"
KEY_MOMENTS_STAGE = "select_key_moments"
KEY_MOMENTS_STAGE_VERSION = 1
OUTPUT_MODE = "timestamp_only"
# Mirrors ``youtube_plugin.SOURCE_KIND`` without importing the media-capable plugin module.
_YOUTUBE_SOURCE_KIND = "youtube_url"

# Budget: roughly one moment per four minutes of source, bounded to [1, 12].
_SECONDS_PER_MOMENT = 240.0
_MAX_MOMENTS = 12
# Diversity: selected moments are at least duration / (2 * budget) apart, never under 15s.
_MIN_GAP_FLOOR_SECONDS = 15.0
_CLAIM_WEIGHT = 2
_CHAPTER_WEIGHT = 1
_SAFE_ITEM_REF = re.compile(r"[A-Za-z0-9_-]{1,128}")

_RATIONALE = {
    "en": {
        "both": "This moment opens a chapter and anchors {claims}.",
        "chapter": "This moment opens a chapter in the source structure.",
        "claims": "This moment anchors {claims} from the transcript.",
        "one": "one retained claim",
        "many": "{n} retained claims",
    },
    "sv": {
        "both": "Detta ögonblick inleder ett kapitel och förankrar {claims}.",
        "chapter": "Detta ögonblick inleder ett kapitel i källans struktur.",
        "claims": "Detta ögonblick förankrar {claims} från transkriptionen.",
        "one": "ett behållet påstående",
        "many": "{n} behållna påståenden",
    },
}


class KeyMomentsError(RuntimeError):
    """Key-moment selection received inconsistent lineage or could not persist."""


@dataclass(frozen=True)
class PersistedKeyMoments:
    object_id: str
    status: str
    output_mode: str
    rationale_language: str
    moments: tuple[dict[str, Any], ...]
    budget: dict[str, Any]
    candidate_count: int
    rejected: dict[str, int]
    dropped: tuple[str, ...]
    metadata_bundle: dict[str, Any]


def derive_key_moments(
    *,
    transcript: PersistedTranscript,
    item_ref: str,
    claims_extraction: PersistedExtraction | None = None,
) -> PersistedKeyMoments:
    """Select and persist timestamp-only moments from durable transcript/claims evidence."""

    if not isinstance(item_ref, str) or not _SAFE_ITEM_REF.fullmatch(item_ref):
        raise KeyMomentsError("key moments require a safe stable YouTube item_ref")
    expected_raw_id = raw_record_object_id(
        source_kind=_YOUTUBE_SOURCE_KIND, item_ref=item_ref, content_identity=transcript.content_identity
    )
    if str(expected_raw_id) != transcript.raw_record_id:
        raise KeyMomentsError("item_ref does not identify this transcript's raw source record")
    derived_from = [transcript.raw_record_id, transcript.object_id]
    if claims_extraction is not None:
        if (
            claims_extraction.result.extractor_id != "claims"
            or claims_extraction.raw_record_id != transcript.raw_record_id
            or claims_extraction.normalized_artifact_id != transcript.object_id
            or claims_extraction.result.source_content_identity != transcript.content_identity
        ):
            raise KeyMomentsError("claims extraction does not descend from this transcript")
        derived_from.append(claims_extraction.object_id)

    segments = _segments(transcript)
    language = system_language_for(transcript.extensions.get("language"))
    duration = max((float(seg["end"]) for seg in segments), default=0.0)
    budget = _budget(duration)
    dropped: list[str] = []

    # Generous candidate generation: one candidate per transcript segment, carrying any
    # chapter-structure and claim evidence that resolves to that segment.  A moment's
    # timestamp is its anchoring segment's start, so the link always lands on cited evidence.
    candidates: dict[int, dict[str, Any]] = {
        index: {"index": index, "time": float(seg["start"]), "chapters": [], "claims": [], "anchors": {}}
        for index, seg in enumerate(segments)
    }
    for chapter in transcript.extensions.get("chapters") or ():
        index = _chapter_segment(chapter, segments)
        if index is None:
            dropped.append("chapter_anchor_unresolvable")
            continue
        if not str(chapter.get("title") or "").strip():
            dropped.append("chapter_title_missing")
            continue
        candidate = candidates[index]
        candidate["chapters"].append(str(chapter["title"]))
        _add_anchor(candidate, index, segments)
    claims = (claims_extraction.result.output.get("claims") if claims_extraction else None) or ()
    for claim in claims:
        anchors = claim.get("anchors") if isinstance(claim, Mapping) else None
        wording = claim.get("source_wording") if isinstance(claim, Mapping) else None
        if (
            not isinstance(wording, str)
            or not wording.strip()
            or not isinstance(anchors, list)
            or not anchors
            or not all(isinstance(a, Mapping) and validate_resolvable_anchor(a, segments) for a in anchors)
        ):
            dropped.append("claim_anchor_unresolvable")
            continue
        first = min(anchors, key=lambda a: float(a["start"]))
        candidate = candidates[int(first["segment_index"])]
        candidate["claims"].append(wording)
        for anchor in anchors:
            _add_anchor(candidate, int(anchor["segment_index"]), segments)

    rejected = {"unsupported": 0, "diversity": 0, "budget": 0}
    supported: list[dict[str, Any]] = []
    for candidate in candidates.values():
        score = _CLAIM_WEIGHT * len(candidate["claims"]) + _CHAPTER_WEIGHT * len(candidate["chapters"])
        if score == 0:
            rejected["unsupported"] += 1
        else:
            supported.append({**candidate, "score": score})

    selected: list[dict[str, Any]] = []
    for candidate in sorted(supported, key=lambda c: (-c["score"], c["time"], c["index"])):
        # Diversity suppression takes precedence over the budget in the rejection counts.
        if any(abs(candidate["time"] - other["time"]) < budget["min_gap_seconds"] for other in selected):
            rejected["diversity"] += 1
        elif len(selected) >= budget["max_moments"]:
            rejected["budget"] += 1
        else:
            selected.append(candidate)
    selected.sort(key=lambda c: (c["time"], c["index"]))

    moments = tuple(
        _moment(candidate, transcript=transcript, item_ref=item_ref, language=language, derived_from=derived_from)
        for candidate in selected
    )
    status = OUTPUT_MODE if moments else "no_supported_moments"
    object_id = str(
        uuid5(
            NAMESPACE_URL,
            "urn:knowledge-acquisition:key-moments:"
            + ":".join([*derived_from, item_ref, str(KEY_MOMENTS_STAGE_VERSION)]),
        )
    )
    extensions: dict[str, Any] = {
        "artifact_kind": "key_moments",
        "raw_record_id": transcript.raw_record_id,
        "normalized_artifact_id": transcript.object_id,
        "claims_artifact_id": claims_extraction.object_id if claims_extraction else None,
        "content_identity": transcript.content_identity,
        "item_ref": item_ref,
        "stage": KEY_MOMENTS_STAGE,
        "stage_version": KEY_MOMENTS_STAGE_VERSION,
        "status": status,
        "output_mode": OUTPUT_MODE,
        "rationale_language": language,
        "budget": budget,
        "candidate_count": len(candidates),
        "rejected": rejected,
        "dropped": dropped,
        "moments": [dict(moment) for moment in moments],
    }
    ancestor = transcript.metadata_bundle
    try:
        created_at = _parse_iso(str(ancestor["created_at"]))
        payload = _metadata_bundle(
            object_id=object_id,
            raw_record={
                "episode_ref": ancestor.get("episode_ref", "unbound"),
                "scope_id": ancestor.get("scope_id"),
                "sensitivity": ancestor.get("sensitivity", "internal"),
            },
            created_by=f"app:knowledge_acquisition.{KEY_MOMENTS_STAGE}",
            created_at=created_at,
            derived_from=derived_from,
            provenance_event_ids=(
                *tuple(ancestor.get("provenance_event_ids") or ()),
                f"{KEY_MOMENTS_STAGE}:{KEY_MOMENTS_STAGE_VERSION}:{transcript.content_identity}:{object_id}",
            ),
            extensions=extensions,
        )
        stored, _created = _create_immutable(
            object_id=object_id,
            kind=KEY_MOMENTS_ARTIFACT_KIND,
            payload=payload,
            source_ref=f"normalized:{transcript.object_id}",
            created_at=created_at,
        )
    except (ExtractionPersistenceError, KeyError, ValueError) as exc:
        raise KeyMomentsError(f"key moments {object_id} could not be persisted") from exc
    ext = stored["extensions"]
    return PersistedKeyMoments(
        object_id=object_id,
        status=str(ext["status"]),
        output_mode=str(ext["output_mode"]),
        rationale_language=str(ext["rationale_language"]),
        moments=tuple(dict(moment) for moment in ext["moments"]),
        budget=dict(ext["budget"]),
        candidate_count=int(ext["candidate_count"]),
        rejected=dict(ext["rejected"]),
        dropped=tuple(ext["dropped"]),
        metadata_bundle=dict(stored),
    )


def _segments(transcript: PersistedTranscript) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    for segment in transcript.extensions.get("segments") or ():
        if not isinstance(segment, Mapping):
            raise KeyMomentsError("persisted transcript segment is malformed")
        start, end = segment.get("start"), segment.get("end")
        if (
            isinstance(start, bool)
            or isinstance(end, bool)
            or not isinstance(start, (int, float))
            or not isinstance(end, (int, float))
            or not math.isfinite(float(start))
            or not math.isfinite(float(end))
            or start < 0
            or end < start
            or not segment.get("anchor")
        ):
            raise KeyMomentsError("persisted transcript segment lacks finite anchored time")
        segments.append(dict(segment))
    return segments


def _budget(duration: float) -> dict[str, Any]:
    if duration <= 0:
        return {"duration_seconds": 0.0, "max_moments": 0, "min_gap_seconds": _MIN_GAP_FLOOR_SECONDS}
    max_moments = max(1, min(_MAX_MOMENTS, math.ceil(duration / _SECONDS_PER_MOMENT)))
    min_gap = max(_MIN_GAP_FLOOR_SECONDS, duration / (2 * max_moments))
    return {"duration_seconds": duration, "max_moments": max_moments, "min_gap_seconds": min_gap}


def _chapter_segment(chapter: object, segments: Sequence[Mapping[str, Any]]) -> int | None:
    if not isinstance(chapter, Mapping):
        return None
    start = chapter.get("start_time")
    if isinstance(start, bool) or not isinstance(start, (int, float)) or not math.isfinite(float(start)) or start < 0:
        return None
    for index, segment in enumerate(segments):
        if float(segment["start"]) <= start < float(segment["end"]) or float(segment["start"]) >= start:
            return index
    return None


def _add_anchor(candidate: dict[str, Any], index: int, segments: Sequence[Mapping[str, Any]]) -> None:
    segment = segments[index]
    candidate["anchors"][index] = {
        "segment_index": index,
        "start": float(segment["start"]),
        "end": float(segment["end"]),
        "anchor": str(segment["anchor"]),
    }


def _moment(
    candidate: Mapping[str, Any],
    *,
    transcript: PersistedTranscript,
    item_ref: str,
    language: str,
    derived_from: Sequence[str],
) -> dict[str, Any]:
    seconds = int(math.floor(candidate["time"]))
    rationale = _rationale(language, chapters=len(candidate["chapters"]), claims=len(candidate["claims"]))
    evidence = [{"kind": "chapter", "source_wording": title} for title in candidate["chapters"]]
    evidence += [{"kind": "claim", "source_wording": wording} for wording in candidate["claims"]]
    return {
        "moment_id": str(
            uuid5(
                NAMESPACE_URL,
                f"urn:knowledge-acquisition:key-moment:{transcript.content_identity}:"
                f"{KEY_MOMENTS_STAGE_VERSION}:{candidate['index']}:{seconds}",
            )
        ),
        "timestamp_seconds": seconds,
        "timestamp_link": f"https://www.youtube.com/watch?v={item_ref}&t={seconds}s",
        "transcript_anchors": [candidate["anchors"][key] for key in sorted(candidate["anchors"])],
        "evidence": evidence,
        "selection_rationale": rationale,
        "rationale_language": language,
        "score": candidate["score"],
        "content_identity": transcript.content_identity,
        "stage": KEY_MOMENTS_STAGE,
        "stage_version": KEY_MOMENTS_STAGE_VERSION,
        "derived_from": list(derived_from),
    }


def _rationale(language: str, *, chapters: int, claims: int) -> str:
    """D6: system rationale is Swedish only for Swedish-original sources, else English."""

    phrases = _RATIONALE[language]
    claim_phrase = phrases["one"] if claims == 1 else phrases["many"].format(n=claims)
    if chapters and claims:
        text = phrases["both"].format(claims=claim_phrase)
    elif chapters:
        text = phrases["chapter"]
    else:
        text = phrases["claims"].format(claims=claim_phrase)
    if not validate_generated_language(text, language):
        raise KeyMomentsError(f"moment rationale failed the D6 language gate for {language!r}")
    return text


__all__ = [
    "KEY_MOMENTS_ARTIFACT_KIND",
    "KEY_MOMENTS_STAGE",
    "KEY_MOMENTS_STAGE_VERSION",
    "KeyMomentsError",
    "PersistedKeyMoments",
    "derive_key_moments",
]
