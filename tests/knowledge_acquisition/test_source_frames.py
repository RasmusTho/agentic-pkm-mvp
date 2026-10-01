"""YSNV2-11 bounded source-frame capture tests (#4118).

Every test drives the production call site ``capture_source_frames`` over durable YSNV2-09 key
moments.  No test performs real network or media egress: the production ``YtDlpFfmpegMediaCapture``
runs with its two lowest boundaries (``_youtube_dl`` and ``_run_ffmpeg``) replaced by in-process
fakes, while sockets and ``subprocess.run`` are forbidden outright.
"""

from __future__ import annotations

import json
import math
import os
import socket
import subprocess
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from app import objects as object_store_module
from app.knowledge_acquisition import source_frames as frames_module
from app.knowledge_acquisition.extraction_persistence import (
    persist_extraction_result,
    persist_normalized_transcript,
)
from app.knowledge_acquisition.extraction_registry import ExtractionResult
from app.knowledge_acquisition.key_moments import derive_key_moments
from app.knowledge_acquisition.normalize import NormalizedSegment, NormalizedTranscript
from app.knowledge_acquisition.raw_record import raw_record_object_id
from app.knowledge_acquisition.source_frames import (
    MAX_RETAINED_FRAMES,
    PHASH_DUPLICATE_DISTANCE,
    SOURCE_FRAMES_ARTIFACT_KIND,
    CapturedFrame,
    FrameExtractionError,
    MediaUnavailableError,
    SourceFramesError,
    capture_source_frames,
    perceptual_hash,
    phash_distance,
)
from app.objects import ObjectStore
from app.source_egress import block_source_egress
from app.stores import reset_store_backends
from app.vault.manager import VaultContext
from app.write_guard import WriteGuard
from tests.invariants._helpers import assert_validates

pytestmark = pytest.mark.not_pg

VIDEO_ID = "abcDEF12345"
CONTENT_IDENTITY = "sha256:frames-fixture"
VIDEO_MARKER = b"FAKE-MP4-VIDEO-BYTES"
VIDEO_BYTES = VIDEO_MARKER * 512
RAW_ID = str(raw_record_object_id(source_kind="youtube_url", item_ref=VIDEO_ID, content_identity=CONTENT_IDENTITY))


@pytest.fixture(autouse=True)
def _memory_store(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("STORE_BACKEND", "memory")
    reset_store_backends()
    object_store_module._MEMORY_STORE.clear()
    yield
    object_store_module._MEMORY_STORE.clear()


@pytest.fixture(autouse=True)
def _no_real_egress(monkeypatch: pytest.MonkeyPatch):
    def _forbidden(*_args, **_kwargs):
        raise AssertionError("source-frame tests must not perform real network or media egress")

    monkeypatch.setattr(socket, "create_connection", _forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", _forbidden)
    monkeypatch.setattr(subprocess, "run", _forbidden)
    monkeypatch.setattr(subprocess, "Popen", _forbidden)
    monkeypatch.setattr(frames_module, "_youtube_dl", _forbidden)
    monkeypatch.setattr(frames_module, "_run_ffmpeg", _forbidden)


# --- fixture rasters: 32x32 grayscale ---------------------------------------------------------

def _raster(fn) -> bytes:
    return bytes(max(0, min(255, int(fn(x, y)))) for y in range(32) for x in range(32))


RASTERS = {
    "scene": _raster(lambda x, y: 128 + 60 * math.sin(x / 5) + 50 * math.cos(y / 7)),
    # Same scene with +/-1 deterministic sensor noise: a perceptual, not byte-level, duplicate.
    "scene_noisy": _raster(lambda x, y: 128 + 60 * math.sin(x / 5) + 50 * math.cos(y / 7) + ((x * 7 + y * 3) % 3) - 1),
    "checker": _raster(lambda x, y: 255 if ((x // 4) + (y // 4)) % 2 else 0),
    "vertical": _raster(lambda x, y: y * 8),
    "diagonal": _raster(lambda x, y: (x + y) * 4),
    "rings": _raster(lambda x, y: 128 + 120 * math.sin(math.hypot(x - 16, y - 16) / 2)),
}


def _jpeg(seconds: int) -> bytes:
    return b"\xff\xd8\xff\xe0" + f"still-{seconds}".encode() + b"\xff\xd9"


# --- durable YSNV2-09 input --------------------------------------------------------------------

def _moments(*, claim_segments: tuple[int, ...] = (3, 30, 30, 60, 90, 110), duration: float = 1200.0):
    segments = tuple(
        NormalizedSegment(start=i * 10.0, end=(i + 1) * 10.0, text=f"Talking about the topic {i}.")
        for i in range(int(duration // 10))
    )
    normalized = NormalizedTranscript(
        segments=segments,
        language="en",
        language_detected=False,
        acquisition_method="captions_manual",
        quality_note="",
        chapters=(),
        source_content_identity=CONTENT_IDENTITY,
    )
    transcript = persist_normalized_transcript(
        raw_record_id=RAW_ID,
        raw_record={
            "content_identity": CONTENT_IDENTITY,
            "acquired_at": "2026-10-01T09:00:00+00:00",
            "scope_id": "scope:external/youtube",
            "sensitivity": "internal",
        },
        normalized=normalized,
    )
    claims = [
        {
            "source_wording": f"Claim at segment {index} number {n}.",
            "system_paraphrase": "The source makes a claim.",
            "anchors": [{"segment_index": index, "start": segments[index].start, "end": segments[index].end}],
        }
        for n, index in enumerate(claim_segments)
    ]
    extraction = persist_extraction_result(
        raw_record_id=transcript.raw_record_id,
        normalized_artifact_id=transcript.object_id,
        normalized=normalized.as_dict(),
        result=ExtractionResult(
            extractor_id="claims",
            extractor_version=1,
            source_content_identity=CONTENT_IDENTITY,
            output={"claims": claims},
            model_identity={"provider": "fixture", "model": "fixture"},
            created_at=datetime(2026, 10, 1, 9, 5, tzinfo=timezone.utc),
        ),
    )
    return derive_key_moments(transcript=transcript, item_ref=VIDEO_ID, claims_extraction=extraction), transcript


def _vault(tmp_path: Path) -> VaultContext:
    root = tmp_path / "vault"
    root.mkdir(parents=True, exist_ok=True)
    return VaultContext("selected", "vault-test", "Vault Test", str(root))


def _guard() -> WriteGuard:
    return WriteGuard(lambda: {"state": "healthy"})


def _install_fake_media_boundaries(
    monkeypatch: pytest.MonkeyPatch,
    *,
    rasters: dict[int, bytes] | None = None,
    duration: float | None = 1200.0,
    ffmpeg_fail_at: set[int] | None = None,
    info_extra: dict[str, Any] | None = None,
    stream_overflow: bool = False,
    empty_still: bool = False,
) -> dict[str, Any]:
    """Replace only yt-dlp and ffmpeg process boundaries beneath the production capture class."""

    calls: dict[str, Any] = {"ydl_options": [], "urls": [], "ffmpeg": []}

    class FakeYoutubeDL:
        def __init__(self, options: dict[str, Any]) -> None:
            calls["ydl_options"].append(options)
            self.options = options

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def extract_info(self, url: str, *, download: bool):
            assert download is True
            calls["urls"].append(url)
            info = {"id": VIDEO_ID, "duration": duration, "ext": "mp4", **(info_extra or {})}
            assert self.options["match_filter"](info, incomplete=True) is None
            if self.options["match_filter"](info, incomplete=False) is not None:
                return info  # yt-dlp skips a filtered download without writing media
            target = Path(self.options["outtmpl"].replace("%(ext)s", "mp4"))
            if stream_overflow:
                # A fragmented stream that ignores max_filesize: the progress hook must stop it.
                target.with_suffix(".mp4.part").write_bytes(VIDEO_BYTES)
                for hook in self.options["progress_hooks"]:
                    hook({"status": "downloading", "downloaded_bytes": frames_module.MAX_TEMP_MEDIA_BYTES + 1})
            target.write_bytes(VIDEO_BYTES)
            return info

    def fake_ffmpeg(args):
        calls["ffmpeg"].append(list(args))
        seconds = int(args[args.index("-ss") + 1])
        media = Path(args[args.index("-i") + 1])
        assert media.read_bytes() == VIDEO_BYTES, "ffmpeg must read the capture-owned temporary media"
        if ffmpeg_fail_at and seconds in ffmpeg_fail_at:
            return subprocess.CompletedProcess(args, 1, b"", b"decode error")
        if args[-1] == "pipe:1":
            raster = (rasters or {}).get(seconds, RASTERS["diagonal"])
            return subprocess.CompletedProcess(args, 0, raster, b"")
        Path(args[-1]).write_bytes(b"" if empty_still else _jpeg(seconds))
        return subprocess.CompletedProcess(args, 0, b"", b"")

    monkeypatch.setattr(frames_module, "_youtube_dl", FakeYoutubeDL)
    monkeypatch.setattr(frames_module, "_run_ffmpeg", fake_ffmpeg)
    return calls


def _inventory(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


# --- AC1 -----------------------------------------------------------------------------------------

def test_capture_call_site_retains_context_frame_by_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    moments, transcript = _moments()
    assert len(moments.moments) >= 2
    calls = _install_fake_media_boundaries(monkeypatch)
    vault = _vault(tmp_path)

    # No media_capture, no opt-in flag: the default production path attempts bounded capture.
    result = capture_source_frames(
        key_moments=moments, transcript=transcript, item_ref=VIDEO_ID,
        vault_context=vault, write_guard=_guard(), temp_root=tmp_path / "media-tmp",
    )

    assert result.status == "frames_retained"
    assert len(result.frames) == 1
    context = result.frames[0]
    assert context["frame_role"] == "context_frame"
    # The context frame is the strongest-evidence moment (two claims at 300s), not a timeline sample.
    top = max(moments.moments, key=lambda m: (m["score"], -m["timestamp_seconds"]))
    assert context["moment_id"] == top["moment_id"] and context["timestamp_seconds"] == 300
    # Without a visual-necessity result, every other moment is rejected rather than captured.
    assert result.rejected["visual_necessity_not_met"] == len(moments.moments) - 1
    assert (Path(vault.active_vault_path) / context["path"]).read_bytes() == _jpeg(300)
    assert context["path"].startswith(
        f"Sources/YouTube/_attachments/yt-{VIDEO_ID}/content-frames-fixture-v"
    )

    # Bounded egress: exactly one low-resolution, size-capped, single-video download.
    assert calls["urls"] == [f"https://www.youtube.com/watch?v={VIDEO_ID}"]
    (options,) = calls["ydl_options"]
    assert options["max_filesize"] == frames_module.MAX_TEMP_MEDIA_BYTES
    assert "height<=360" in options["format"] and options["noplaylist"] is True
    # Every format alternative is a size-bounded progressive HTTP(S) file, never HLS/DASH fragments.
    for alternative in options["format"].split("/"):
        assert "[protocol^=http]" in alternative and "[filesize<?256M]" in alternative, alternative
    assert len(options["progress_hooks"]) == 1
    assert options["outtmpl"].startswith(str(tmp_path / "media-tmp"))
    assert len(calls["ffmpeg"]) == 2  # one still + one pHash raster for the single context frame

    # Replay/text-only rerun never recaptures: the retained manifest is the durable outcome.
    monkeypatch.setattr(frames_module, "_youtube_dl", lambda *_a, **_k: pytest.fail("recapture attempted"))
    again = capture_source_frames(
        key_moments=moments, transcript=transcript, item_ref=VIDEO_ID,
        vault_context=vault, write_guard=_guard(), temp_root=tmp_path / "media-tmp",
    )
    assert again.status == "already_captured" and again.manifest_path == result.manifest_path


# --- AC2 -----------------------------------------------------------------------------------------

def test_context_frame_is_retained_when_capture_succeeds_and_failure_degrades_to_timestamps_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    moments, transcript = _moments()
    original = [dict(m) for m in moments.moments]

    def run(name: str, **kwargs: Any):
        vault = _vault(tmp_path / name)
        result = capture_source_frames(
            key_moments=moments, transcript=transcript, item_ref=VIDEO_ID,
            vault_context=vault, write_guard=_guard(), temp_root=tmp_path / name / "tmp", **kwargs,
        )
        return result, Path(vault.active_vault_path)

    # Success: exactly one contextual frame.
    _install_fake_media_boundaries(monkeypatch)
    ok, ok_vault = run("success")
    assert ok.status == "frames_retained" and [f["frame_role"] for f in ok.frames] == ["context_frame"]
    assert ok.frame_for(ok.frames[0]["moment_id"]) == ok.frames[0]

    failures: dict[str, Any] = {}
    # Unavailable media (download raises).
    class Unavailable:
        def download_temporary_media(self, **_kw):
            raise MediaUnavailableError("video is private")

        def extract_frame(self, **_kw):
            raise AssertionError("no extraction without media")

    failures["unavailable"] = run("unavailable", media_capture=Unavailable())
    # Over-bound source: the production duration filter suppresses the download.
    _install_fake_media_boundaries(monkeypatch, duration=frames_module.MAX_SOURCE_DURATION_SECONDS + 1)
    failures["over_bound"] = run("over_bound")
    # Unknown duration and live/upcoming streams fail closed before any download.
    _install_fake_media_boundaries(monkeypatch, duration=None)
    failures["unknown_duration"] = run("unknown_duration")
    _install_fake_media_boundaries(monkeypatch, info_extra={"is_live": True, "live_status": "is_live"})
    failures["live"] = run("live")
    # A stream that ignores max_filesize is stopped by the byte-bound progress hook.
    _install_fake_media_boundaries(monkeypatch, stream_overflow=True)
    failures["stream_overflow"] = run("stream_overflow")
    # Frame decode failure, or an empty still, for the context moment.
    _install_fake_media_boundaries(monkeypatch, ffmpeg_fail_at={300})
    failures["decode"] = run("decode")
    _install_fake_media_boundaries(monkeypatch, empty_still=True)
    failures["empty_still"] = run("empty_still")
    # Media fetcher returning a path outside the capture-owned temp directory is refused.
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(VIDEO_BYTES)

    class Escaping:
        def download_temporary_media(self, **_kw):
            return outside

        def extract_frame(self, **_kw):
            raise AssertionError("escaped media must not be decoded")

    failures["escaped"] = run("escaped", media_capture=Escaping())

    for name, (result, vault_root) in failures.items():
        assert result.status == "timestamps_only", name
        assert result.degraded_reason and result.degraded_reason.startswith("capture_failed"), name
        assert result.frames == () and result.frame_for(original[0]["moment_id"]) is None, name
        # No placeholder: nothing at all is written to the vault on a degraded capture.
        assert _inventory(vault_root) == {}, name
        assert result.deletion_receipt["status"] == "deleted", name
        stored = ObjectStore().get_object(result.object_id)
        assert stored is not None and stored.payload["extensions"]["status"] == "timestamps_only"
        assert stored.payload["extensions"]["frames"] == []
    assert outside.read_bytes() == VIDEO_BYTES  # a foreign path is never deleted or adopted

    # A failing visual-necessity judgement never admits a frame and never fails the capture.
    _install_fake_media_boundaries(monkeypatch)

    def broken_predicate(_moment, _frame):
        raise RuntimeError("classifier unavailable")

    judged, _ = run("broken_predicate", visual_necessity=broken_predicate)
    assert judged.status == "frames_retained" and [f["frame_role"] for f in judged.frames] == ["context_frame"]
    assert judged.rejected["visual_necessity_not_met"] == len(original) - 1

    # Replay context: egress blocked means no capture attempt at all, and no failure.
    monkeypatch.setattr(frames_module, "_youtube_dl", lambda *_a, **_k: pytest.fail("egress during replay"))
    with block_source_egress():
        replay, replay_vault = run("replay")
    assert (replay.status, replay.degraded_reason, replay.frames) == ("timestamps_only", "source_egress_blocked", ())
    assert _inventory(replay_vault) == {}

    # The moments themselves are never altered by capture success or failure.
    assert [dict(m) for m in moments.moments] == original
    stored_moments = ObjectStore().get_object(moments.object_id)
    assert [m for m in stored_moments.payload["extensions"]["moments"]] == original
    for moment in original:
        assert {"frame", "frames", "frame_ref", "placeholder"}.isdisjoint(moment)

    # Inconsistent lineage fails loudly instead of attaching frames to foreign moments.
    with pytest.raises(SourceFramesError):
        capture_source_frames(
            key_moments=moments, transcript=transcript, item_ref="otherVideo1",
            vault_context=_vault(tmp_path / "lineage"), write_guard=_guard(),
        )


# --- AC3 -----------------------------------------------------------------------------------------

def test_temporary_video_deletion_leaves_only_retained_frames_with_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    moments, transcript = _moments()
    _install_fake_media_boundaries(
        monkeypatch, rasters={300: RASTERS["scene"], 30: RASTERS["checker"], 600: RASTERS["vertical"]}
    )
    vault = _vault(tmp_path)
    temp_root = tmp_path / "media-tmp"
    temp_root.mkdir()

    result = capture_source_frames(
        key_moments=moments, transcript=transcript, item_ref=VIDEO_ID,
        vault_context=vault, write_guard=_guard(), temp_root=temp_root,
        visual_necessity=lambda _moment, _frame: True,
    )
    assert result.status == "frames_retained" and len(result.frames) == MAX_RETAINED_FRAMES

    # Fixture-level byte inventory after cleanup: the temp root is empty and the vault holds
    # exactly the retained frames plus their manifest; no video bytes survive anywhere.
    assert _inventory(temp_root) == {} and list(temp_root.iterdir()) == []
    vault_files = _inventory(Path(vault.active_vault_path))
    assert set(vault_files) == {f["path"] for f in result.frames} | {result.manifest_path}
    for name, payload in {**vault_files, **_inventory(tmp_path)}.items():
        assert VIDEO_MARKER not in payload, name
    for frame in result.frames:
        assert vault_files[frame["path"]] == _jpeg(frame["timestamp_seconds"])

    receipt = result.deletion_receipt
    stills = sum(len(_jpeg(s)) for s in {int(c["timestamp_seconds"]) for c in moments.moments})
    assert receipt["receipt_type"] == "temporary_media_deletion" and receipt["status"] == "deleted"
    assert receipt["remaining_entries"] == 0
    assert receipt["deleted_bytes"] >= len(VIDEO_BYTES) and receipt["deleted_bytes"] <= len(VIDEO_BYTES) + stills
    manifest = json.loads(vault_files[result.manifest_path])
    assert manifest["deletion_receipt"] == receipt
    stored = ObjectStore().get_object(result.object_id)
    assert stored.payload["extensions"]["deletion_receipt"] == receipt

    # Negative: a cleanup that cannot prove deletion fails visibly, never returns success.
    moments2, transcript2 = _moments(claim_segments=(3, 30, 30, 60))
    _install_fake_media_boundaries(monkeypatch)
    real_rmdir = os.rmdir

    def stuck_rmdir(path, *args, **kwargs):
        if Path(path).name.startswith("ysnv2-frames-"):
            raise OSError("device busy")
        return real_rmdir(path, *args, **kwargs)

    monkeypatch.setattr(frames_module.os, "rmdir", stuck_rmdir)
    monkeypatch.setattr(frames_module.shutil, "rmtree", lambda *_a, **_k: None)
    stuck_vault = _vault(tmp_path / "stuck")
    with pytest.raises(SourceFramesError, match="cleanup failed"):
        capture_source_frames(
            key_moments=moments2, transcript=transcript2, item_ref=VIDEO_ID,
            vault_context=stuck_vault, write_guard=_guard(), temp_root=tmp_path / "stuck-tmp",
        )
    # Cleanup precedes vault writes, so a failed cleanup leaves no retained frame either.
    assert _inventory(Path(stuck_vault.active_vault_path)) == {}


# --- AC4 -----------------------------------------------------------------------------------------

def test_retained_frames_have_exception_metadata_and_phash_deduplication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # pHash sanity: deterministic, near-duplicates are close, distinct content is far.
    assert perceptual_hash(RASTERS["scene"]) == perceptual_hash(RASTERS["scene"])
    assert RASTERS["scene"] != RASTERS["scene_noisy"]
    near = phash_distance(perceptual_hash(RASTERS["scene"]), perceptual_hash(RASTERS["scene_noisy"]))
    assert near <= PHASH_DUPLICATE_DISTANCE
    for other in ("checker", "vertical", "rings"):
        assert phash_distance(perceptual_hash(RASTERS["scene"]), perceptual_hash(RASTERS[other])) > PHASH_DUPLICATE_DISTANCE
    with pytest.raises(FrameExtractionError):
        perceptual_hash(b"\x00" * 10)

    moments, transcript = _moments()
    by_time = {m["timestamp_seconds"]: m for m in moments.moments}
    assert set(by_time) == {30, 300, 600, 900, 1100}
    rasters = {
        300: RASTERS["scene"],  # context frame (two claims)
        30: RASTERS["scene_noisy"],  # perceptual duplicate of the context frame
        600: RASTERS["checker"],
        900: RASTERS["vertical"],
        1100: RASTERS["diagonal"],  # beyond the retained-frame cap
    }
    calls = _install_fake_media_boundaries(monkeypatch, rasters=rasters)
    judged: list[int] = []

    def necessary(moment, frame: CapturedFrame) -> bool:
        judged.append(moment["timestamp_seconds"])
        return frame.image_bytes.startswith(b"\xff\xd8")

    vault = _vault(tmp_path)
    result = capture_source_frames(
        key_moments=moments, transcript=transcript, item_ref=VIDEO_ID,
        vault_context=vault, write_guard=_guard(), temp_root=tmp_path / "tmp",
        visual_necessity=necessary,
    )

    assert result.status == "frames_retained"
    assert [(f["timestamp_seconds"], f["frame_role"]) for f in result.frames] == [
        (300, "context_frame"), (600, "visual_necessity"), (900, "visual_necessity"),
    ]
    assert len(result.frames) == MAX_RETAINED_FRAMES
    assert result.rejected == {"visual_necessity_not_met": 0, "duplicate_phash": 1, "cap": 1, "extraction_failed": 0}
    assert 1100 not in judged and 1100 not in {int(a[a.index("-ss") + 1]) for a in calls["ffmpeg"]}
    phashes = [f["phash"] for f in result.frames]
    assert len(set(phashes)) == len(phashes)

    for frame in result.frames:
        assert frame["media_role"] == "media_derivative"
        assert frame["regenerability"] == "source_dependent"
        assert frame["usage_rights"] == "personal_use_only"
        assert frame["sensitivity"] == "internal"
        assert frame["publishable"] is False
        assert frame["media_type"] == "image/jpeg"
        assert frame["phash"] == perceptual_hash(rasters[frame["timestamp_seconds"]])
        lineage = frame["lineage"]
        assert lineage["content_identity"] == CONTENT_IDENTITY
        assert lineage["source_url"] == f"https://www.youtube.com/watch?v={VIDEO_ID}&t={frame['timestamp_seconds']}s"
        assert lineage["derived_from"] == [RAW_ID, transcript.object_id, moments.object_id, frame["moment_id"]]
        assert frame["moment_id"] == by_time[frame["timestamp_seconds"]]["moment_id"]
        on_disk = (Path(vault.active_vault_path) / frame["path"]).read_bytes()
        assert frame["byte_size"] == len(on_disk)

    manifest = json.loads((Path(vault.active_vault_path) / result.manifest_path).read_text())
    assert manifest["media_role"] == "media_derivative" and manifest["regenerability"] == "source_dependent"
    assert manifest["usage_rights"] == "personal_use_only" and manifest["publishable"] is False
    assert manifest["frames"] == list(result.frames)

    stored = ObjectStore().get_object(result.object_id)
    assert stored is not None and stored.kind == SOURCE_FRAMES_ARTIFACT_KIND
    bundle = dict(stored.payload)
    assert_validates(bundle, "metadata-bundle.schema.json")
    assert bundle["authority_state"] == "derived" and bundle["sensitivity"] == "internal"
    assert bundle["derived_from"] == [RAW_ID, transcript.object_id, moments.object_id]
    assert bundle["extensions"]["regenerability"] == "source_dependent"
    assert bundle["extensions"]["frames"] == list(result.frames)
