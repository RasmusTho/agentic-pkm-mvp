"""Deterministic `raw` → `normalized` transcript stage (KA-03).

Implements `docs/KNOWLEDGE_ACQUISITION/REFINEMENT_PIPELINE_CONTRACT.md` § `normalized`: one
source-agnostic shape for any acquired transcript, whatever the acquisition method
(`captions_manual` / `captions_auto` / `asr`). Per
`docs/KNOWLEDGE_ACQUISITION/NORMALIZE_TRANSCRIPT.md`:

- Deterministic: same `raw` record in, byte-identical `normalized` output out. No network, no
  LLM calls, no clock/random dependence in the output.
- Auto-caption normalization strips inline timing/styling tags and collapses the rolling-cue
  duplication (the yt-dlp #1734 pattern the research memo names): any line exactly repeating the
  immediately preceding emitted line is dropped, and each surviving line keeps its own cue's
  start/end timing.
- Language is recorded as *detected*, never asserted; `acquisition_method` is propagated
  unchanged from the raw record.
- Lineage stamps the raw record's `content_identity` plus this stage's version — no event is
  emitted here (`REFINEMENT_PIPELINE_CONTRACT.md` § Stage execution model names a stage-event
  requirement, but that wiring is KA-06 / #2801, a later slice; this stage is a pure transform).

Dispatch is on the record's **declared** `acquisition_method` token — the discriminator the
source spec owns — never on payload shape-sniffing. In the shipped `youtube_url` raw-record
shape (KA-01 #2928; KA-02 PR #2931), an ASR record's `caption_body` holds the full *plain-text*
ASR transcript while its timed segments live under `asr_segments`; sniffing `caption_body` first
would VTT-parse prose to zero cues and silently discard the transcript. The paths converge on
the same `NormalizedSegment` / `NormalizedTranscript` shape:

- `captions_manual` / `captions_auto` → parse `caption_body` as VTT-shaped cues, strip inline
  tags, dedup rolling cues;
- `asr` → read the `asr_segments` list (`{start, end, text}` dicts, the
  `app/media/transcribe.py::run_asr` shape) directly;
- anything else (including `captionless`, which carries no transcript) → `NormalizeError`.

Fail-loud guard: a record whose transcript body is non-empty but whose normalization yields zero
segments raises `NormalizeError` (item-scoped, per the contract's loud stage-failure posture) —
this stage never emits a superficially-valid empty artifact for a record that carried content.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Mapping

STAGE_NAME = "normalize"
STAGE_VERSION = 1

# Acquisition-method dispatch vocabulary, declared by the youtube_url source spec
# (YOUTUBE_SOURCE_SPEC.md; REFINEMENT_PIPELINE_CONTRACT.md § normalized). Caption-method
# records carry a VTT-shaped `caption_body`; ASR records carry timed `asr_segments`
# (KA-02 PR #2931) with `caption_body` holding the plain-text transcript. Any other token
# (including `captionless`, which has no transcript to normalize) fails loud in normalize().
_CAPTION_METHODS = frozenset({"captions_manual", "captions_auto"})
_ASR_METHOD = "asr"


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


def has_usable_transcript(normalized: NormalizedTranscript) -> bool:
    """Whether normalized evidence contains at least one usable transcript segment.

    All live pipeline producers call this on the typed result of :func:`normalize`, so acquire,
    replay, and candidate assembly share one decision for the valid empty-ASR terminal state.
    Captionless and malformed inputs never reach this helper because ``normalize`` fails loudly.
    """
    return bool(normalized.segments)


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


def normalize(raw_record: dict[str, Any]) -> NormalizedTranscript:
    """Normalize a `raw` transcript record into the shared `normalized` shape.

    Dispatches on the record's declared `acquisition_method` token (contract-honest: the
    discriminator is set by the source plugin per its source spec, never guessed from payload
    shape). Caption methods parse `caption_body` as VTT-shaped cues with rolling-cue dedup;
    `asr` reads the timed `asr_segments` list directly. Both converge on one
    `NormalizedTranscript` schema.

    Raises `NormalizeError` (item-scoped, loud) for an unrecognized method token, and whenever
    a record carrying a non-empty transcript body would otherwise normalize to zero segments —
    an empty result from non-empty content is transcript loss, never a valid output.
    """
    acquisition_method = raw_record.get("acquisition_method")
    if not acquisition_method or not isinstance(acquisition_method, str):
        raise NormalizeError("raw_record.acquisition_method is required and must be a string")

    content_identity = raw_record.get("content_identity")
    if not content_identity or not isinstance(content_identity, str):
        raise NormalizeError("raw_record.content_identity is required and must be a string")

    raw_body = raw_record.get("caption_body")
    caption_body: str = raw_body if isinstance(raw_body, str) else ""
    body_has_content = bool(caption_body.strip())

    if acquisition_method in _CAPTION_METHODS:
        if not body_has_content:
            raise NormalizeError(
                f"{acquisition_method} record has no caption_body to normalize "
                "(malformed raw record: caption-method records always carry a caption track body)"
            )
        segments = dedup_rolling_cues(parse_caption_cues(caption_body))
        if not segments:
            raise NormalizeError(
                "caption_body is non-empty but parsed to zero cues/segments — refusing to emit "
                "an empty normalized artifact for a record that carried transcript content"
            )
    elif acquisition_method == _ASR_METHOD:
        asr_segments = raw_record.get("asr_segments")
        if not isinstance(asr_segments, list):
            raise NormalizeError("asr record asr_segments must be a list")

        normalized_segments: list[NormalizedSegment] = []
        try:
            for index, segment in enumerate(asr_segments):
                if not isinstance(segment, Mapping):
                    raise TypeError(f"asr_segments[{index}] must be a mapping")

                start_raw = segment["start"]
                end_raw = segment["end"]
                text_raw = segment["text"]
                if (
                    not isinstance(start_raw, (int, float))
                    or isinstance(start_raw, bool)
                    or not isinstance(end_raw, (int, float))
                    or isinstance(end_raw, bool)
                ):
                    raise TypeError(
                        f"asr_segments[{index}] start/end must be numeric values"
                    )
                start = float(start_raw)
                end = float(end_raw)
                if not math.isfinite(start) or not math.isfinite(end):
                    raise ValueError(
                        f"asr_segments[{index}] start/end must be finite"
                    )
                if end < start:
                    raise ValueError(
                        f"asr_segments[{index}] end must not precede start"
                    )
                if not isinstance(text_raw, str):
                    raise TypeError(
                        f"asr_segments[{index}].text must be a string"
                    )
                normalized_text = _normalize_whitespace(text_raw)
                if not normalized_text:
                    raise ValueError(
                        f"asr_segments[{index}].text must be non-blank"
                    )
                normalized_segments.append(
                    NormalizedSegment(
                        start=start,
                        end=end,
                        text=normalized_text,
                    )
                )
        except (KeyError, OverflowError, TypeError, ValueError) as exc:
            # A malformed asr_segments entry (missing start/end/text key, or a non-numeric
            # start/end) must surface the stage's own uniform error type, not a raw stdlib
            # exception — KA-06 (#2801) stage dead-lettering needs one consistent catch target.
            raise NormalizeError(
                f"asr record has a malformed asr_segments entry: {exc!r}"
            ) from exc
        segments = tuple(normalized_segments)
        segments = tuple(seg for seg in segments if seg.text)
        if not segments and body_has_content:
            raise NormalizeError(
                "asr record has a non-empty transcript body but zero usable asr_segments — "
                "refusing to emit an empty normalized artifact for a record that carried "
                "transcript content"
            )
    else:
        raise NormalizeError(
            f"unsupported acquisition_method for normalize: {acquisition_method!r} "
            f"(caption methods: {sorted(_CAPTION_METHODS)}; asr: {_ASR_METHOD!r}; "
            "'captionless' records carry no transcript and are not normalizable)"
        )

    metadata = raw_record.get("metadata") or {}
    chapters = tuple(dict(ch) for ch in (metadata.get("chapters") or ()) if ch)

    language = raw_record.get("caption_language") or raw_record.get("language")
    # Every branch above either raises NormalizeError or is a _CAPTION_METHODS / _ASR_METHOD
    # token, so acquisition_method is always a valid key here — no default fallback needed.
    quality_note = _QUALITY_NOTES[acquisition_method]

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
# Matches any inline VTT tag: styling (`<c>`, `</c>`, `<b>`, `<c.colorE5E5E5>`) and karaoke
# timestamps (`<00:00:00.500>`) alike.
_INLINE_TAG_RE = re.compile(r"<[^>]*>")


def _parse_timestamp(hours: str | None, minutes: str, seconds: str, millis: str) -> float:
    h = int(hours[:-1]) if hours else 0
    m = int(minutes)
    s = int(seconds)
    ms = int(millis)
    return h * 3600.0 + m * 60.0 + s + ms / 1000.0


def _normalize_whitespace(text: str) -> str:
    return " ".join(text.split()).strip()


def _strip_cue_text_tags(line: str) -> str:
    """Strip inline VTT timing/styling tags (karaoke timestamps, `<c>`/`<b>` etc.).

    Tags substitute as a single space — not the empty string — so adjacent words never join
    when no whitespace precedes the tag (`foo<c>bar</c>` → "foo bar", not "foobar"); runs of
    whitespace then collapse via `_normalize_whitespace`.
    """
    stripped = _INLINE_TAG_RE.sub(" ", line)
    return _normalize_whitespace(stripped)


@dataclass(frozen=True)
class _RawCue:
    start: float
    end: float
    lines: tuple[str, ...]


def parse_caption_cues(caption_body: str) -> tuple[_RawCue, ...]:
    """Parse a VTT-shaped caption body into raw cues (tags stripped, blank lines dropped).

    Tolerant of the WEBVTT header, `Kind:`/`Language:` metadata lines, cue identifiers, and
    cue settings after the timestamp line (`align:start position:0%`) — all ignored. A body
    with no recognizable timestamp lines (e.g. plain prose) yields zero cues; `normalize()`
    turns that into a loud item-scoped `NormalizeError` for caption-method records rather than
    silently emitting an empty transcript.
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
    "has_usable_transcript",
    "normalize",
    "parse_caption_cues",
    "dedup_rolling_cues",
]
