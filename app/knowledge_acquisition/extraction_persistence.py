"""Durable, rebuildable transcript and extraction artifacts for YSNV2-04.

The immutable ``raw`` ObjectStore record remains replay authority.  This module stores
normalized transcripts and extractor outputs through the same PDM-owned ObjectStore/StorePort
seam as raw acquisition, but classifies them as derived projections.  A replay may replace an
equivalent normalized projection and append a new extraction run; it never consumes either as
its source.

Every payload is also a schema-valid ``MetadataBundle``.  Pipeline-specific fields live under
the contract's explicit ``extensions`` object, so persistence does not invent a second metadata
shape or leak store mechanics into HKA/SIP semantics.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence
from uuid import NAMESPACE_URL, uuid4, uuid5

from app.knowledge_acquisition.extraction_registry import ExtractionResult
from app.knowledge_acquisition.normalize import NormalizedTranscript
from app.objects import DomainObject, ObjectStore

NORMALIZED_ARTIFACT_KIND = "knowledge_acquisition.normalized_transcript"
EXTRACTION_ARTIFACT_KIND = "knowledge_acquisition.extraction"
_DEFAULT_SCOPE_ID = "scope:external/unresolved"
_SENSITIVITY_VALUES = frozenset({"public", "internal", "private", "secret"})


class ExtractionPersistenceError(RuntimeError):
    """A durable derived artifact was absent, malformed, or could not be persisted."""


@dataclass(frozen=True)
class PersistedTranscript:
    object_id: str
    raw_record_id: str
    content_identity: str
    stage_version: int
    derived_from: tuple[str, ...]
    extensions: dict[str, Any]
    metadata_bundle: dict[str, Any]

    @property
    def anchors(self) -> tuple[str, ...]:
        return tuple(
            str(segment["anchor"])
            for segment in self.extensions.get("segments", ())
            if isinstance(segment, Mapping) and segment.get("anchor")
        )


@dataclass(frozen=True)
class PersistedExtraction:
    object_id: str
    raw_record_id: str
    normalized_artifact_id: str
    input_anchors: tuple[str, ...]
    result: ExtractionResult
    metadata_bundle: dict[str, Any]


def transcript_artifact_id(
    *, raw_record_id: str, content_identity: str, stage_version: int
) -> str:
    return str(
        uuid5(
            NAMESPACE_URL,
            "urn:knowledge-acquisition:normalized:"
            f"{raw_record_id}:{content_identity}:{stage_version}",
        )
    )


def segment_anchor(*, start: float, end: float, index: int) -> str:
    """Return a stable time-derived anchor with an ordinal collision breaker."""
    if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end < start:
        raise ExtractionPersistenceError("segment anchor requires finite ordered non-negative time")
    return (
        f"t{round(start * 1000):09d}-t{round(end * 1000):09d}-s{index:04d}"
    )


def persist_normalized_transcript(
    *,
    raw_record_id: str,
    raw_record: Mapping[str, Any],
    normalized: NormalizedTranscript,
) -> PersistedTranscript:
    """Persist the deterministic normalized transcript projection.

    The object id and ``created_at`` derive from immutable raw identity/time, so an unchanged
    stage replay writes an equivalent payload to the same rebuildable object rather than
    introducing timestamp drift.
    """
    content_identity = normalized.source_content_identity
    object_id = transcript_artifact_id(
        raw_record_id=raw_record_id,
        content_identity=content_identity,
        stage_version=normalized.stage_version,
    )
    segments: list[dict[str, Any]] = []
    for index, segment in enumerate(normalized.segments):
        segments.append(
            {
                **segment.as_dict(),
                "anchor": segment_anchor(start=segment.start, end=segment.end, index=index),
            }
        )
    created_at = _raw_created_at(raw_record)
    extensions: dict[str, Any] = {
        "artifact_kind": "normalized_transcript",
        "raw_record_id": raw_record_id,
        "content_identity": content_identity,
        "stage": normalized.stage,
        "stage_version": normalized.stage_version,
        "acquisition_method": normalized.acquisition_method,
        "language": normalized.language,
        "language_detected": normalized.language_detected,
        "quality_note": normalized.quality_note,
        "chapters": [dict(chapter) for chapter in normalized.chapters],
        "segments": segments,
    }
    payload = _metadata_bundle(
        object_id=object_id,
        raw_record=raw_record,
        created_by="app:knowledge_acquisition.normalize",
        created_at=created_at,
        derived_from=(raw_record_id,),
        provenance_event_ids=(
            f"raw:{raw_record_id}",
            f"normalize:{normalized.stage_version}:{content_identity}",
        ),
        extensions=extensions,
    )
    stored_payload, _created = _create_immutable(
        object_id=object_id,
        kind=NORMALIZED_ARTIFACT_KIND,
        payload=payload,
        source_ref=f"raw:{raw_record_id}",
        created_at=created_at,
    )
    transcript = _transcript_from_payload(stored_payload)
    if (
        transcript.raw_record_id != raw_record_id
        or transcript.content_identity != content_identity
        or transcript.stage_version != normalized.stage_version
    ):
        raise ExtractionPersistenceError(
            f"normalized transcript {object_id} resolved to the wrong raw ancestor"
        )
    return transcript


def load_persisted_transcript(
    *, raw_record_id: str, content_identity: str, stage_version: int
) -> PersistedTranscript | None:
    object_id = transcript_artifact_id(
        raw_record_id=raw_record_id,
        content_identity=content_identity,
        stage_version=stage_version,
    )
    stored = ObjectStore().get_object(object_id)
    if stored is None:
        return None
    if stored.kind != NORMALIZED_ARTIFACT_KIND:
        raise ExtractionPersistenceError(
            f"normalized transcript identity {object_id} is occupied by kind {stored.kind!r}"
        )
    transcript = _transcript_from_payload(dict(stored.payload))
    if (
        transcript.raw_record_id != raw_record_id
        or transcript.content_identity != content_identity
        or transcript.stage_version != stage_version
    ):
        raise ExtractionPersistenceError(
            f"normalized transcript {object_id} resolved to the wrong raw ancestor"
        )
    return transcript


def persist_extraction_result(
    *,
    raw_record_id: str,
    normalized_artifact_id: str,
    normalized: Mapping[str, Any],
    result: ExtractionResult,
    force_reextract: bool = False,
) -> PersistedExtraction:
    """Append one immutable extraction-run artifact and return its durable identity."""
    transcript = load_persisted_transcript(
        raw_record_id=raw_record_id,
        content_identity=result.source_content_identity,
        stage_version=int(normalized.get("stage_version") or 0),
    )
    if transcript is None or transcript.object_id != normalized_artifact_id:
        raise ExtractionPersistenceError(
            "extraction persistence requires its durable normalized transcript ancestor"
        )
    object_id = (
        str(uuid4())
        if force_reextract
        else str(
            uuid5(
                NAMESPACE_URL,
                "urn:knowledge-acquisition:extraction:"
                f"{raw_record_id}:{normalized_artifact_id}:"
                f"{result.extractor_id}:{result.extractor_version}",
            )
        )
    )
    created_at = result.created_at.astimezone(timezone.utc)
    extensions: dict[str, Any] = {
        "artifact_kind": "extraction",
        "raw_record_id": raw_record_id,
        "normalized_artifact_id": normalized_artifact_id,
        "content_identity": result.source_content_identity,
        "stage": result.stage,
        "stage_version": result.extractor_version,
        "extractor_id": result.extractor_id,
        "extractor_version": result.extractor_version,
        "model_identity": dict(result.model_identity),
        "output": dict(result.output),
        "input_anchors": list(transcript.anchors),
        "extraction_run_id": object_id,
    }
    raw_record = {
        "content_identity": result.source_content_identity,
        "episode_ref": transcript.metadata_bundle.get("episode_ref", "unbound"),
        "scope_id": transcript.metadata_bundle.get("scope_id", _DEFAULT_SCOPE_ID),
        "sensitivity": transcript.metadata_bundle.get("sensitivity", "internal"),
    }
    payload = _metadata_bundle(
        object_id=object_id,
        raw_record=raw_record,
        created_by=f"app:knowledge_acquisition.extractor:{result.extractor_id}",
        created_at=created_at,
        derived_from=(raw_record_id, normalized_artifact_id),
        provenance_event_ids=(
            *tuple(transcript.metadata_bundle.get("provenance_event_ids") or ()),
            (
                f"extractor:{result.extractor_id}:{result.extractor_version}:"
                f"{result.source_content_identity}:{object_id}"
            ),
        ),
        extensions=extensions,
    )
    stored_payload, created = _create_immutable(
        object_id=object_id,
        kind=EXTRACTION_ARTIFACT_KIND,
        payload=payload,
        source_ref=f"normalized:{normalized_artifact_id}",
        created_at=created_at,
    )
    persisted = _extraction_from_payload(stored_payload, replayed=not created)
    if (
        persisted.raw_record_id != raw_record_id
        or persisted.normalized_artifact_id != normalized_artifact_id
        or persisted.result.source_content_identity != result.source_content_identity
        or persisted.result.extractor_id != result.extractor_id
        or persisted.result.extractor_version != result.extractor_version
    ):
        raise ExtractionPersistenceError(
            f"extraction artifact {object_id} resolved to the wrong durable ancestor"
        )
    return persisted


def load_latest_extraction(
    *,
    raw_record_id: str,
    content_identity: str,
    extractor_id: str,
    extractor_version: int,
) -> PersistedExtraction | None:
    """Load the newest matching immutable extraction run from the resolved ObjectStore."""
    matches: list[PersistedExtraction] = []
    for stored in ObjectStore().list_objects(
        kind=EXTRACTION_ARTIFACT_KIND, limit=None
    ):
        payload = dict(stored.payload)
        ext = payload.get("extensions")
        if not isinstance(ext, Mapping):
            continue
        if (
            ext.get("raw_record_id") == raw_record_id
            and ext.get("content_identity") == content_identity
            and ext.get("extractor_id") == extractor_id
            and ext.get("extractor_version") == extractor_version
        ):
            matches.append(_extraction_from_payload(payload, replayed=True))
    if not matches:
        return None
    return max(matches, key=lambda item: (item.result.created_at, item.object_id))


def _create_immutable(
    *,
    object_id: str,
    kind: str,
    payload: dict[str, Any],
    source_ref: str,
    created_at: datetime,
) -> tuple[dict[str, Any], bool]:
    store = ObjectStore()
    try:
        created = store.create_object_once(
            DomainObject(
                uuid=object_id,
                kind=kind,
                payload=payload,
                source_ref=source_ref,
                created_at=created_at,
            )
        )
        if created:
            return payload, True
        winner = store.get_object(object_id)
    except Exception as exc:  # noqa: BLE001 - typed persistence boundary
        raise ExtractionPersistenceError(
            f"failed to persist immutable derived artifact kind {kind!r}"
        ) from exc
    if winner is None or winner.kind != kind:
        occupied_kind = None if winner is None else winner.kind
        raise ExtractionPersistenceError(
            f"immutable artifact identity {object_id} resolved to kind {occupied_kind!r}"
        )
    return dict(winner.payload), False


def _metadata_bundle(
    *,
    object_id: str,
    raw_record: Mapping[str, Any],
    created_by: str,
    created_at: datetime,
    derived_from: Sequence[str],
    provenance_event_ids: Sequence[str],
    extensions: dict[str, Any],
) -> dict[str, Any]:
    sensitivity = raw_record.get("sensitivity")
    if sensitivity not in _SENSITIVITY_VALUES:
        sensitivity = "internal"
    episode_ref = _episode_ref(raw_record.get("episode_ref"))
    payload: dict[str, Any] = {
        "object_id": object_id,
        "object_type": "projection",
        "scope_id": str(raw_record.get("scope_id") or _DEFAULT_SCOPE_ID),
        "source_role": "external_source",
        "authority_state": "derived",
        # A transcript/extraction projection is reference material. It does not self-promote
        # to schema-level evidence standing (which would require an authority receipt).
        "evidence_role": "reference",
        "sensitivity": sensitivity,
        "suppression_state": "visible",
        "created_by": created_by,
        "created_at": _iso(created_at),
        "derived_from": [str(item) for item in derived_from],
        "content_hash": _digest(extensions),
        "provenance_event_ids": [str(item) for item in provenance_event_ids],
        "episode_ref": episode_ref,
        "extensions": extensions,
    }
    return payload


def _transcript_from_payload(payload: dict[str, Any]) -> PersistedTranscript:
    ext = payload.get("extensions")
    if not isinstance(ext, dict) or ext.get("artifact_kind") != "normalized_transcript":
        raise ExtractionPersistenceError("stored normalized transcript has malformed extensions")
    return PersistedTranscript(
        object_id=str(payload["object_id"]),
        raw_record_id=str(ext["raw_record_id"]),
        content_identity=str(ext["content_identity"]),
        stage_version=int(ext["stage_version"]),
        derived_from=tuple(str(item) for item in payload.get("derived_from") or ()),
        extensions=dict(ext),
        metadata_bundle=dict(payload),
    )


def _extraction_from_payload(
    payload: dict[str, Any], *, replayed: bool
) -> PersistedExtraction:
    ext = payload.get("extensions")
    if not isinstance(ext, dict) or ext.get("artifact_kind") != "extraction":
        raise ExtractionPersistenceError("stored extraction has malformed extensions")
    created_at = _parse_iso(str(payload["created_at"]))
    object_id = str(payload["object_id"])
    result = ExtractionResult(
        extractor_id=str(ext["extractor_id"]),
        extractor_version=int(ext["extractor_version"]),
        source_content_identity=str(ext["content_identity"]),
        output=dict(ext.get("output") or {}),
        model_identity=dict(ext.get("model_identity") or {}),
        created_at=created_at,
        replayed=replayed,
        artifact_id=object_id,
        raw_record_id=str(ext["raw_record_id"]),
        normalized_artifact_id=str(ext["normalized_artifact_id"]),
    )
    return PersistedExtraction(
        object_id=object_id,
        raw_record_id=result.raw_record_id or "",
        normalized_artifact_id=result.normalized_artifact_id or "",
        input_anchors=tuple(str(item) for item in ext.get("input_anchors") or ()),
        result=result,
        metadata_bundle=dict(payload),
    )


def _raw_created_at(raw_record: Mapping[str, Any]) -> datetime:
    value = raw_record.get("acquired_at")
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    if isinstance(value, str):
        try:
            return _parse_iso(value)
        except ValueError:
            pass
    # Legacy raw fixtures may not carry acquisition time. A fixed epoch keeps unchanged replay
    # deterministic; current persist_raw_record always supplies acquired_at.
    return datetime(1970, 1, 1, tzinfo=timezone.utc)


def _episode_ref(value: Any) -> str | list[str]:
    if isinstance(value, str) and value in {"unbound", "pending"}:
        return value
    if (
        isinstance(value, (list, tuple))
        and value
        and all(isinstance(item, str) and item for item in value)
    ):
        return list(value)
    return "unbound"


def _digest(value: Any) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return f"sha256:{hashlib.sha256(body.encode('utf-8')).hexdigest()}"


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _parse_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


__all__ = [
    "EXTRACTION_ARTIFACT_KIND",
    "NORMALIZED_ARTIFACT_KIND",
    "ExtractionPersistenceError",
    "PersistedExtraction",
    "PersistedTranscript",
    "load_latest_extraction",
    "load_persisted_transcript",
    "persist_extraction_result",
    "persist_normalized_transcript",
    "segment_anchor",
    "transcript_artifact_id",
]
