from __future__ import annotations
from typing import Dict, List, Optional


def split_into_chunks(text: str, max_chars: int = 3000) -> List[str]:
    out: List[str] = []
    cur = ""
    for line in text.splitlines(keepends=True):
        if len(cur) + len(line) > max_chars and cur:
            out.append(cur)
            cur = line
        else:
            cur += line
    if cur:
        out.append(cur)
    return out


def build_chunks(
    text: str,
    *,
    max_chars: int = 3000,
    segments: Optional[List[Dict[str, str]]] = None,
) -> List[Dict[str, str]]:
    if segments:
        return _chunks_from_segments(segments, max_chars=max_chars)
    return [{"text": chunk} for chunk in split_into_chunks(text, max_chars=max_chars)]


def _chunks_from_segments(segments: List[Dict[str, str]], *, max_chars: int) -> List[Dict[str, str]]:
    records: List[Dict[str, str]] = []
    for idx, seg in enumerate(segments):
        speaker = seg.get("speaker", f"spk_{idx}")
        text = seg.get("text", "").strip()
        if not text:
            continue
        pieces = split_into_chunks(text, max_chars=max_chars)
        for piece in pieces:
            records.append({"text": piece, "speaker": speaker, "segment_index": idx})
    return records


__all__ = ["split_into_chunks", "build_chunks"]
