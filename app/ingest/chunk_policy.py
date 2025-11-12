from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional


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
    segments: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    if segments:
        normalized = _normalize_segments(segments)
        if normalized:
            return speaker_aware_chunks(normalized, max_chars=max_chars)
    return [{"text": chunk} for chunk in split_into_chunks(text, max_chars=max_chars)]


def speaker_aware_chunks(
    segments: Iterable[Dict[str, Any]],
    *,
    max_chars: int = 3000,
) -> List[Dict[str, Any]]:
    """
    Merge diarization segments into coherent chunks that respect speaker boundaries.
    """
    normalized = _normalize_segments(segments)
    if not normalized:
        return []
    normalized.sort(key=lambda item: (item["start"], item["segment_index"]))
    chunks: List[Dict[str, Any]] = []
    current: Dict[str, Any] | None = None

    for seg in normalized:
        text = seg["text"]
        if not text:
            continue
        sub_segments = split_segment_by_chars(seg, max_chars=max_chars)
        for sub in sub_segments:
            text = sub["text"]
            if (
                current is None
                or sub["speaker"] != current["speaker"]
                or len(current["text"]) + 1 + len(text) > max_chars
            ):
                if current:
                    chunks.append(current)
                current = {
                    "text": text,
                    "speaker": sub["speaker"],
                    "start": sub["start"],
                    "end": sub["end"],
                    "segment_start": sub["segment_index"],
                    "segment_end": sub["segment_index"],
                    "speaker_segments": 1,
                }
            else:
                current["text"] = f"{current['text'].rstrip()} {text}".strip()
                current["end"] = max(current["end"], sub["end"])
                current["segment_end"] = sub["segment_index"]
                current["speaker_segments"] += 1
    if current:
        chunks.append(current)
    return chunks


def split_segment_by_chars(seg: Dict[str, Any], *, max_chars: int) -> List[Dict[str, Any]]:
    text = seg.get("text", "")
    if not text:
        return []
    if len(text) <= max_chars:
        return [seg]
    speaker = seg.get("speaker")
    start = seg.get("start", 0.0)
    end = seg.get("end", start)
    total = len(text)
    pieces: List[Dict[str, Any]] = []
    base_index = seg.get("segment_index", 0)
    offset = 0
    piece_idx = 0
    while offset < total:
        next_offset = min(offset + max_chars, total)
        chunk_text = text[offset:next_offset]
        chunk_start_ratio = offset / total
        chunk_end_ratio = next_offset / total
        sub_start = start + (end - start) * chunk_start_ratio
        sub_end = start + (end - start) * chunk_end_ratio
        pieces.append(
            {
                "speaker": speaker,
                "text": chunk_text,
                "start": sub_start,
                "end": sub_end,
                "segment_index": base_index + piece_idx,
            }
        )
        offset = next_offset
        piece_idx += 1
    return pieces


def _normalize_segments(segments: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    last_end = 0.0
    for idx, seg in enumerate(segments):
        text = str(seg.get("text", "")).strip()
        if not text:
            continue
        speaker = str(seg.get("speaker") or f"spk_{idx}").strip() or f"spk_{idx}"
        start = _to_float(seg.get("start"), fallback=last_end)
        end = _to_float(seg.get("end"), fallback=start + max(len(text) / 50.0, 0.5))
        if end < start:
            end = start
        last_end = max(last_end, end)
        normalized.append(
            {
                "speaker": speaker,
                "text": text,
                "start": start,
                "end": end,
                "segment_index": idx,
            }
        )
    return normalized


def _to_float(value: Any, *, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(fallback)


__all__ = ["split_into_chunks", "build_chunks", "speaker_aware_chunks"]
