from __future__ import annotations

import os
from typing import Any, Dict, List

from app.ingest.chunk_policy import build_chunks
from app.ingest.deduper import Deduper

_deduper = Deduper()


def ingest_and_chunk(obj: Dict[str, Any]) -> List[Dict[str, Any]]:
    text = obj.get("text", "")
    segments = obj.get("segments") if _diarization_enabled() else None
    chunk_records = build_chunks(text, segments=segments)
    out: List[Dict[str, Any]] = []
    for idx, record in enumerate(chunk_records):
        chunk_text = record.get("text", "")
        if _deduper.is_dup(chunk_text, obj.get("uuid", "")):
            out.append({"kind": "duplicate", "index": idx})
        else:
            chunk_payload = {"kind": "chunk", "index": idx, "text": chunk_text}
            if "speaker" in record:
                chunk_payload["speaker"] = record["speaker"]
            out.append(chunk_payload)
    return out


def _diarization_enabled() -> bool:
    return os.getenv("DIARIZE_ENABLE", "").strip().lower() in {"1", "true", "yes", "on"}
