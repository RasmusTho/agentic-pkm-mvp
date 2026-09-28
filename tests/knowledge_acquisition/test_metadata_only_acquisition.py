"""Production-path proofs for the YouTube metadata-only acquisition slice (#5722)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
import uuid

import pytest

from app import objects as object_store_module
from app.knowledge_acquisition import youtube_plugin as plugin
from app.knowledge_acquisition.acquisition_requests import (
    AcquisitionRequests,
    DiscoveryTrigger,
    drain_one,
    reset_memory_acquisition_requests,
)
from app.knowledge_acquisition.acquire import acquire_youtube
from app.knowledge_acquisition.replay import run_replay
from app.knowledge_acquisition.youtube_plugin import MetadataAcquisitionError
from app.stores import reset_store_backends
from app.vault.manager import VaultContext
from app.write_guard import WriteGuard

pytestmark = pytest.mark.not_pg

VIDEO_ID = "abcdefghijk"
VIDEO_URL = f"https://www.youtube.com/watch?v={VIDEO_ID}"


class _FakeCursor:
    def __init__(self, rows: list[tuple[Any, ...]]):
        self._rows = rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class FakeOutboxConn:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}

    def execute(self, sql: str, params: tuple = ()) -> _FakeCursor:
        text = " ".join(sql.lower().split())
        if text.startswith("insert into outbox (id,"):
            row_id, topic, payload, created_at, attempts, legacy_key, vault_binding_id, *_ = params
            if row_id in self.rows:
                return _FakeCursor([])
            self.rows[row_id] = {
                "id": row_id,
                "topic": topic,
                "payload": payload,
                "created_at": created_at,
                "attempts": attempts,
                "legacy_key": legacy_key,
                "vault_binding_id": vault_binding_id,
            }
            return _FakeCursor([(row_id,)])
        raise AssertionError(f"unexpected SQL shape: {text!r}")

    def payloads_for(self, topic: str) -> list[dict[str, Any]]:
        return [row["payload"] for row in self.rows.values() if row["topic"] == topic]


def _info(**overrides: Any) -> dict[str, Any]:
    result: dict[str, Any] = {
        "id": VIDEO_ID,
        "title": "Metadata Test Video",
        "channel": "Metadata Channel",
        "channel_id": "UCmetadata",
        "upload_date": "20260928",
        "duration": 321,
        "description": "Metadata description",
        "chapters": [{"start_time": 0, "title": "Opening"}],
        "tags": ["metadata", "test"],
        "language": "en",
        "thumbnail": "https://example.com/thumb.jpg",
        "subtitles": {"en": [{"ext": "vtt", "url": "https://example.com/caption.vtt"}]},
        "automatic_captions": {},
    }
    result.update(overrides)
    return result


def _trigger() -> DiscoveryTrigger:
    return DiscoveryTrigger(
        binding_id=str(uuid.uuid4()),
        collection_kind="subscription_feed",
        collection_ref="subscriptions",
        trigger="poll",
    )


def _queue() -> AcquisitionRequests:
    return AcquisitionRequests.for_runtime()


def _enqueue(
    queue: AcquisitionRequests,
    conn: FakeOutboxConn,
    *,
    item_ref: str = VIDEO_ID,
    policy_snapshot: dict[str, Any] | None = None,
) -> Any:
    return queue.enqueue(
        source_kind="youtube_url",
        item_ref=item_ref,
        source_ref=f"https://www.youtube.com/watch?v={item_ref}",
        trigger=_trigger(),
        policy_snapshot=policy_snapshot
        or {"policy_version": 1, "mode": "candidate_metadata_only", "captions": True},
        conn=conn,
    )


def _vault(path: Path) -> VaultContext:
    path.mkdir(parents=True, exist_ok=True)
    return VaultContext(
        status="selected",
        active_vault_id="metadata-test",
        active_vault_name="Metadata Test",
        active_vault_path=str(path),
    )


def _allowing_guard() -> WriteGuard:
    return WriteGuard(lambda: {"state": "healthy"})


@pytest.fixture(autouse=True)
def _memory_backend(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost:5432/app_test")
    reset_store_backends()
    reset_memory_acquisition_requests()
    object_store_module._MEMORY_STORE.clear()
    yield
    reset_store_backends()
    reset_memory_acquisition_requests()
    object_store_module._MEMORY_STORE.clear()


def test_drain_materializes_metadata_only_without_transcript_or_extractors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = {"metadata": 0, "caption": 0, "transcribe": 0, "extractor": 0}

    def metadata_fetch(url: str) -> dict[str, Any]:
        calls["metadata"] += 1
        return _info()

    monkeypatch.setattr(plugin, "yt_dlp_extract_metadata", metadata_fetch)
    monkeypatch.setattr(plugin, "yt_dlp_extract_info", lambda _url: (_ for _ in ()).throw(AssertionError("transcript metadata seam called")))
    monkeypatch.setattr(plugin, "fetch_caption_body", lambda _url: (_ for _ in ()).throw(AssertionError("caption seam called")))
    monkeypatch.setattr(plugin, "transcribe_source", lambda _url: (_ for _ in ()).throw(AssertionError("ASR seam called")))

    conn = FakeOutboxConn()
    queue = _queue()
    row = _enqueue(queue, conn)
    claimed = queue.claim_batch(1, conn=conn)
    result = drain_one(
        claimed[0],
        vault_context=_vault(tmp_path / "vault"),
        queue=queue,
        write_guard=_allowing_guard(),
        conn=conn,
    )

    assert result.status == "completed"
    assert result.content_identity is not None
    assert result.content_identity.startswith("youtube-metadata-v1:sha256:")
    assert calls == {"metadata": 1, "caption": 0, "transcribe": 0, "extractor": 0}
    assert row.request_id == result.request_id
    note_paths = list((tmp_path / "vault").rglob("*.md"))
    assert len(note_paths) == 1
    note = note_paths[0].read_text(encoding="utf-8")
    assert "transcript_available: false" in note
    assert "requires_review: true" in note
    assert "review_state: draft" in note
    assert "triage_state: captured" in note
    assert "Metadata Test Video" in note
    assert "Metadata Channel" in note
    assert "youtube-metadata-v1:sha256:" in note
    assert "**Derived transcript:** not materialized" in note
    assert "### Summary" not in note
    assert "### Claims" not in note


def test_metadata_identity_and_first_write_wins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = _info()
    monkeypatch.setattr(plugin, "yt_dlp_extract_metadata", lambda _url: current)
    conn = FakeOutboxConn()

    from app.knowledge_acquisition.acquire import acquire_metadata_only

    first = acquire_metadata_only(
        VIDEO_URL, vault_context=_vault(tmp_path / "vault"), conn=conn
    )
    first_path = next((tmp_path / "vault").rglob("*.md"))
    first_bytes = first_path.read_bytes()
    first_path.write_bytes(first_bytes + b"\nOwner edit.\n")
    second = acquire_metadata_only(
        VIDEO_URL, vault_context=_vault(tmp_path / "vault"), conn=conn
    )
    assert first.content_identity == second.content_identity
    assert first_path.read_bytes() == first_bytes + b"\nOwner edit.\n"

    current = _info(title="Metadata Test Video v2")
    changed = acquire_metadata_only(
        VIDEO_URL, vault_context=_vault(tmp_path / "vault"), conn=conn
    )
    assert changed.content_identity != first.content_identity
    assert len(list((tmp_path / "vault").rglob("*.md"))) == 2

    caption_body = "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nTranscript\n"
    monkeypatch.setattr(plugin, "yt_dlp_extract_info", lambda _url: _info())
    monkeypatch.setattr(plugin, "fetch_caption_body", lambda _url: caption_body)
    transcript = acquire_youtube(
        VIDEO_URL,
        vault_context=_vault(tmp_path / "vault"),
        extractor_ids=(),
        conn=conn,
    )
    assert transcript.content_identity != first.content_identity
    assert first_path.read_bytes() == first_bytes + b"\nOwner edit.\n"


def test_metadata_candidate_truth_and_lineage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(plugin, "yt_dlp_extract_metadata", lambda _url: _info())
    conn = FakeOutboxConn()
    from app.knowledge_acquisition.acquire import acquire_metadata_only

    receipt = acquire_metadata_only(
        VIDEO_URL, vault_context=_vault(tmp_path / "vault"), conn=conn
    )
    objects = list(object_store_module._MEMORY_STORE.values())
    raw = next(item for item in objects if item.kind == "knowledge_acquisition.raw")
    normalized = next(item for item in objects if item.kind == "knowledge_acquisition.normalized_metadata")
    note = next((tmp_path / "vault").rglob("*.md")).read_text(encoding="utf-8")
    assert receipt.raw_record_id == str(raw.uuid)
    assert f"raw_record_id: {raw.uuid}" in note
    assert f"normalized_artifact_id: {normalized.uuid}" in note
    assert "extraction_artifact_ids" not in note
    assert "transcript_available: false" in note
    assert "**Transcript:** unavailable" in note


def test_metadata_replay_is_egress_free_and_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.knowledge_acquisition.acquire import acquire_metadata_only

    monkeypatch.setattr(plugin, "yt_dlp_extract_metadata", lambda _url: _info())
    conn = FakeOutboxConn()
    original = acquire_metadata_only(
        VIDEO_URL, vault_context=_vault(tmp_path / "vault"), conn=conn
    )
    note_path = next((tmp_path / "vault").rglob("*.md"))
    note_bytes = note_path.read_bytes()
    monkeypatch.setattr(plugin, "yt_dlp_extract_metadata", lambda _url: (_ for _ in ()).throw(AssertionError("replay egress")))
    replay = run_replay(
        original.raw_record_id,
        vault_context=_vault(tmp_path / "vault"),
        conn=conn,
        assert_no_source_egress=True,
    )
    assert replay.source_egress == 0
    assert replay.equivalent is True
    assert any(stage.stage == "normalize_metadata" and stage.status == "ok" for stage in replay.stages)
    assert any(stage.stage == "candidate" and stage.status == "already_exists" for stage in replay.stages)
    assert note_path.read_bytes() == note_bytes


def test_metadata_drain_failure_retry_and_writeguard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(plugin, "yt_dlp_extract_metadata", lambda _url: _info())
    conn = FakeOutboxConn()
    queue = _queue()
    row = _enqueue(queue, conn)
    claimed = queue.claim_batch(1, conn=conn)
    blocked = drain_one(
        claimed[0],
        vault_context=_vault(tmp_path / "vault"),
        queue=queue,
        write_guard=WriteGuard(lambda: {"state": "safe_mode", "reason": "test"}),
        conn=conn,
    )
    assert blocked.status == "pending"
    assert blocked.completed_at is None
    assert blocked.last_failure["reason_code"] == "writeguard_blocked"
    retry = queue.claim_batch(1, now=datetime.now(timezone.utc) + timedelta(hours=7), conn=conn)
    assert retry and retry[0].request_id == row.request_id
    done = drain_one(
        retry[0],
        vault_context=_vault(tmp_path / "vault"),
        queue=queue,
        write_guard=_allowing_guard(),
        conn=conn,
    )
    assert done.status == "completed"
    assert len(list((tmp_path / "vault").rglob("*.md"))) == 1

    failing = _enqueue(queue, conn, item_ref="lmnopqrstuv")
    claimed_failure = queue.claim_batch(1, now=datetime.now(timezone.utc) + timedelta(hours=7), conn=conn)
    monkeypatch.setattr(plugin, "yt_dlp_extract_metadata", lambda _url: (_ for _ in ()).throw(MetadataAcquisitionError("HTTP 503")))
    failure = drain_one(
        next(item for item in claimed_failure if item.request_id == failing.request_id),
        vault_context=_vault(tmp_path / "vault"),
        queue=queue,
        conn=conn,
    )
    assert failure.status == "pending"
    assert failure.completed_at is None
    assert failure.last_failure["reason_code"] == "network_error"


def test_metadata_policy_validation_and_unsupported_mode_guards(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.knowledge_acquisition.acquisition_requests import (
        AcquisitionRequestValidationError,
    )

    conn = FakeOutboxConn()
    queue = _queue()
    with pytest.raises(AcquisitionRequestValidationError, match="classify every selected"):
        _enqueue(
            queue,
            conn,
            policy_snapshot={
                "policy_version": 1,
                "mode": "candidate_metadata_only",
                "extractor_ids": ["summary"],
                "extractor_requirements": {"claims": "optional"},
            },
        )

    incompatible = _enqueue(
        queue,
        conn,
        policy_snapshot={
            "policy_version": 1,
            "mode": "candidate_metadata_only",
            "captions": True,
            "extractor_ids": ["summary"],
        },
    )
    monkeypatch.setattr(plugin, "yt_dlp_extract_metadata", lambda _url: (_ for _ in ()).throw(AssertionError("egress before policy validation")))
    result = drain_one(queue.claim_batch(1, conn=conn)[0], vault_context=None, queue=queue, conn=conn)
    assert result.request_id == incompatible.request_id
    assert result.status == "dead_lettered"
    assert result.last_failure["reason_code"] == "policy_unsupported"

    valid = _enqueue(
        queue,
        conn,
        item_ref="lmnopqrstuv",
        policy_snapshot={"policy_version": 1, "mode": "candidate_metadata_only", "captions": False},
    )
    monkeypatch.setattr(plugin, "yt_dlp_extract_metadata", lambda _url: _info(id="lmnopqrstuv"))
    claimed = queue.claim_batch(1, now=datetime.now(timezone.utc) + timedelta(hours=7), conn=conn)
    done = drain_one(
        claimed[0],
        vault_context=_vault(tmp_path / "vault"),
        queue=queue,
        conn=conn,
    )
    assert done.request_id == valid.request_id
    assert done.status == "completed"

    refused_policies = (
        (
            "mnopqrstuvw",
            {"policy_version": 1, "mode": "future_policy_mode"},
            "policy_unsupported",
        ),
        (
            "zyxwvutsrqp",
            {
                "policy_version": 1,
                "mode": "candidate_metadata_only",
                "media": {"enabled": True},
            },
            "media_policy_disabled",
        ),
        (
            "ponmlkjihgf",
            {"policy_version": 1, "mode": "acquire_transcript", "captions": False},
            "policy_unsupported",
        ),
    )
    for item_ref, policy_snapshot, reason_code in refused_policies:
        request = _enqueue(
            queue,
            conn,
            item_ref=item_ref,
            policy_snapshot=policy_snapshot,
        )
        claimed_refused = queue.claim_batch(
            1, now=datetime.now(timezone.utc) + timedelta(hours=7), conn=conn
        )
        assert claimed_refused[0].request_id == request.request_id
        refused = drain_one(
            claimed_refused[0], vault_context=None, queue=queue, conn=conn
        )
        assert refused.request_id == request.request_id
        assert refused.status == "dead_lettered"
        assert refused.last_failure["reason_code"] == reason_code
