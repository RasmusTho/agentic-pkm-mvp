"""`youtube_url` source plugin — required `fetch(item_ref)` operation (KA-01).

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
- Captionless is a normal recorded outcome (KA-02 / ASR fallback consumes it
  later); this task never raises for "no captions".

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

from app.knowledge_acquisition.raw_record import RawRecordResult, persist_raw_record

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
      This function only ever looks at the source video's own detected/original
      language key, never at translated-language keys, so translated tracks are
      structurally excluded rather than filtered after the fact.
    - Captionless (no manual or auto track in an original language) returns
      `CaptionSelection(available=False)` — a normal outcome, not an error.
    """
    manual = info.get("subtitles") or {}
    automatic = info.get("automatic_captions") or {}
    video_language = info.get("language")

    candidate_languages = [lang for lang in (video_language,) if lang]
    candidate_languages.extend(lang for lang in original_languages if lang not in candidate_languages)

    for lang in candidate_languages:
        tracks = manual.get(lang)
        if tracks:
            return CaptionSelection(
                available=True,
                language=lang,
                acquisition_method="captions_manual",
                track_url=_pick_track_url(tracks),
            )

    for lang in candidate_languages:
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


def compute_content_identity(*, metadata: dict[str, Any], caption: CaptionSelection) -> str:
    """Hash of the acquired content itself (metadata + caption body), per
    SOURCE_PLUGIN_CONTRACT.md § Identity and dedup: distinguishes "re-fetched,
    unchanged" from "content changed upstream".
    """
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
    object_id: Any
    content_identity: str
    is_new: bool
    acquisition_method: str  # "captions_manual" | "captions_auto" | "captionless"
    language: str | None
    record: dict[str, Any] = field(default_factory=dict)


def fetch(item_ref_or_url: str) -> FetchOutcome:
    """The plugin's required `fetch(item_ref) -> RawEvidence` operation.

    Accepts either an explicit YouTube URL or a bare video id. Caption-first,
    manual-preferred, original-language-only. Captionless is recorded as a
    normal outcome (`acquisition_method: "captionless"`), never raised.
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

    content_identity = compute_content_identity(metadata=metadata, caption=caption)
    # `acquisition_method` is always set when a track is available; `or` also
    # narrows the type to `str` for the FetchOutcome contract.
    acquisition_method = caption.acquisition_method or "captionless"

    payload = {
        "source_kind": SOURCE_KIND,
        "item_ref": video_id,
        "url": item_ref_or_url,
        "metadata": metadata,
        "acquisition_method": acquisition_method,
        "caption_language": caption.language,
        "caption_body": caption.body,
        "provenance": {
            "source_kind": SOURCE_KIND,
            "url": item_ref_or_url,
            "creator": metadata.get("channel"),
            "published": metadata.get("publish_date"),
            "acquisition_method": acquisition_method,
            "plugin_version": "ka-01-v1",
        },
    }

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
        language=caption.language,
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
