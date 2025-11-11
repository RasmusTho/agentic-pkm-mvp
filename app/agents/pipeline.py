from __future__ import annotations

from typing import Any, Dict, List

from app.ingest.chunk_policy import split_into_chunks
from app.ingest.deduper import Deduper

_deduper = Deduper()


def ingest_and_chunk(obj: Dict[str, Any]) -> List[Dict[str, Any]]:
    text = obj.get("text", "")
    chunks = split_into_chunks(text)
    out: List[Dict[str, Any]] = []
    for idx, chunk in enumerate(chunks):
        if _deduper.is_dup(chunk, obj.get("uuid", "")):
            out.append({"kind": "duplicate", "index": idx})
        else:
            out.append({"kind": "chunk", "index": idx, "text": chunk})
    return out
