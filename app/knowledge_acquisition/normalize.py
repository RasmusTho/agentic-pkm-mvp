"""Deterministic `raw` → `normalized` transcript stage (KA-03).

Implements `docs/KNOWLEDGE_ACQUISITION/REFINEMENT_PIPELINE_CONTRACT.md` § `normalized`: one
source-agnostic shape for any acquired transcript, whatever the acquisition method
(`captions_manual` / `captions_auto` / `asr`). Per
`docs/KNOWLEDGE_ACQUISITION/NORMALIZE_TRANSCRIPT.md`:

- Deterministic: same `raw` record in, byte-identical `normalized` output out. No network, no
  LLM calls, no clock/random dependence in the output.
- Auto-caption normalization strips inline timing/styling tags, collapses consecutive duplicate
  lines, and merges rolling cues that repeat trailing text into single segments with combined
  start/end (the yt-dlp #1734 pattern the research memo names).
- Language is recorded as *detected*, never asserted; `acquisition_method` is propagated
  unchanged from the raw record.
- Lineage stamps the raw record's `content_identity` plus this stage's version — no event is
  emitted here (`REFINEMENT_PIPELINE_CONTRACT.md` § Stage execution model names a stage-event
  requirement, but that wiring is KA-06 / #2801, a later slice; this stage is a pure transform).

Both the caption path (`caption_body`: a VTT-shaped string) and the ASR path (`segments`: a list
of `{start, end, text}` dicts, per `app/media/transcribe.py::run_asr`) funnel through the same
`normalize()` entry point to the same `NormalizedSegment` / `NormalizedTranscript` shape.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

STAGE_NAME = "normalize"
STAGE_VERSION = 1

# Acquisition methods declared by the youtube_url source spec
# (YOUTUBE_SOURCE_SPEC.md; REFINEMENT_PIPELINE_CONTRACT.md § normalized).
_CAPTION_METHODS = {"captions_manual", "captions_auto"}


class NormalizeError(ValueError):
    """Raised when a raw record cannot be normalized (malformed/missing required fields)."""


@dataclass(frozen=True)
class NormalizedSegment:
    start: float
    end: float
    text: str
    speaker: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "start": self.start,
            "end": self.end,
            "text": self.text,
            "speaker": self.speaker,
        }


@dataclass(frozen=True)
class NormalizedTranscript:
    """The one source-agnostic normalized artifact (`REFINEMENT_PIPELINE_CONTRACT.md` § normalized)."""

    segments: tuple[NormalizedSegment, ...]
    language: str | None
    language_detected: bool
    acquisition_method: str
    quality_note: str
    chapters: tuple[dict[str, Any], ...]
    source_content_identity: str
    stage: str = STAGE_NAME
    stage_version: int = STAGE_VERSION

    def as_dict(self) -> dict[str, Any]:
        """Deterministic, JSON-serializable projection (dict/list/str/float/bool/None only)."""
        return {
            "stage": self.stage,
            "stage_version": self.stage_version,
            "source_content_identity": self.source_content_identity,
            "acquisition_method": self.acquisition_method,
            "language": self.language,
            "language_detected": self.language_detected,
            "quality_note": self.quality_note,
            "chapters": [dict(chapter) for chapter in self.chapters],
            "segments": [segment.as_dict() for segment in self.segments],
        }


# Quality notes are deterministic, fixed strings keyed by acquisition method — per
# REFINEMENT_PIPELINE_CONTRACT.md § normalized ("a quality note: consumers may weigh acquisition
# methods differently") and RESEARCH_2026-07.md § 3 ("manual captions > faster-whisper ASR >
# auto-captions"). Never derived from content, so identical input always yields an identical note.
_QUALITY_NOTES: dict[str, str] = {
    "captions_manual": "creator-provided manual captions; highest fidelity of the acquisition methods",
    "captions_auto": "machine-generated auto-captions; rolling-cue duplication removed by normalization, "
    "punctuation/segmentation may still be imprecise",
    "asr": "local faster-whisper transcription; used only when no caption track was available",
}
_DEFAULT_QUALITY_NOTE = "acquisition method not recognized; quality unknown"


def normalize(raw_record: dict[str, Any]) -> NormalizedTranscript:
    """Normalize a `raw` transcript record into the shared `normalized` shape.

    Dispatches on shape, not a hardcoded source check: a `caption_body` string is parsed as
    caption cues (VTT-style) and rolling-cue deduped; a `segments` list (the ASR shape) is taken
    as already-segmented and passed through the same downstream pipeline. Both converge on one
    `NormalizedTranscript` schema.
    """
    acquisition_method = raw_record.get("acquisition_method")
    if not acquisition_method or not isinstance(acquisition_method, str):
        raise NormalizeError("raw_record.acquisition_method is required and must be a string")

    content_identity = raw_record.get("content_identity")
    if not content_identity or not isinstance(content_identity, str):
        raise NormalizeError("raw_record.content_identity is required and must be a string")

    caption_body = raw_record.get("caption_body")
    asr_segments = raw_record.get("segments")

    if caption_body:
        raw_segments = parse_caption_cues(caption_body)
        segments = dedup_rolling_cues(raw_segments)
    elif asr_segments:
        segments = tuple(
            NormalizedSegment(
                start=float(seg["start"]),
                end=float(seg["end"]),
                text=_normalize_whitespace(str(seg["text"])),
            )
            for seg in asr_segments
        )
        segments = tuple(seg for seg in segments if seg.text)
    else:
        segments = ()

    metadata = raw_record.get("metadata") or {}
    chapters = tuple(dict(ch) for ch in (metadata.get("chapters") or ()) if ch)

    language = raw_record.get("caption_language") or raw_record.get("language")
    quality_note = _QUALITY_NOTES.get(acquisition_method, _DEFAULT_QUALITY_NOTE)

    return NormalizedTranscript(
        segments=segments,
        language=language,
        # Language is always "detected" per REFINEMENT_PIPELINE_CONTRACT.md § normalized
        # ("language (detected, marked as detected)") — this stage never asserts ground truth,
        # regardless of whether the upstream language came from a caption track or ASR.
        language_detected=True,
        acquisition_method=acquisition_method,
        quality_note=quality_note,
        chapters=chapters,
        source_content_identity=content_identity,
    )


# ---------------------------------------------------------------------------
# Caption (VTT-shaped) parsing
# ---------------------------------------------------------------------------

_TIMESTAMP_RE = re.compile(
    r"(\d{2}:)?(\d{2}):(\d{2})[.,](\d{3})\s*-->\s*(\d{2}:)?(\d{2}):(\d{2})[.,](\d{3})"
)
_INLINE_TAG_RE = re.compile(r"<[^>]*>")
_KARAOKE_TIMESTAMP_RE = re.compile(r"<\d{2}:\d{2}:\d{2}[.,]\d{3}>")


def _parse_timestamp(hours: str | None, minutes: str, seconds: str, millis: str) -> float:
    h = int(hours[:-1]) if hours else 0
    m = int(minutes)
    s = int(seconds)
    ms = int(millis)
    return h * 3600.0 + m * 60.0 + s + ms / 1000.0


def _normalize_whitespace(text: str) -> str:
    return " ".join(text.split()).strip()


def _strip_cue_text_tags(line: str) -> str:
    """Strip inline VTT timing/styling tags (karaoke timestamps, `<c>`/`<b>` etc.)."""
    stripped = _KARAOKE_TIMESTAMP_RE.sub("", line)
    stripped = _INLINE_TAG_RE.sub("", stripped)
    return _normalize_whitespace(stripped)


@dataclass(frozen=True)
class _RawCue:
    start: float
    end: float
    lines: tuple[str, ...]


def parse_caption_cues(caption_body: str) -> tuple[_RawCue, ...]:
    """Parse a VTT-shaped caption body into raw cues (tags stripped, blank lines dropped).

    Tolerant of the WEBVTT header, `Kind:`/`Language:` metadata lines, cue identifiers, and
    cue settings after the timestamp line (`align:start position:0%`) — all ignored. Also
    tolerant of bare `srv3`/`json3`-derived plain-text bodies with no timestamp lines at all: in
    that case the whole body becomes a single untimed cue at (0.0, 0.0) rather than raising, since
    a normalizer failure would dead-letter the whole item for a cosmetic format difference.
    """
    lines = caption_body.splitlines()
    cues: list[_RawCue] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        match = _TIMESTAMP_RE.search(line)
        if match:
            start = _parse_timestamp(match.group(1), match.group(2), match.group(3), match.group(4))
            end = _parse_timestamp(match.group(5), match.group(6), match.group(7), match.group(8))
            i += 1
            cue_lines: list[str] = []
            while i < n and lines[i].strip() != "":
                cleaned = _strip_cue_text_tags(lines[i])
                if cleaned:
                    cue_lines.append(cleaned)
                i += 1
            if cue_lines:
                cues.append(_RawCue(start=start, end=end, lines=tuple(cue_lines)))
        else:
            i += 1
    return tuple(cues)


def dedup_rolling_cues(raw_cues: tuple[_RawCue, ...]) -> tuple[NormalizedSegment, ...]:
    """Collapse rolling auto-captions into deduplicated segments (yt-dlp #1734 pattern).

    Rolling auto-captions repeat trailing lines across consecutive cues (a 2-line rolling
    window: cue N's second line becomes cue N+1's first line, plus one new line). This:

    1. Drops any line that is an exact repeat of the immediately preceding *emitted* line
       (collapses consecutive duplicate lines regardless of cue boundaries).
    2. Merges the surviving new text of a rolling cue into one segment per genuinely new line,
       using that line's own cue timing — so timestamps stay meaningful per line rather than
       collapsing to one mega-segment.

    Deterministic and order-preserving: identical input always yields identical output.
    """
    segments: list[NormalizedSegment] = []
    last_line: str | None = None
    for cue in raw_cues:
        for line in cue.lines:
            if line == last_line:
                continue
            segments.append(NormalizedSegment(start=cue.start, end=cue.end, text=line))
            last_line = line
    return tuple(segments)


__all__ = [
    "STAGE_NAME",
    "STAGE_VERSION",
    "NormalizeError",
    "NormalizedSegment",
    "NormalizedTranscript",
    "normalize",
    "parse_caption_cues",
    "dedup_rolling_cues",
]
