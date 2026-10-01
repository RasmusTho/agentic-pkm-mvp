"""YSNV2 acquisition-time wiring of key moments and default frame capture (#5746).

Every test drives the production call sites ``acquire_youtube``, ``acquire_metadata_only`` and
``run_replay``.  Source egress is stubbed at the plugin seams (as in ``test_acquire.py``) and the
only media boundary is an injected ``SourceMediaCapture`` fake; the production yt-dlp/ffmpeg
boundaries beneath ``YtDlpFfmpegMediaCapture`` and real sockets are forbidden outright.
"""

from __future__ import annotations

import json
import math
import socket
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from app import objects as object_store_module
from app.knowledge_acquisition import source_frames as frames_module
from app.knowledge_acquisition import youtube_plugin as plugin
from app.knowledge_acquisition.acquire import (
    AcquisitionError,
    acquire_metadata_only,
    acquire_youtube,
)
from app.knowledge_acquisition.extraction_registry import clear_registry
from app.knowledge_acquisition.extractors import claims_extractor, summary_extractor, synthesis_extractor
from app.knowledge_acquisition.key_moments import KEY_MOMENTS_ARTIFACT_KIND
from app.knowledge_acquisition.replay import run_replay
from app.knowledge_acquisition.source_frames import (
    CapturedFrame,
    MediaUnavailableError,
    SourceFramesError,
)
from app.knowledge_acquisition.stage_events import STAGE_DEAD_LETTERED_TOPIC
from app.objects import ObjectStore
from app.stores import reset_store_backends
from tests.knowledge_acquisition.test_acquire import (
    FAKE_URL,
    VIDEO_ID,
    FakeOutboxConn,
    _allowing_guard,
    _stub_caption_fetch,
    _stub_completion,
    _vault,
)

pytestmark = pytest.mark.not_pg

MOMENTS_HEADING = "### Timestamped moments"
_RASTER = bytes(max(0, min(255, int(128 + 60 * math.sin(x / 5) + 50 * math.cos(y / 7)))) for y in range(32) for x in range(32))


def _jpeg(seconds: int) -> bytes:
    return b"\xff\xd8\xff\xe0" + f"still-{seconds}".encode() + b"\xff\xd9"


class FakeMediaCapture:
    """Injected media seam: records every egress attempt and never touches the network."""

    def __init__(self, *, fail_with: Exception | None = None) -> None:
        self.fail_with = fail_with
        self.downloads: list[str] = []
        self.extractions: list[int] = []

    def download_temporary_media(
        self, *, item_ref: str, dest_dir: Path, max_bytes: int, max_duration_seconds: int
    ) -> Path:
        self.downloads.append(item_ref)
        if self.fail_with is not None:
            raise self.fail_with
        media = dest_dir / "source-media.mp4"
        media.write_bytes(b"FAKE-MP4" * 64)
        return media

    def extract_frame(self, *, media_path: Path, timestamp_seconds: int, work_dir: Path) -> CapturedFrame:
        self.extractions.append(timestamp_seconds)
        return CapturedFrame(image_bytes=_jpeg(timestamp_seconds), grayscale_32=_RASTER)


@pytest.fixture(autouse=True)
def _extractors():
    clear_registry()
    summary_extractor.register(
        complete=_stub_completion(json.dumps({"summary": "A deterministic test summary.", "confidence": 0.75}))
    )
    synthesis_extractor.register(
        complete=_stub_completion(
            json.dumps({
                "synthesis_sentences": [{
                    "text": "The transcript describes a deterministic test.",
                    "anchors": [{"segment_index": 0, "start": 0.0, "end": 2.0}],
                }],
                "model_confidence": 0.8,
            })
        )
    )
    claims_extractor.register(
        complete=_stub_completion(
            json.dumps({
                "claims": [
                    {
                        "source_wording": "Hello world",
                        "system_paraphrase": "The source opens with a greeting.",
                        "anchors": [{"segment_index": 0, "start": 0.0, "end": 2.0}],
                    },
                    {
                        "source_wording": "This is a transcript about testing.",
                        "system_paraphrase": "The source describes testing.",
                        "anchors": [{"segment_index": 1, "start": 2.0, "end": 4.0}],
                    },
                ]
            })
        )
    )
    yield
    clear_registry()
    summary_extractor.register()
    synthesis_extractor.register()
    claims_extractor.register()


@pytest.fixture(autouse=True)
def _memory_store(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost:5432/app_test")
    reset_store_backends()
    object_store_module._MEMORY_STORE.clear()
    yield
    reset_store_backends()
    object_store_module._MEMORY_STORE.clear()


@pytest.fixture(autouse=True)
def _no_real_media_egress(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    attempts: list[str] = []

    def _forbidden(*_args: Any, **_kwargs: Any):
        attempts.append("real-media-boundary")
        raise AssertionError("wiring tests must not reach real network or media boundaries")

    monkeypatch.setattr(socket, "create_connection", _forbidden)
    monkeypatch.setattr(socket.socket, "connect", _forbidden)
    monkeypatch.setattr(plugin, "yt_dlp_extract_metadata", _forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", _forbidden)
    monkeypatch.setattr(frames_module, "_youtube_dl", _forbidden)
    monkeypatch.setattr(frames_module, "_run_ffmpeg", _forbidden)
    return attempts


def _acquire(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capture: Any, **kwargs: Any):
    _stub_caption_fetch(monkeypatch)
    vault = _vault(tmp_path / "vault")
    conn = kwargs.pop("conn", FakeOutboxConn())
    receipt = acquire_youtube(
        FAKE_URL, vault_context=vault, write_guard=_allowing_guard(), conn=conn, media_capture=capture, **kwargs
    )
    candidate = next(stage for stage in receipt.stages if stage.stage == "candidate")
    note = (Path(vault.active_vault_path) / str(candidate.artifact_path)).read_text(encoding="utf-8")
    return receipt, vault, note


def _persisted_moments() -> list[dict[str, Any]]:
    return [dict(obj.payload) for obj in ObjectStore().list_objects(kind=KEY_MOMENTS_ARTIFACT_KIND, limit=None)]


def _moments_section(note: str) -> str:
    start = note.index(MOMENTS_HEADING)
    end = note.find("\n### ", start + 1)
    evidence = note.index("## Evidence and lineage")
    return note[start : end if 0 < end < evidence else evidence]


def test_acquisition_renders_timestamped_moments_section_from_persisted_moments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    receipt, _vault_ctx, note = _acquire(tmp_path, monkeypatch, FakeMediaCapture())

    assert receipt.ok is True
    (stored,) = _persisted_moments()
    ext = stored["extensions"]
    assert ext["raw_record_id"] == receipt.raw_record_id and ext["item_ref"] == VIDEO_ID
    assert ext["claims_artifact_id"] is not None
    moments = ext["moments"]
    assert moments, "the claims extraction must yield at least one supported moment"

    # The section renders inside the shared proposals wrapper, after the universal spine.
    proposals = note.index("## Proposals (non-authoritative)")
    assert proposals < note.index("### Evidence-anchored claims") < note.index(MOMENTS_HEADING)
    assert note.index(MOMENTS_HEADING) < note.index("## Evidence and lineage")
    section = _moments_section(note)
    for moment in moments:
        seconds = moment["timestamp_seconds"]
        assert f"[{seconds // 60:02d}:{seconds % 60:02d}]" in section
        assert moment["timestamp_link"].replace("&", "&amp;") in section
        for anchor in moment["transcript_anchors"]:
            assert anchor["anchor"] in section
        assert moment["selection_rationale"] in section
    # Every section line is blockquoted proposal content, never owner-band prose.
    assert all(line.startswith(">") for line in section.splitlines()[1:] if line)
    assert f"key_moments={stored['object_id']}" in note


def test_acquisition_invokes_default_frame_capture_and_embeds_context_frame(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _no_real_media_egress: list[str]
) -> None:
    capture = FakeMediaCapture()
    receipt, vault, note = _acquire(tmp_path, monkeypatch, capture)

    assert receipt.ok is True
    # Default capture: no opt-in flag, exactly one bounded download for the acquisition.
    assert capture.downloads == [VIDEO_ID]
    vault_root = Path(vault.active_vault_path)
    (manifest_path,) = vault_root.rglob("frames.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    (frame,) = manifest["frames"]
    assert frame["frame_role"] == "context_frame"
    assert (vault_root / frame["path"]).read_bytes() == _jpeg(frame["timestamp_seconds"])

    section = _moments_section(note)
    seconds = frame["timestamp_seconds"]
    assert f"![Context frame at {seconds // 60:02d}:{seconds % 60:02d}]({frame['path']})" in section
    assert "![[" not in note
    assert "frames_retained" in note

    # Without an injected seam the production capture class is the default call site.
    other = tmp_path / "default"
    _no_real_media_egress.clear()
    default_receipt, _v, default_note = _acquire(other, monkeypatch, None)
    assert _no_real_media_egress == ["real-media-boundary"]
    assert default_receipt.ok is True
    assert MOMENTS_HEADING in default_note and "![" not in _moments_section(default_note)


def test_capture_failure_degrades_to_timestamps_only_and_metadata_only_skips_moments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _no_real_media_egress: list[str]
) -> None:
    capture = FakeMediaCapture(fail_with=MediaUnavailableError("video unavailable"))
    receipt, vault, note = _acquire(tmp_path / "failed", monkeypatch, capture)

    assert receipt.ok is True and capture.downloads == [VIDEO_ID]
    section = _moments_section(note)
    assert "](https://www.youtube.com/watch?v=" in section
    assert "![" not in section and "frame" not in section.lower()  # no placeholder
    assert not list(Path(vault.active_vault_path).rglob("*.jpg"))
    # Required evidence survives; the degradation is visible outside the moments section.
    assert "### Evidence-anchored synthesis" in note and "### Evidence-anchored claims" in note
    assert "timestamps-only (capture_failed: video unavailable)" in note
    assert "**Materialization status:** complete" in note

    # Infrastructure failures of the capture stage stay visible instead of a silent success.
    conn = FakeOutboxConn()
    broken = FakeMediaCapture(fail_with=SourceFramesError("temporary media cleanup failed"))
    with pytest.raises(AcquisitionError, match="temporary media cleanup failed"):
        _acquire(tmp_path / "broken", monkeypatch, broken, conn=conn)
    (dead,) = conn.rows_for(STAGE_DEAD_LETTERED_TOPIC)
    assert "source_frames_failed" in json.dumps(dead["payload"])
    # No candidate note materialized; only the derived bundle transcript exists.
    assert [p.name for p in (tmp_path / "broken" / "vault").rglob("*.md")] == ["transcript.md"]

    # Metadata-only acquisition: no moments section, no moments artifact, no capture attempt.
    object_store_module._MEMORY_STORE.clear()
    _no_real_media_egress.clear()
    monkeypatch.setattr(
        plugin,
        "yt_dlp_extract_metadata",
        lambda url: {"id": VIDEO_ID, "title": "Metadata only", "channel": "Test Channel", "duration": 600},
    )
    meta_vault = _vault(tmp_path / "meta")
    meta = acquire_metadata_only(FAKE_URL, vault_context=meta_vault, write_guard=_allowing_guard(), conn=FakeOutboxConn())
    assert meta.ok is True
    meta_stage = next(stage for stage in meta.stages if stage.stage == "candidate")
    meta_note = (Path(meta_vault.active_vault_path) / str(meta_stage.artifact_path)).read_text(encoding="utf-8")
    assert MOMENTS_HEADING not in meta_note and "Key moments" not in meta_note
    assert _persisted_moments() == []
    assert _no_real_media_egress == []


def test_replay_does_not_recapture_frames_or_egress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _no_real_media_egress: list[str]
) -> None:
    capture = FakeMediaCapture()
    conn = FakeOutboxConn()
    receipt, vault, original_note = _acquire(tmp_path, monkeypatch, capture, conn=conn)
    vault_root = Path(vault.active_vault_path)
    before = {p.relative_to(vault_root).as_posix(): p.read_bytes() for p in vault_root.rglob("*.jpg")}
    assert len(before) == 1 and capture.downloads == [VIDEO_ID]

    # Any source/media egress during replay fails the test loudly.
    monkeypatch.setattr(plugin, "yt_dlp_extract_info", lambda url: pytest.fail("replay fetched the source"))
    monkeypatch.setattr(plugin, "fetch_caption_body", lambda url: pytest.fail("replay fetched captions"))
    replayed = run_replay(receipt.raw_record_id, vault_context=vault, write_guard=_allowing_guard(), conn=conn)

    assert replayed.source_egress == 0
    candidate = next(stage for stage in replayed.stages if stage.stage == "candidate")
    assert candidate.status == "proposal_written"
    companion = (vault_root / str(candidate.artifact_path)).read_text(encoding="utf-8")
    section = _moments_section(companion)
    # The retained frame is re-referenced from its durable manifest, never recaptured.
    (frame_path,) = before
    assert f"]({frame_path})" in section
    assert capture.downloads == [VIDEO_ID] and _no_real_media_egress == []
    after = {p.relative_to(vault_root).as_posix(): p.read_bytes() for p in vault_root.rglob("*.jpg")}
    assert after == before
    # The original candidate stays byte-identical (first-write-wins).
    original_stage = next(stage for stage in receipt.stages if stage.stage == "candidate")
    assert (vault_root / str(original_stage.artifact_path)).read_text(encoding="utf-8") == original_note

    # A repeated replay (text-only re-rendering of the same candidate) still never recaptures.
    again = run_replay(receipt.raw_record_id, vault_context=vault, write_guard=_allowing_guard(), conn=conn)
    assert again.source_egress == 0
    assert capture.downloads == [VIDEO_ID] and _no_real_media_egress == []
