"""`youtube_url` source plugin — required `fetch(item_ref)` operation
(KA-01) plus the captionless ASR fallback (KA-02).

Implements the plugin fetch operation defined in
`docs/KNOWLEDGE_ACQUISITION/SOURCE_PLUGIN_CONTRACT.md` § Operations for the
`youtube_url` source instance specified in
`docs/KNOWLEDGE_ACQUISITION/YOUTUBE_SOURCE_SPEC.md`.

Mechanism (per `YOUTUBE_SOURCE_SPEC.md` § Transcript acquisition, grounded in
`RESEARCH_2026-07.md` §3):

- One yt-dlp invocation retrieves metadata (title, channel + id, publish date,
  duration, description, chapters, tags, language, thumbnail ref) and caption
  tracks via ``--write-subs --write-auto-subs --skip-download``.
- Original-language tracks only; auto-*translated* tracks are never requested
  (429-prone, excluded by the research memo and the source spec).
- Manual caption track preferred over auto-captions when both exist.
- The PO-token provider plugin (``bgutil-ytdlp-pot-provider``) is a declared
  local dependency of this egress path, wired through yt-dlp's extractor-args
  provider framework — not reimplemented here.
- Captionless falls back to the existing `app.media.transcribe.transcribe_source`
  faster-whisper chain (KA-02, `docs/KNOWLEDGE_ACQUISITION/ASR_FALLBACK_PATH.md`):
  reused as-is, never invoked when a usable caption track exists.

This module contains the only YouTube-shaped code in the platform
(`SOURCE_PLUGIN_CONTRACT.md` § preamble). Everything downstream operates on the
source-agnostic `raw` record produced here.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

from app.knowledge_acquisition.raw_record import (
    RawRecordResult,
    find_raw_record,
    persist_raw_record,
)
from app.media.transcribe import transcribe_source
from app.observability.log import json_log

SOURCE_KIND = "youtube_url"

# yt-dlp extractor args wiring the PO-token provider plugin as a declared local
# dependency for the subtitle/`subs` context (YOUTUBE_SOURCE_SPEC.md § Transcript
# acquisition; RESEARCH_2026-07.md §3). Declared once here so the egress posture
# is visible in one place, per SOURCE_PLUGIN_CONTRACT.md § Plugin identity.
_PO_TOKEN_PROVIDER_EXTRACTOR_ARGS = {
    "youtube": {
        "player-client": ["default"],
    },
    "youtubepot-bgutilhttp": {},
}

# Politeness sleeps per YOUTUBE_SOURCE_SPEC.md § Transcript acquisition
# ("low single-digit seconds").
_SLEEP_REQUESTS_SECONDS = 2
_SLEEP_SUBTITLES_SECONDS = 2

_VIDEO_ID_RE = re.compile(
    r"(?:youtu\.be/|youtube\.com/(?:watch\?v=|embed/|shorts/|v/))([A-Za-z0-9_-]{11})"
)


class CaptionAcquisitionError(RuntimeError):
    """Raised when yt-dlp itself fails (network/tooling failure) — not for 'no captions'."""


def extract_video_id(url: str) -> str:
    """Return the stable YouTube video id (item_ref) from an explicit URL."""
    match = _VIDEO_ID_RE.search(url)
    if match:
        return match.group(1)
    # Bare video id passed directly.
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", url):
        return url
    raise ValueError(f"Could not extract a YouTube video id from: {url!r}")


def yt_dlp_extract_info(url: str) -> dict[str, Any]:
    """Invoke yt-dlp once to retrieve metadata + caption track listing.

    Isolated as its own module-level function so tests can stub the network
    boundary directly (monkeypatch this function) without touching yt-dlp's
    internals — no real egress in CI. This is the only function in the plugin
    that talks to yt-dlp/YouTube.
    """
    try:
        from yt_dlp import YoutubeDL  # type: ignore
    except ImportError as exc:  # pragma: no cover - exercised via stubbing in tests
        raise CaptionAcquisitionError("yt-dlp is not installed") from exc

    ydl_opts = {
        "skip_download": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "quiet": True,
        "noprogress": True,
        "sleep_requests": _SLEEP_REQUESTS_SECONDS,
        "sleep_interval_subtitles": _SLEEP_SUBTITLES_SECONDS,
        "extractor_args": _PO_TOKEN_PROVIDER_EXTRACTOR_ARGS,
    }
    try:
        with YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(url, download=False)
    except Exception as exc:  # pragma: no cover - network/tooling failure path
        raise CaptionAcquisitionError(f"yt-dlp failed to fetch {url!r}: {exc}") from exc


@dataclass(frozen=True)
class CaptionSelection:
    """The chosen caption track, or none (captionless is a normal outcome)."""

    available: bool
    language: str | None = None
    acquisition_method: str | None = None  # "captions_manual" | "captions_auto"
    track_url: str | None = None
    body: str | None = None


def select_caption_track(
    info: dict[str, Any], *, original_languages: tuple[str, ...] = ("en", "sv")
) -> CaptionSelection:
    """Pick the caption track per the caption-first, manual-preferred, original-language-only rule.

    - Manual tracks (`info["subtitles"]`) are preferred over automatic captions
      (`info["automatic_captions"]`) whenever both exist for the same language.
    - Only original-language tracks are considered. yt-dlp's `automatic_captions`
      dict includes machine-*translated* tracks (one entry per target language);
      those are auto-*translated* and MUST NOT be requested
      (YOUTUBE_SOURCE_SPEC.md § Transcript acquisition, point 1; 429-prone).

    Language selection (the "original language" resolution):

    - **Video language known** — that language is the *only* candidate, for both
      the manual and the automatic pass. The `en`/`sv` defaults are NOT mixed in:
      for e.g. a `de` video whose `automatic_captions` carry only auto-*translated*
      `en`/`sv` entries, looking up those keys would request a translated track.
      A known-language video with no track in its own language is captionless.
      (A manual or auto track in the video's own language is accepted even when
      that language is outside `original_languages` — original-language-only
      refers to the video's language; wrong-language *rejection* is the
      pipeline's early metadata filter, not the plugin's job.)
    - **Video language unknown** (`language` missing/None) — conservative
      posture, documented decision (spec is silent; PR #2928 review round 1):
      the manual pass falls back to `original_languages` because manual tracks
      are creator-provided and never auto-*translated* (requesting one cannot
      hit the 429-prone translated endpoint, and the operator's content
      universe is sv/en per YOUTUBE_SOURCE_SPEC § Transcript acquisition).
      The automatic pass is skipped entirely: without the video's language we
      cannot tell an original auto track from an auto-translated one, so we
      prefer captionless (KA-02 ASR consumes it) over risking a translated
      track.
    - Captionless (no acceptable track) returns `CaptionSelection(available=False)`
      — a normal outcome, not an error.
    """
    manual = info.get("subtitles") or {}
    automatic = info.get("automatic_captions") or {}
    video_language = info.get("language")

    if video_language:
        manual_candidates: tuple[str, ...] = (video_language,)
        automatic_candidates: tuple[str, ...] = (video_language,)
    else:
        manual_candidates = original_languages
        automatic_candidates = ()  # conservative: never guess at auto-caption keys

    for lang in manual_candidates:
        tracks = manual.get(lang)
        if tracks:
            return CaptionSelection(
                available=True,
                language=lang,
                acquisition_method="captions_manual",
                track_url=_pick_track_url(tracks),
            )

    for lang in automatic_candidates:
        tracks = automatic.get(lang)
        if tracks:
            return CaptionSelection(
                available=True,
                language=lang,
                acquisition_method="captions_auto",
                track_url=_pick_track_url(tracks),
            )

    return CaptionSelection(available=False)


def _pick_track_url(tracks: list[dict[str, Any]]) -> str | None:
    for track in tracks:
        if track.get("ext") in {"vtt", "srv3", "json3"}:
            return track.get("url")
    return tracks[0].get("url") if tracks else None


def fetch_caption_body(track_url: str) -> str:
    """Retrieve the caption track body for the selected track.

    Isolated so tests can stub this network call independently of
    `yt_dlp_extract_info` (e.g. to exercise a caption download failure without
    touching metadata extraction).
    """
    try:
        from yt_dlp.utils import sanitized_Request  # type: ignore
        from urllib.request import urlopen
    except ImportError as exc:  # pragma: no cover
        raise CaptionAcquisitionError("yt-dlp is not installed") from exc
    try:
        with urlopen(sanitized_Request(track_url), timeout=10) as resp:  # nosec B310 - yt-dlp-provided URL
            return resp.read().decode("utf-8", errors="replace")
    except Exception as exc:  # pragma: no cover - network failure path
        raise CaptionAcquisitionError(f"failed to download caption track: {exc}") from exc


def compute_content_identity(
    *, metadata: dict[str, Any], caption: CaptionSelection, asr_fallback: bool = False
) -> str:
    """Hash of the acquired content, per SOURCE_PLUGIN_CONTRACT.md § Identity
    and dedup: distinguishes "re-fetched, unchanged" from "content changed
    upstream".

    Caption path (``asr_fallback=False``): metadata + the caption track body —
    the KA-01 fingerprint, byte-for-byte unchanged.

    ASR path (``asr_fallback=True``): the transcribed text MUST NOT enter the
    identity hash — faster-whisper output is non-deterministic (beam search,
    no fixed seed), so hashing it would mint a new record on every re-fetch of
    an unchanged item, violating fetch idempotency and re-paying the full
    download + transcription each time. Identity is instead bound to the
    STABLE acquired signals: the same upstream metadata fields the caption
    path hashes, plus a method discriminator. It is computed BEFORE ASR runs,
    so a dedup hit skips the ASR chain entirely. Accepted consequences:

    - Change detection on the ASR path is metadata-bound: an upstream audio
      re-upload with byte-identical metadata is not re-acquired (undetectable
      without downloading the audio — an accepted bound).
    - If captions later appear on the video, the caption path computes a
      caption-based identity (different fingerprint shape) → a new record →
      correct quality upgrade, with the prior ASR record left untouched.
    """
    if asr_fallback:
        fingerprint: dict[str, Any] = {
            "title": metadata.get("title"),
            "description": metadata.get("description"),
            "duration": metadata.get("duration"),
            "acquisition_method": "asr",
        }
    else:
        fingerprint = {
            "title": metadata.get("title"),
            "description": metadata.get("description"),
            "duration": metadata.get("duration"),
            "caption_language": caption.language,
            "caption_method": caption.acquisition_method,
            "caption_body": caption.body,
        }
    encoded = json.dumps(fingerprint, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class FetchOutcome:
    """Result of one `fetch` call.

    ``ok=False`` marks an item-scoped acquisition failure (currently: the ASR
    chain failed on a captionless item). Per REFINEMENT_PIPELINE_CONTRACT.md
    § Stage execution model the failure is loud and traced but scoped to the
    item: no raw record is fabricated, ``object_id`` is ``None``, and the item
    stays retryable (nothing occupies its identity slot).
    """

    object_id: Any
    content_identity: str
    is_new: bool
    acquisition_method: str  # "captions_manual" | "captions_auto" | "asr"
    language: str | None
    record: dict[str, Any] = field(default_factory=dict)
    ok: bool = True
    failure: str | None = None


def _run_asr_fallback(item_ref_or_url: str) -> dict[str, Any]:
    """Run the captionless item through the existing faster-whisper chain.

    Per `docs/KNOWLEDGE_ACQUISITION/ASR_FALLBACK_PATH.md`: reuse
    `app.media.transcribe.transcribe_source` as-is (no internal changes,
    diarization hook and model cache stay as they are). Only invoked when no
    usable caption track exists — audio download engages the full media
    anti-bot machinery, which is why ASR is the fallback, never the default.
    """
    result = transcribe_source(item_ref_or_url)
    payload = result.get("payload") or {}
    return {
        "text": payload.get("text"),
        "segments": payload.get("segments") or [],
        "language": payload.get("language"),
    }


def fetch(item_ref_or_url: str) -> FetchOutcome:
    """The plugin's required `fetch(item_ref) -> RawEvidence` operation.

    Accepts either an explicit YouTube URL or a bare video id. Caption-first,
    manual-preferred, original-language-only. A captionless item falls back
    to the existing faster-whisper ASR chain (KA-02); ASR is never invoked
    when a usable caption track exists.

    Captionless flow order: extract_info (cheap) → captionless → compute the
    metadata-bound ASR identity → store dedup check → hit = traced no-op (ASR
    never runs); miss = run ASR, persist. An ASR-chain failure returns a
    traced ``ok=False`` outcome instead of raising (see FetchOutcome).
    """
    video_id = extract_video_id(item_ref_or_url)
    info = yt_dlp_extract_info(item_ref_or_url)

    caption = select_caption_track(info)
    if caption.available and caption.track_url:
        body = fetch_caption_body(caption.track_url)
        caption = CaptionSelection(
            available=True,
            language=caption.language,
            acquisition_method=caption.acquisition_method,
            track_url=caption.track_url,
            body=body,
        )

    metadata = {
        "title": info.get("title"),
        "channel": info.get("channel") or info.get("uploader"),
        "channel_id": info.get("channel_id") or info.get("uploader_id"),
        "publish_date": info.get("upload_date"),
        "duration": info.get("duration"),
        "description": info.get("description"),
        "chapters": info.get("chapters"),
        "tags": info.get("tags"),
        "language": info.get("language"),
        "thumbnail": info.get("thumbnail"),
    }

    asr_transcript: dict[str, Any] | None = None
    if caption.available:
        # Usable caption track exists — ASR MUST NOT run (ASR_FALLBACK_PATH.md
        # § Purpose: "never when a usable caption track exists").
        content_identity = compute_content_identity(metadata=metadata, caption=caption)
        if caption.acquisition_method is None:  # pragma: no cover - select_caption_track invariant
            raise CaptionAcquisitionError(
                "selected caption track has no acquisition_method "
                "(select_caption_track always sets it for available tracks)"
            )
        acquisition_method = caption.acquisition_method
        caption_language = caption.language
        caption_body = caption.body
    else:
        # ASR-path identity is metadata-bound and computed BEFORE the ASR
        # chain runs (see compute_content_identity), so an unchanged item is a
        # traced dedup no-op that never re-pays download + transcription.
        content_identity = compute_content_identity(
            metadata=metadata, caption=caption, asr_fallback=True
        )
        existing = find_raw_record(
            source_kind=SOURCE_KIND, item_ref=video_id, content_identity=content_identity
        )
        if existing is not None:
            return FetchOutcome(
                object_id=existing.object_id,
                content_identity=existing.content_identity,
                is_new=False,
                acquisition_method=str(existing.record.get("acquisition_method") or "asr"),
                language=existing.record.get("caption_language"),
                record=existing.record,
            )
        try:
            asr_transcript = _run_asr_fallback(item_ref_or_url)
        except Exception as exc:
            # Loud, item-scoped, traced (REFINEMENT_PIPELINE_CONTRACT.md
            # § Stage execution model): the ASR chain crosses yt-dlp, ffmpeg
            # (subprocess.CalledProcessError), and faster-whisper
            # (RuntimeError), each with its own exception taxonomy, so the
            # boundary catches broadly. No raw record is fabricated; the
            # identity slot stays free and the item is retryable.
            failure = f"{type(exc).__name__}: {exc}"
            json_log(
                event="knowledge_acquisition.asr.fallback_failed",
                source_kind=SOURCE_KIND,
                item_ref=video_id,
                url=item_ref_or_url,
                content_identity=content_identity,
                error=failure,
            )
            return FetchOutcome(
                object_id=None,
                content_identity=content_identity,
                is_new=False,
                acquisition_method="asr",
                language=None,
                record={},
                ok=False,
                failure=failure,
            )
        acquisition_method = "asr"
        caption_language = asr_transcript.get("language")
        caption_body = asr_transcript.get("text")

    payload = {
        "source_kind": SOURCE_KIND,
        "item_ref": video_id,
        "url": item_ref_or_url,
        "metadata": metadata,
        "acquisition_method": acquisition_method,
        "caption_language": caption_language,
        "caption_body": caption_body,
        "provenance": {
            "source_kind": SOURCE_KIND,
            "url": item_ref_or_url,
            "creator": metadata.get("channel"),
            "published": metadata.get("publish_date"),
            "acquisition_method": acquisition_method,
            "plugin_version": "ka-01-v1",
        },
    }
    if asr_transcript is not None:
        # ASR-only fields: shape parity with the caption path is preserved
        # above (identical top-level schema); this additive field carries the
        # ASR quality note + timed segments the normalize stage (KA-03) reads
        # for the ASR path, per REFINEMENT_PIPELINE_CONTRACT.md § normalized.
        payload["asr_segments"] = asr_transcript.get("segments") or []
        payload["quality_note"] = (
            "asr: local faster-whisper transcription (fallback; no caption track available)"
        )

    result: RawRecordResult = persist_raw_record(
        source_kind=SOURCE_KIND,
        item_ref=video_id,
        content_identity=content_identity,
        payload=payload,
        source_ref=item_ref_or_url,
    )

    return FetchOutcome(
        object_id=result.object_id,
        content_identity=result.content_identity,
        is_new=result.is_new,
        acquisition_method=acquisition_method,
        language=caption_language,
        record=result.record,
    )


__all__ = [
    "SOURCE_KIND",
    "CaptionAcquisitionError",
    "CaptionSelection",
    "FetchOutcome",
    "extract_video_id",
    "yt_dlp_extract_info",
    "select_caption_track",
    "fetch_caption_body",
    "compute_content_identity",
    "fetch",
]
