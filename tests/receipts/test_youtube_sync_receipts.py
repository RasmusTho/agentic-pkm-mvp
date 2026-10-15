from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.receipts.youtube_sync_receipts import query_youtube_sync_receipts

pytestmark = pytest.mark.not_pg


def test_projection_answers_audit_questions_secret_free() -> None:
    request = SimpleNamespace(
        request_id="request-1",
        item_ref="video-1",
        status="pending",
        requested_at="2026-10-15T00:00:00+00:00",
        completed_at=None,
        attempts=1,
        next_attempt_at="2026-10-15T00:05:00+00:00",
        artifact_path=None,
        content_identity=None,
        discovery_triggers=(
            {"binding_id": "binding-a", "collection_kind": "inbox_playlist", "collection_ref": "PL-a", "discovered_at": "2026-10-15T00:00:00+00:00", "trigger": "poll"},
            {"binding_id": "binding-b", "collection_kind": "inbox_playlist", "collection_ref": "PL-b", "discovered_at": "2026-10-15T00:00:01+00:00", "trigger": "poll"},
        ),
    )
    sources = (
        SimpleNamespace(binding_id="binding-a", cursor={"frontier": "2026-10-15T00:00:01+00:00"}, last_success_at="2026-10-15T00:00:02+00:00"),
        SimpleNamespace(binding_id="binding-b", cursor={}, last_success_at=None),
    )
    records = [
        {"event": "youtube.source.discovered", "event_id": "source-1", "payload": {"item_ref": "video-1", "binding_id": "binding-a", "collection_kind": "inbox_playlist", "collection_ref": "PL-a", "trigger": "poll", "discovered_at": "2026-10-15T00:00:00+00:00"}},
        {"event": "youtube.source.discovered", "event_id": "source-2", "payload": {"item_ref": "video-1", "binding_id": "binding-b", "collection_kind": "inbox_playlist", "collection_ref": "PL-b", "trigger": "poll", "discovered_at": "2026-10-15T00:00:01+00:00"}},
        {"event": "acquisition.failed", "event_id": "failed-1", "payload": {"request_id": "request-1", "item_ref": "video-1", "attempt": 1, "reason_code": "auth_revoked", "error": "refresh-token-super-secret"}},
    ]
    result = query_youtube_sync_receipts(records=records, requests=(request,), sources=sources, channel_database="test")
    assert result.source_available is True
    assert len(result.rows) == 1
    row = result.rows[0]
    projection = row.to_dict()
    assert row.item_ref == "video-1"
    assert row.request_id == "request-1"
    assert row.deduplicated is True
    assert {trigger["binding_id"] for trigger in row.sources} == {"binding-a", "binding-b"}
    assert row.failure_reason_code == "auth_revoked"
    assert row.failed_stage == "acquisition"
    assert row.cursor_advanced is True
    assert row.next_retry_at == "2026-10-15T00:05:00+00:00"
    assert row.account_binding_ids == ("binding-a", "binding-b")
    assert row.channel_database == "test"
    assert "refresh-token-super-secret" not in json.dumps(projection)
