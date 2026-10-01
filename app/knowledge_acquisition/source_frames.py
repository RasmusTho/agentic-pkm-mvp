"""Bounded source-frame capture for YouTube Source Note v2 (YSNV2-11, #4118).

Per revised owner decision D1, every eligible acquisition with timestamped key moments (YSNV2-09)
attempts bounded temporary-media capture by default.  When capture succeeds, one contextual frame
(``context_frame``) is retained for visual orientation without needing a visual-necessity result;
any additional frame must pass an explicit visual-necessity predicate, perceptual-hash
deduplication, and the retained-frame cap.

The failure mode makes the note less illustrated, never less truthful:

* unavailable media, an exceeded bound, or a frame-extraction failure degrades to timestamps-only
  output — the moments are unchanged, nothing is written to the vault and no placeholder exists;
* a replay context (source egress blocked) never recaptures;
* temporary video bytes live only in a capture-owned temporary directory that is deleted in-run,
  before any vault write, and the deletion is recorded as a receipt.  A cleanup that cannot prove
  every temporary byte is gone fails loudly instead of returning success.

Retained frames are ``media_derivative`` exceptions (MEDIA_ARTIFACT_CONTRACT §3.2): source-dependent
regenerability (the derivative needs the external source again and is not an ordinary rebuildable
extraction), personal-use rights, internal-or-stricter sensitivity, and lineage back to the source
moment.  Frames are written beneath the immutable YSNV2-06 bundle version folder; nothing here
publishes a frame.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping, Protocol, Sequence
from uuid import NAMESPACE_URL, uuid5

import numpy as np

from app.knowledge.write_ops import candidate_note_exists_durable, create_candidate_note_once
from app.knowledge_acquisition.extraction_persistence import (
    ExtractionPersistenceError,
    PersistedTranscript,
    _create_immutable,
    _metadata_bundle,
)
from app.knowledge_acquisition.key_moments import PersistedKeyMoments
from app.knowledge_acquisition.source_bundle import (
    _source_key,
    _version_key,
    validate_youtube_attachment_root,
)
from app.source_egress import SourceEgressBlockedError, assert_source_egress_allowed
from app.vault.manager import VaultContext
from app.vault.path_overlap import VaultPathOverlapError, assert_targets_do_not_overlap_capture_note
from app.vault.paths import get_vault_sources_dir_rel
from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard, WritesBlockedError

SOURCE_FRAMES_ARTIFACT_KIND = "knowledge_acquisition.source_frames"
SOURCE_FRAMES_STAGE = "capture_source_frames"
SOURCE_FRAMES_STAGE_VERSION = 1
SOURCE_FRAMES_WRITE_ACTION = "knowledge_acquisition.youtube_source_frames"

# Bounds.  Capture is per acquisition, never per timeline sample.
MAX_RETAINED_FRAMES = 3  # one context_frame + at most two visually necessary frames
MAX_FRAME_EXTRACTIONS = 6
MAX_TEMP_MEDIA_BYTES = 256 * 1024 * 1024
MAX_SOURCE_DURATION_SECONDS = 4 * 60 * 60
# Every alternative must be a progressive HTTP(S) file within the byte bound.  Fragmented
# HLS/DASH downloaders do not enforce ``max_filesize``, and live streams have no end.
_FORMAT_BOUND = f"[filesize<?{MAX_TEMP_MEDIA_BYTES // (1024 * 1024)}M][filesize_approx<?{MAX_TEMP_MEDIA_BYTES // (1024 * 1024)}M][protocol^=http]"
MEDIA_FORMAT = (
    f"worst[height<=360][ext=mp4]{_FORMAT_BOUND}/worst[height<=360]{_FORMAT_BOUND}/worst{_FORMAT_BOUND}"
)
_LIVE_STATUSES = frozenset({"is_live", "is_upcoming", "post_live"})
FFMPEG_TIMEOUT_SECONDS = 60
SOCKET_TIMEOUT_SECONDS = 30
FRAME_MAX_WIDTH = 640
# Hamming distance on the 64-bit DCT pHash at or below which two frames are duplicates.
PHASH_DUPLICATE_DISTANCE = 8
_PHASH_SIDE = 32
_PHASH_LOW = 8

USAGE_RIGHTS = "personal_use_only"
REGENERABILITY = "source_dependent"
MEDIA_ROLE = "media_derivative"
_SENSITIVITY_ORDER = ("public", "internal", "private", "secret")
_FRAME_MEDIA_TYPE = "image/jpeg"


class SourceFramesError(RuntimeError):
    """Frame capture received inconsistent lineage, or could not prove temporary-media cleanup."""


class MediaUnavailableError(RuntimeError):
    """The source media could not be fetched within the capture bounds."""


class FrameExtractionError(RuntimeError):
    """A frame could not be extracted from the temporary media."""


@dataclass(frozen=True)
class CapturedFrame:
    """One extracted frame: encoded image bytes plus a 32x32 grayscale raster for pHash."""

    image_bytes: bytes
    grayscale_32: bytes
    media_type: str = _FRAME_MEDIA_TYPE


class SourceMediaCapture(Protocol):
    """Seam for the only media-egress and media-decoding operations of this stage."""

    def download_temporary_media(
        self, *, item_ref: str, dest_dir: Path, max_bytes: int, max_duration_seconds: int
    ) -> Path: ...

    def extract_frame(self, *, media_path: Path, timestamp_seconds: int, work_dir: Path) -> CapturedFrame: ...


VisualNecessity = Callable[[Mapping[str, Any], CapturedFrame], bool]


def _youtube_dl(options: dict[str, Any]) -> Any:
    from yt_dlp import YoutubeDL  # type: ignore

    return YoutubeDL(options)


def _run_ffmpeg(args: Sequence[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(  # noqa: S603 - fixed argv, no shell
        ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", *args],
        capture_output=True,
        timeout=FFMPEG_TIMEOUT_SECONDS,
        check=False,
    )


class YtDlpFfmpegMediaCapture:
    """Production capture: one bounded low-resolution yt-dlp download plus ffmpeg stills."""

    def download_temporary_media(
        self, *, item_ref: str, dest_dir: Path, max_bytes: int, max_duration_seconds: int
    ) -> Path:
        assert_source_egress_allowed("source_frames.download_temporary_media")

        def duration_filter(info: Mapping[str, Any], *, incomplete: bool = False) -> str | None:
            if incomplete:
                return None
            if info.get("is_live") or info.get("live_status") in _LIVE_STATUSES:
                return "live or upcoming streams are outside the bounded capture"
            duration = info.get("duration")
            if isinstance(duration, bool) or not isinstance(duration, (int, float)) or duration <= 0:
                return "source duration is unknown; bounded capture requires a finite duration"
            if duration > max_duration_seconds:
                return f"source duration {duration}s exceeds the {max_duration_seconds}s capture bound"
            return None

        def byte_bound(progress: Mapping[str, Any]) -> None:
            for key in ("downloaded_bytes", "total_bytes", "total_bytes_estimate"):
                value = progress.get(key)
                if isinstance(value, (int, float)) and value > max_bytes:
                    raise MediaUnavailableError(f"temporary media exceeds the {max_bytes}-byte capture bound")

        options: dict[str, Any] = {
            "format": MEDIA_FORMAT,
            "outtmpl": str(dest_dir / "source-media.%(ext)s"),
            "paths": {"home": str(dest_dir), "temp": str(dest_dir)},
            "max_filesize": max_bytes,
            "match_filter": duration_filter,
            "progress_hooks": [byte_bound],
            "noplaylist": True,
            "cachedir": False,
            "quiet": True,
            "noprogress": True,
            "socket_timeout": SOCKET_TIMEOUT_SECONDS,
            "writesubtitles": False,
            "writethumbnail": False,
        }
        url = f"https://www.youtube.com/watch?v={item_ref}"
        try:
            with _youtube_dl(options) as ydl:
                ydl.extract_info(url, download=True)
        except Exception as exc:  # noqa: BLE001 - every fetch failure degrades to timestamps-only
            raise MediaUnavailableError(f"temporary media download failed: {exc}") from exc
        media = sorted(p for p in dest_dir.iterdir() if p.is_file() and p.name.startswith("source-media."))
        if not media:
            raise MediaUnavailableError("temporary media is unavailable within the capture bounds")
        return media[0]

    def extract_frame(self, *, media_path: Path, timestamp_seconds: int, work_dir: Path) -> CapturedFrame:
        still = work_dir / f"frame-{timestamp_seconds}.jpg"
        seek = ["-ss", str(int(timestamp_seconds)), "-i", str(media_path), "-frames:v", "1"]
        try:
            encoded = _run_ffmpeg(
                [*seek, "-vf", f"scale='min({FRAME_MAX_WIDTH},iw)':-2", "-q:v", "4", "-y", str(still)]
            )
            raster = _run_ffmpeg(
                [*seek, "-vf", f"scale={_PHASH_SIDE}:{_PHASH_SIDE}:flags=area,format=gray", "-f", "rawvideo", "pipe:1"]
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise FrameExtractionError(f"ffmpeg frame extraction failed: {exc}") from exc
        if encoded.returncode != 0 or raster.returncode != 0 or not still.is_file():
            raise FrameExtractionError(f"ffmpeg could not extract a frame at {timestamp_seconds}s")
        try:
            image_bytes = still.read_bytes()
        except OSError as exc:
            raise FrameExtractionError(f"extracted frame could not be read: {exc}") from exc
        return CapturedFrame(image_bytes=image_bytes, grayscale_32=bytes(raster.stdout))


@dataclass(frozen=True)
class SourceFramesResult:
    status: str
    degraded_reason: str | None
    frames: tuple[dict[str, Any], ...]
    deletion_receipt: dict[str, Any] | None
    rejected: dict[str, int] = field(default_factory=dict)
    object_id: str | None = None
    manifest_path: str | None = None

    def frame_for(self, moment_id: str) -> dict[str, Any] | None:
        return next((frame for frame in self.frames if frame["moment_id"] == moment_id), None)


def perceptual_hash(grayscale_32: bytes) -> str:
    """64-bit DCT perceptual hash (pHash) of a 32x32 8-bit grayscale raster, as 16 hex digits."""

    if not isinstance(grayscale_32, (bytes, bytearray)) or len(grayscale_32) != _PHASH_SIDE * _PHASH_SIDE:
        raise FrameExtractionError("pHash requires a 32x32 8-bit grayscale raster")
    pixels = np.frombuffer(bytes(grayscale_32), dtype=np.uint8).astype(np.float64).reshape(_PHASH_SIDE, _PHASH_SIDE)
    k = np.arange(_PHASH_SIDE)
    basis = np.cos(np.pi * (2 * k[None, :] + 1) * k[:, None] / (2 * _PHASH_SIDE))
    low = (basis @ pixels @ basis.T)[:_PHASH_LOW, :_PHASH_LOW]
    bits = (low > np.median(low)).flatten()
    value = 0
    for bit in bits:
        value = (value << 1) | int(bit)
    return f"{value:016x}"


def phash_distance(left: str, right: str) -> int:
    return bin(int(left, 16) ^ int(right, 16)).count("1")


def capture_source_frames(
    *,
    key_moments: PersistedKeyMoments,
    transcript: PersistedTranscript,
    item_ref: str,
    vault_context: VaultContext,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
    youtube_attachment_root: str | None = None,
    media_capture: SourceMediaCapture | None = None,
    visual_necessity: VisualNecessity | None = None,
    temp_root: Path | None = None,
) -> SourceFramesResult:
    """Production call site: bounded default capture over timestamped moments.

    Returns a typed result for every capture degradation; raises only for inconsistent lineage,
    an unprovable temporary-media cleanup, or a failed vault/ObjectStore write (infrastructure
    failures stay visible rather than being reported as a successful timestamps-only outcome).
    """

    extensions = key_moments.metadata_bundle.get("extensions") or {}
    if (
        extensions.get("normalized_artifact_id") != transcript.object_id
        or extensions.get("content_identity") != transcript.content_identity
        or extensions.get("item_ref") != item_ref
    ):
        raise SourceFramesError("key moments do not descend from this transcript and item_ref")
    vault_root = _vault_root(vault_context)
    if youtube_attachment_root is None:
        youtube_attachment_root = f"{get_vault_sources_dir_rel(vault_root)}/YouTube/_attachments"
    root = validate_youtube_attachment_root(youtube_attachment_root)
    bundle_folder = PurePosixPath(root) / _source_key(item_ref) / _version_key(
        transcript.content_identity, transcript.extensions.get("stage_version")
    )
    manifest_path = (bundle_folder / "frames.json").as_posix()

    moments = [dict(moment) for moment in key_moments.moments if moment.get("moment_id")]
    if not moments:
        return SourceFramesResult("timestamps_only", "no_timestamped_moments", (), None)
    if candidate_note_exists_durable(manifest_path, vault_root=vault_root):
        # A retained capture is never recaptured: the existing manifest is the durable outcome.
        return SourceFramesResult("already_captured", None, (), None, manifest_path=manifest_path)
    try:
        assert_source_egress_allowed("source_frames.capture")
    except SourceEgressBlockedError:
        return SourceFramesResult("timestamps_only", "source_egress_blocked", (), None)

    capture = media_capture or YtDlpFfmpegMediaCapture()
    attempted_at = datetime.now(timezone.utc)
    ordered = sorted(moments, key=lambda m: (-int(m.get("score") or 0), int(m["timestamp_seconds"])))
    context_moment = ordered[0]
    others = sorted(ordered[1:], key=lambda m: int(m["timestamp_seconds"]))
    rejected = {"visual_necessity_not_met": 0, "duplicate_phash": 0, "cap": 0, "extraction_failed": 0}
    selected: list[tuple[Mapping[str, Any], str, CapturedFrame, str]] = []
    degraded_reason: str | None = None

    if temp_root is not None:
        temp_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(prefix="ysnv2-frames-", dir=str(temp_root) if temp_root else None))
    try:
        try:
            media_path = capture.download_temporary_media(
                item_ref=item_ref,
                dest_dir=temp_dir,
                max_bytes=MAX_TEMP_MEDIA_BYTES,
                max_duration_seconds=MAX_SOURCE_DURATION_SECONDS,
            )
            _require_bounded_temp_media(media_path, temp_dir)
            context = _validated_frame(
                capture.extract_frame(
                    media_path=media_path, timestamp_seconds=int(context_moment["timestamp_seconds"]), work_dir=temp_dir
                )
            )
            selected.append((context_moment, "context_frame", context, perceptual_hash(context.grayscale_32)))
            extractions = 1
            for moment in others:
                if len(selected) >= MAX_RETAINED_FRAMES or extractions >= MAX_FRAME_EXTRACTIONS:
                    rejected["cap"] += 1
                    continue
                if visual_necessity is None:
                    rejected["visual_necessity_not_met"] += 1
                    continue
                extractions += 1
                try:
                    frame = _validated_frame(
                        capture.extract_frame(
                            media_path=media_path, timestamp_seconds=int(moment["timestamp_seconds"]), work_dir=temp_dir
                        )
                    )
                    digest = perceptual_hash(frame.grayscale_32)
                except FrameExtractionError:
                    rejected["extraction_failed"] += 1
                    continue
                if not _passes_visual_necessity(visual_necessity, moment, frame):
                    rejected["visual_necessity_not_met"] += 1
                elif any(phash_distance(digest, kept[3]) <= PHASH_DUPLICATE_DISTANCE for kept in selected):
                    rejected["duplicate_phash"] += 1
                else:
                    selected.append((moment, "visual_necessity", frame, digest))
        except (MediaUnavailableError, FrameExtractionError) as exc:
            degraded_reason = f"capture_failed: {exc}"
            selected = []
    finally:
        # Cleanup precedes every vault write, so no failure path can strand temporary media.
        deletion_receipt = _delete_temporary_media(temp_dir)

    if degraded_reason is not None:
        object_id = _persist_outcome(
            key_moments, transcript, "timestamps_only", degraded_reason, [], rejected, deletion_receipt, attempted_at
        )
        return SourceFramesResult(
            "timestamps_only", degraded_reason, (), deletion_receipt, dict(rejected), object_id
        )

    sensitivity = _frame_sensitivity(transcript.metadata_bundle.get("sensitivity"))
    frames = [
        _frame_record(
            moment, role, frame, digest, bundle_folder=bundle_folder, transcript=transcript,
            key_moments=key_moments, item_ref=item_ref, sensitivity=sensitivity,
        )
        for moment, role, frame, digest in selected
    ]
    targets = [str(record["path"]) for record in frames] + [manifest_path]
    try:
        assert_targets_do_not_overlap_capture_note(targets, vault_root=vault_root)
    except VaultPathOverlapError as exc:
        raise SourceFramesError(str(exc)) from exc
    manifest = {
        "artifact_kind": "youtube_source_frames",
        "media_role": MEDIA_ROLE,
        "regenerability": REGENERABILITY,
        "usage_rights": USAGE_RIGHTS,
        "sensitivity": sensitivity,
        "publishable": False,
        "item_ref": item_ref,
        "content_identity": transcript.content_identity,
        "key_moments_artifact_id": key_moments.object_id,
        "stage": SOURCE_FRAMES_STAGE,
        "stage_version": SOURCE_FRAMES_STAGE_VERSION,
        "frames": frames,
        "rejected": rejected,
        "deletion_receipt": deletion_receipt,
    }
    try:
        for record, (_moment, _role, frame, _digest) in zip(frames, selected):
            create_candidate_note_once(
                str(record["path"]), frame.image_bytes, vault_root=vault_root,
                action=SOURCE_FRAMES_WRITE_ACTION, write_guard=write_guard,
            )
        manifest_status = create_candidate_note_once(
            manifest_path, json.dumps(manifest, indent=2, sort_keys=True) + "\n", vault_root=vault_root,
            action=SOURCE_FRAMES_WRITE_ACTION, write_guard=write_guard,
        )
    except WritesBlockedError as exc:
        # Content-addressed frame names make a later retry converge; no manifest means not captured.
        return SourceFramesResult("blocked", str(exc), (), deletion_receipt, dict(rejected))
    except (OSError, ValueError) as exc:
        raise SourceFramesError(f"retained frame write failed: {exc}") from exc
    if manifest_status == "already_exists":
        # A concurrent capture won the first-write-wins manifest; its outcome is authoritative.
        return SourceFramesResult("already_captured", None, (), deletion_receipt, dict(rejected), None, manifest_path)
    object_id = _persist_outcome(
        key_moments, transcript, "frames_retained", None, frames, rejected, deletion_receipt, attempted_at
    )
    return SourceFramesResult(
        "frames_retained", None, tuple(frames), deletion_receipt, dict(rejected), object_id, manifest_path
    )


def _validated_frame(frame: CapturedFrame) -> CapturedFrame:
    if not isinstance(frame, CapturedFrame) or frame.media_type != _FRAME_MEDIA_TYPE or not frame.image_bytes:
        raise FrameExtractionError("retained frames must be non-empty JPEG stills")
    return frame


def _passes_visual_necessity(predicate: VisualNecessity, moment: Mapping[str, Any], frame: CapturedFrame) -> bool:
    try:
        return predicate(moment, frame) is True
    except Exception:  # noqa: BLE001 - an unusable necessity judgement never admits a frame
        return False


def _require_bounded_temp_media(media_path: Path, temp_dir: Path) -> None:
    try:
        resolved = media_path.resolve(strict=True)
        info = os.lstat(media_path)
    except OSError as exc:
        raise MediaUnavailableError(f"temporary media is missing: {exc}") from exc
    if resolved.parent != temp_dir.resolve() or not stat.S_ISREG(info.st_mode):
        raise MediaUnavailableError("temporary media escaped the capture-owned temporary directory")
    if info.st_size <= 0 or info.st_size > MAX_TEMP_MEDIA_BYTES:
        raise MediaUnavailableError("temporary media is empty or exceeds the byte bound")


def _delete_temporary_media(temp_dir: Path) -> dict[str, Any]:
    deleted_files = 0
    deleted_bytes = 0
    try:
        for current, dirnames, filenames in os.walk(temp_dir, topdown=False, followlinks=False):
            for name in filenames + [d for d in dirnames if os.path.islink(os.path.join(current, d))]:
                path = os.path.join(current, name)
                info = os.lstat(path)
                if stat.S_ISREG(info.st_mode):
                    deleted_bytes += info.st_size
                os.unlink(path)
                deleted_files += 1
            for name in dirnames:
                path = os.path.join(current, name)
                if not os.path.islink(path):
                    os.rmdir(path)
        os.rmdir(temp_dir)
    except OSError as exc:
        # Best-effort removal, but an itemized receipt can no longer be proven: fail visibly.
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise SourceFramesError(
            f"temporary media cleanup failed (remaining: {temp_dir.exists()}): {exc}"
        ) from exc
    if temp_dir.exists():
        raise SourceFramesError("temporary media cleanup could not prove deletion")
    return {
        "receipt_type": "temporary_media_deletion",
        "temp_dir": temp_dir.name,
        "deleted_files": deleted_files,
        "deleted_bytes": deleted_bytes,
        "remaining_entries": 0,
        "status": "deleted",
        "deleted_at": datetime.now(timezone.utc).isoformat(),
    }


def _frame_sensitivity(ancestor: object) -> str:
    if isinstance(ancestor, str) and ancestor in _SENSITIVITY_ORDER:
        return max("internal", ancestor, key=_SENSITIVITY_ORDER.index)
    return "internal"


def _frame_record(
    moment: Mapping[str, Any],
    role: str,
    frame: CapturedFrame,
    digest: str,
    *,
    bundle_folder: PurePosixPath,
    transcript: PersistedTranscript,
    key_moments: PersistedKeyMoments,
    item_ref: str,
    sensitivity: str,
) -> dict[str, Any]:
    sha256 = hashlib.sha256(frame.image_bytes).hexdigest()
    moment_id = str(moment["moment_id"])
    seconds = int(moment["timestamp_seconds"])
    path = bundle_folder / "frames" / f"{_safe_token(moment_id)}-{sha256[:12]}.jpg"
    return {
        "frame_id": str(uuid5(NAMESPACE_URL, f"urn:knowledge-acquisition:source-frame:{moment_id}:{sha256}")),
        "moment_id": moment_id,
        "frame_role": role,
        "path": path.as_posix(),
        "media_type": frame.media_type,
        "byte_size": len(frame.image_bytes),
        "sha256": sha256,
        "phash": digest,
        "timestamp_seconds": seconds,
        "media_role": MEDIA_ROLE,
        "regenerability": REGENERABILITY,
        "not_rebuildable_reason": "requires the external source video; not an ordinary rebuildable extraction",
        "usage_rights": USAGE_RIGHTS,
        "sensitivity": sensitivity,
        "publishable": False,
        "lineage": {
            "source_kind": "youtube_url",
            "source_url": f"https://www.youtube.com/watch?v={item_ref}&t={seconds}s",
            "content_identity": transcript.content_identity,
            "derived_from": [
                transcript.raw_record_id,
                transcript.object_id,
                key_moments.object_id,
                moment_id,
            ],
            "stage": SOURCE_FRAMES_STAGE,
            "stage_version": SOURCE_FRAMES_STAGE_VERSION,
        },
    }


def _safe_token(value: str) -> str:
    token = "".join(ch for ch in value if ch.isalnum() or ch == "-")
    if not token:
        raise SourceFramesError("moment_id cannot form a safe frame filename")
    return token


def _persist_outcome(
    key_moments: PersistedKeyMoments,
    transcript: PersistedTranscript,
    status: str,
    degraded_reason: str | None,
    frames: Sequence[Mapping[str, Any]],
    rejected: Mapping[str, int],
    deletion_receipt: Mapping[str, Any],
    attempted_at: datetime,
) -> str:
    """Durable per-attempt record carrying the outcome and the deletion receipt."""

    derived_from = [transcript.raw_record_id, transcript.object_id, key_moments.object_id]
    object_id = str(
        uuid5(
            NAMESPACE_URL,
            "urn:knowledge-acquisition:source-frames:"
            + ":".join([*derived_from, str(SOURCE_FRAMES_STAGE_VERSION), attempted_at.isoformat()]),
        )
    )
    extensions: dict[str, Any] = {
        "artifact_kind": "source_frames",
        "media_role": MEDIA_ROLE,
        "regenerability": REGENERABILITY,
        "usage_rights": USAGE_RIGHTS,
        "content_identity": transcript.content_identity,
        "key_moments_artifact_id": key_moments.object_id,
        "stage": SOURCE_FRAMES_STAGE,
        "stage_version": SOURCE_FRAMES_STAGE_VERSION,
        "status": status,
        "degraded_reason": degraded_reason,
        "frames": [dict(frame) for frame in frames],
        "rejected": dict(rejected),
        "deletion_receipt": dict(deletion_receipt),
        "bounds": {
            "max_retained_frames": MAX_RETAINED_FRAMES,
            "max_frame_extractions": MAX_FRAME_EXTRACTIONS,
            "max_temp_media_bytes": MAX_TEMP_MEDIA_BYTES,
            "max_source_duration_seconds": MAX_SOURCE_DURATION_SECONDS,
            "media_format": MEDIA_FORMAT,
        },
    }
    ancestor = transcript.metadata_bundle
    try:
        payload = _metadata_bundle(
            object_id=object_id,
            raw_record={
                "episode_ref": ancestor.get("episode_ref", "unbound"),
                "scope_id": ancestor.get("scope_id"),
                "sensitivity": _frame_sensitivity(ancestor.get("sensitivity")),
            },
            created_by=f"app:knowledge_acquisition.{SOURCE_FRAMES_STAGE}",
            created_at=attempted_at,
            derived_from=derived_from,
            provenance_event_ids=(
                *tuple(ancestor.get("provenance_event_ids") or ()),
                f"{SOURCE_FRAMES_STAGE}:{SOURCE_FRAMES_STAGE_VERSION}:{transcript.content_identity}:{object_id}",
            ),
            extensions=extensions,
        )
        _create_immutable(
            object_id=object_id,
            kind=SOURCE_FRAMES_ARTIFACT_KIND,
            payload=payload,
            source_ref=f"key_moments:{key_moments.object_id}",
            created_at=attempted_at,
        )
    except (ExtractionPersistenceError, KeyError, ValueError) as exc:
        raise SourceFramesError(f"source frames outcome {object_id} could not be persisted") from exc
    return object_id


def _vault_root(context: VaultContext) -> Path:
    if not context.active_vault_path:
        raise SourceFramesError("vault_context.active_vault_path is required")
    return Path(context.active_vault_path).expanduser().resolve()


__all__ = [
    "MAX_RETAINED_FRAMES",
    "PHASH_DUPLICATE_DISTANCE",
    "SOURCE_FRAMES_ARTIFACT_KIND",
    "SOURCE_FRAMES_STAGE",
    "SOURCE_FRAMES_STAGE_VERSION",
    "CapturedFrame",
    "FrameExtractionError",
    "MediaUnavailableError",
    "SourceFramesError",
    "SourceFramesResult",
    "SourceMediaCapture",
    "YtDlpFfmpegMediaCapture",
    "capture_source_frames",
    "perceptual_hash",
    "phash_distance",
]
