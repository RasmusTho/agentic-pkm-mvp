from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

# Chunk metadata schema v1 fields. Documented in `docs/EMBEDDINGS.md :: Oversized
# input handling` and `docs/DATA_MODEL.md :: store_vector_index`. Every chunk
# produced by `build_chunks`/`build_structural_chunks` carries exactly these
# fields (heading_path is `[]` for non-structural / diarized chunks).
CHUNK_METADATA_FIELDS_V1 = (
    "chunk_id",
    "source_id",
    "heading_path",
    "char_start",
    "char_end",
    "language",
    "provenance",
)

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S.*)$")


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
    source_id: Optional[str] = None,
    language: str = "und",
    provenance: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Chunk ``text`` (or diarized ``segments``) and attach chunk metadata schema v1.

    Diarization/speaker-aware path is preserved unchanged when ``segments`` are
    supplied. Otherwise markdown text is split with heading/section-aware
    structural boundaries (v1: character + heading boundaries only; no
    tokenizer/model-based windowing — that is deferred to W5, see #2323).
    """
    if segments:
        normalized = _normalize_segments(segments)
        if normalized:
            chunks = speaker_aware_chunks(normalized, max_chars=max_chars)
            return _attach_metadata(
                chunks, text=text, source_id=source_id, language=language, provenance=provenance
            )
    structural = build_structural_chunks(text, max_chars=max_chars)
    return _attach_metadata(
        structural, text=text, source_id=source_id, language=language, provenance=provenance
    )


def build_structural_chunks(text: str, *, max_chars: int = 3000) -> List[Dict[str, Any]]:
    """Heading/section-aware structural chunker (v1: char + heading boundaries only).

    Splits markdown at heading boundaries first (tracking a heading-path stack),
    then sub-splits any section that still exceeds ``max_chars`` using the naive
    char/line accumulator. Each returned dict carries ``text``, ``heading_path``
    (list of heading strings from h1..hN), ``char_start``, and ``char_end``
    (offsets into the original ``text``).
    """
    if not text:
        return []
    sections = _split_by_headings(text)
    out: List[Dict[str, Any]] = []
    for section_text, heading_path, section_start in sections:
        if len(section_text) <= max_chars:
            out.append(
                {
                    "text": section_text,
                    "heading_path": list(heading_path),
                    "char_start": section_start,
                    "char_end": section_start + len(section_text),
                }
            )
            continue
        offset = section_start
        for piece in split_into_chunks(section_text, max_chars=max_chars):
            out.append(
                {
                    "text": piece,
                    "heading_path": list(heading_path),
                    "char_start": offset,
                    "char_end": offset + len(piece),
                }
            )
            offset += len(piece)
    return out


def _split_by_headings(text: str) -> List[Tuple[str, List[str], int]]:
    """Split text into (section_text, heading_path, char_start) tuples.

    A heading path is the stack of active headings by level (h1..h6) at the
    point a section starts, e.g. ["Intro", "Background"] for text under an
    `## Background` heading nested below `# Intro`.
    """
    lines = text.splitlines(keepends=True)
    sections: List[Tuple[str, List[str], int]] = []
    stack: List[Tuple[int, str]] = []  # (level, heading text)
    cur_lines: List[str] = []
    cur_start = 0
    offset = 0

    def flush(next_start: int) -> None:
        nonlocal cur_lines, cur_start
        if cur_lines:
            sections.append(("".join(cur_lines), [h for _, h in stack], cur_start))
        cur_lines = []
        cur_start = next_start

    for line in lines:
        match = _HEADING_RE.match(line.rstrip("\n"))
        if match:
            flush(offset)
            level = len(match.group(1))
            heading_text = match.group(2).strip()
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, heading_text))
            cur_lines = [line]
            cur_start = offset
        else:
            cur_lines.append(line)
        offset += len(line)
    flush(offset)
    return [s for s in sections if s[0].strip()]


def _attach_metadata(
    chunks: List[Dict[str, Any]],
    *,
    text: str,
    source_id: Optional[str],
    language: str,
    provenance: Optional[str],
) -> List[Dict[str, Any]]:
    """Attach chunk metadata schema v1 fields to each chunk record in place.

    Offsets (``char_start``/``char_end``) are preserved when already present
    (structural chunker); otherwise they are computed by locating each chunk's
    text within the source text sequentially (diarization / naive fallback path).
    """
    search_from = 0
    out: List[Dict[str, Any]] = []
    for idx, chunk in enumerate(chunks):
        chunk_text = chunk.get("text", "")
        if "char_start" in chunk and "char_end" in chunk:
            char_start = chunk["char_start"]
            char_end = chunk["char_end"]
        else:
            found = text.find(chunk_text, search_from) if chunk_text else -1
            if found < 0:
                found = search_from
            char_start = found
            char_end = found + len(chunk_text)
            search_from = char_end
        enriched = dict(chunk)
        enriched["chunk_id"] = _chunk_id(source_id, idx, char_start, char_end)
        enriched["source_id"] = source_id
        enriched.setdefault("heading_path", [])
        enriched["char_start"] = char_start
        enriched["char_end"] = char_end
        enriched["language"] = language
        enriched["provenance"] = provenance
        out.append(enriched)
    return out


def _chunk_id(source_id: Optional[str], index: int, char_start: int, char_end: int) -> str:
    """Deterministic chunk_id: stable across re-chunking the same source/offsets.

    Compatible with `IncludedItem.chunk_ids: list[str]` in
    `app/context_bundles/schema.py` (plain string identifiers).
    """
    basis = f"{source_id or ''}:{index}:{char_start}:{char_end}"
    digest = hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]
    return f"chunk_{digest}"


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


__all__ = [
    "split_into_chunks",
    "build_chunks",
    "build_structural_chunks",
    "speaker_aware_chunks",
    "CHUNK_METADATA_FIELDS_V1",
]
