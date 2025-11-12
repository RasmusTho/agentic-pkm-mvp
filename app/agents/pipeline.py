from __future__ import annotations

import os
from typing import Any, Dict, List, Set

from app.agents.base.audit import audit_log
from app.ingest.chunk_policy import build_chunks
from app.ingest.deduper import Deduper

_deduper = Deduper()
_AGENT = "ingest-pipeline"


def ingest_and_chunk(obj: Dict[str, Any]) -> List[Dict[str, Any]]:
    text = obj.get("text", "")
    segments = obj.get("segments") if _diarization_enabled() else None
    chunk_records = build_chunks(text, segments=segments)
    out: List[Dict[str, Any]] = []
    speakers: Set[str] = set()
    for idx, record in enumerate(chunk_records):
        chunk_text = record.get("text", "")
        if _deduper.is_dup(chunk_text, obj.get("uuid", "")):
            out.append({"kind": "duplicate", "index": idx})
        else:
            chunk_payload: Dict[str, Any] = {"kind": "chunk", "index": idx, "text": chunk_text}
            if speaker := record.get("speaker"):
                chunk_payload["speaker"] = speaker
                speakers.add(speaker)
            if "start" in record:
                chunk_payload["start"] = record["start"]
            if "end" in record:
                chunk_payload["end"] = record["end"]
            if "speaker_segments" in record:
                chunk_payload["speaker_segments"] = record["speaker_segments"]
            out.append(chunk_payload)
    _audit_chunk_creation(
        object_id=str(obj.get("uuid") or ""),
        trace_id=obj.get("trace_id"),
        chunks=len([entry for entry in out if entry.get("kind") == "chunk"]),
        speaker_count=len(speakers) if _diarization_enabled() and speakers else None,
    )
    return out


def _diarization_enabled() -> bool:
    return os.getenv("DIARIZE_ENABLE", "").strip().lower() in {"1", "true", "yes", "on"}


def _audit_chunk_creation(
    *,
    object_id: str | None,
    trace_id: str | None,
    chunks: int,
    speaker_count: int | None,
) -> None:
    if not object_id:
        return
    details: Dict[str, Any] = {"chunks": chunks}
    if speaker_count is not None:
        details["speaker_count"] = speaker_count
    audit_log(
        object_id=object_id,
        agent=_AGENT,
        action="text.chunk.created",
        trace_id=trace_id,
        details=details,
    )
