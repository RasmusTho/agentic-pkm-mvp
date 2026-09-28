"""Production-path proofs for the YouTube metadata-only acquisition slice (#5722)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Any
import uuid

import pytest

from app import objects as object_store_module
from app.knowledge_acquisition import candidate_writeback
from app.knowledge_acquisition import youtube_plugin as plugin
from app.knowledge_acquisition.acquisition_requests import (
    ACQUISITION_FAILED_TOPIC,
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
    monkeypatch.setattr(
        candidate_writeback,
        "run_extractor",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("extractor seam called")),
    )

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

    other_url = "https://www.youtube.com/watch?v=lmnopqrstuv"
    other = acquire_metadata_only(
        other_url, vault_context=_vault(tmp_path / "vault"), conn=conn
    )
    assert other.content_identity != first.content_identity
    assert other.raw_record_id != changed.raw_record_id
    assert other.content_identity != changed.content_identity
    assert len(list((tmp_path / "vault").rglob("*.md"))) == 5


def test_metadata_candidate_path_uses_final_digest_component() -> None:
    def make_candidate(identity: str) -> Any:
        return candidate_writeback.Candidate(
            content_identity=identity,
            source_kind="youtube_url",
            item_ref=VIDEO_ID,
            url=VIDEO_URL,
            title="Metadata Test Video",
            creator="Metadata Channel",
            published="20260928",
            acquisition_method="metadata_only",
            transcript_available=False,
            extractions=(),
        )

    prefix = "youtube-metadata-v1:sha256:"
    path_a = candidate_writeback.candidate_note_path(
        make_candidate(prefix + "a" * 15 + "1" + "0" * 48)
    )
    path_b = candidate_writeback.candidate_note_path(
        make_candidate(prefix + "a" * 15 + "2" + "0" * 48)
    )

    assert path_a != path_b
    assert "youtube-metadata" not in path_a.rsplit("/", 1)[-1]


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

    from app.knowledge_acquisition.raw_record import RawRecordIntegrityError

    integrity = _enqueue(queue, conn, item_ref="zyxwvutsrqp")
    claimed_integrity = queue.claim_batch(
        20, now=datetime.now(timezone.utc) + timedelta(hours=7), conn=conn
    )

    def fail_raw_fetch(_url: str) -> Any:
        raise RawRecordIntegrityError("occupied raw identity")

    monkeypatch.setattr(plugin, "fetch_metadata", fail_raw_fetch)
    integrity_result = drain_one(
        next(item for item in claimed_integrity if item.request_id == integrity.request_id),
        vault_context=_vault(tmp_path / "vault"),
        queue=queue,
        conn=conn,
    )
    assert integrity_result.status == "dead_lettered"
    assert integrity_result.last_failure["reason_code"] == "pipeline_configuration_or_persistence"


def test_writeguard_block_remains_retryable_after_attempt_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(plugin, "yt_dlp_extract_metadata", lambda _url: _info())
    conn = FakeOutboxConn()
    queue = AcquisitionRequests.for_runtime(max_attempts=1)
    row = _enqueue(queue, conn)

    blocked = drain_one(
        queue.claim_batch(1, conn=conn)[0],
        vault_context=_vault(tmp_path / "vault"),
        queue=queue,
        write_guard=WriteGuard(lambda: {"state": "safe_mode", "reason": "test"}),
        conn=conn,
    )
    assert blocked.status == "pending"
    assert blocked.attempts == 1
    assert blocked.last_failure["reason_code"] == "writeguard_blocked"
    failure_event = json.loads(conn.payloads_for(ACQUISITION_FAILED_TOPIC)[-1])
    failure_payload = failure_event["payload"]
    assert failure_payload["terminal"] is False

    retry = queue.claim_batch(
        1, now=datetime.now(timezone.utc) + timedelta(hours=7), conn=conn
    )
    assert len(retry) == 1 and retry[0].request_id == row.request_id
    assert retry[0].attempts == 2
    completed = drain_one(
        retry[0],
        vault_context=_vault(tmp_path / "vault"),
        queue=queue,
        write_guard=_allowing_guard(),
        conn=conn,
    )
    assert completed.status == "completed"


def test_ytdlp_metadata_fetch_disables_captions_and_media_download(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    expected = _info()

    class FakeYoutubeDL:
        def __init__(self, options: dict[str, Any]) -> None:
            captured["options"] = options

        def __enter__(self) -> "FakeYoutubeDL":
            return self

        def __exit__(self, *_args: Any) -> None:
            return None

        def extract_info(self, url: str, *, download: bool) -> dict[str, Any]:
            captured["url"] = url
            captured["download"] = download
            return expected

    monkeypatch.setattr(plugin, "assert_source_egress_allowed", lambda _boundary: None)
    monkeypatch.setitem(sys.modules, "yt_dlp", SimpleNamespace(YoutubeDL=FakeYoutubeDL))

    assert plugin.yt_dlp_extract_metadata(VIDEO_URL) == expected
    assert captured["options"]["skip_download"] is True
    assert captured["options"]["writesubtitles"] is False
    assert captured["options"]["writeautomaticsub"] is False
    assert captured["download"] is False
    assert captured["url"] == VIDEO_URL


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

    from app.knowledge_acquisition.acquire import (
        TerminalAcquisitionError,
        acquire_metadata_only,
    )

    with pytest.raises(TerminalAcquisitionError, match="cannot select transcript extractors"):

        acquire_metadata_only(
            VIDEO_URL,
            vault_context=None,
            extractor_ids=("summary",),
            env={"DATABASE_URL": "postgresql://fixture:fixture@localhost/fixture"},
            fetch_fn=lambda _url: (_ for _ in ()).throw(AssertionError("egress before guard")),
        )

    with pytest.raises(TerminalAcquisitionError, match="cannot carry extractor_requirements"):
        acquire_metadata_only(
            VIDEO_URL,
            vault_context=None,
            extractor_requirements={"summary": "optional"},
            env={"DATABASE_URL": "postgresql://fixture:fixture@localhost/fixture"},
            fetch_fn=lambda _url: (_ for _ in ()).throw(AssertionError("egress before guard")),
        )

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


def test_explicit_empty_metadata_extractor_policy_does_not_expand_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(plugin, "yt_dlp_extract_metadata", lambda _url: _info())
    conn = FakeOutboxConn()
    queue = _queue()
    row = _enqueue(
        queue,
        conn,
        policy_snapshot={
            "policy_version": 1,
            "mode": "candidate_metadata_only",
            "captions": True,
            "extractor_ids": [],
            "extractor_requirements": {},
        },
    )

    assert row.policy_snapshot["extractor_ids"] == []
    assert row.policy_snapshot["extractor_requirements"] == {}
    result = drain_one(
        queue.claim_batch(1, conn=conn)[0],
        vault_context=_vault(tmp_path / "vault"),
        queue=queue,
        conn=conn,
    )
    assert result.request_id == row.request_id
    assert result.status == "completed"
