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
        SimpleNamespace(binding_id="binding-a", account_binding_id="account-a", cursor={"frontier": "2026-10-15T00:00:01+00:00"}, last_success_at="2026-10-15T00:00:02+00:00"),
        SimpleNamespace(binding_id="binding-b", account_binding_id="account-b", cursor={}, last_success_at=None),
    )
    records = [
        {"event": "youtube.source.discovered", "event_id": "source-1", "payload": {"item_ref": "video-1", "binding_id": "binding-a", "collection_kind": "inbox_playlist", "collection_ref": "PL-a", "trigger": "poll", "discovered_at": "2026-10-15T00:00:00+00:00"}},
        {"event": "youtube.source.discovered", "event_id": "source-2", "payload": {"item_ref": "video-1", "binding_id": "binding-b", "collection_kind": "inbox_playlist", "collection_ref": "PL-b", "trigger": "poll", "discovered_at": "2026-10-15T00:00:01+00:00"}},
        {"event": "acquisition.failed", "event_id": "failed-1", "payload": {"request_id": "request-1", "item_ref": "video-1", "attempt": 1, "reason_code": "auth_revoked", "error": "refresh-token-super-secret"}},
    ]
    result = query_youtube_sync_receipts(
        records=records,
        requests=(request,),
        sources=sources,
        channel_database="isolated-test-db",
    )
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
    assert row.account_binding_ids == ("account-a", "account-b")
    assert row.channel_database == "isolated-test-db"
    assert "refresh-token-super-secret" not in json.dumps(projection)


def test_discovery_event_envelope_timestamp_merges_request_trigger() -> None:
    request = SimpleNamespace(
        request_id="request-rss",
        item_ref="video-rss",
        status="pending",
        requested_at="2026-10-15T00:00:01+00:00",
        completed_at=None,
        attempts=0,
        next_attempt_at=None,
        artifact_path=None,
        content_identity=None,
        discovery_triggers=(
            {
                "binding_id": "binding-rss",
                "collection_kind": "subscription_feed",
                "collection_ref": "UC-rss",
                "discovered_at": "2026-10-15T00:00:01+00:00",
                "trigger": "poll",
            },
        ),
    )
    records = [
        {
            "event": "youtube.source.discovered",
            "event_id": "discover-rss",
            "timestamp": "2026-10-15T00:00:00+00:00",
            "payload": {
                "item_ref": "video-rss",
                "binding_id": "binding-rss",
                "collection_kind": "subscription_feed",
                "collection_ref": "UC-rss",
                "trigger": "poll",
            },
        }
    ]

    result = query_youtube_sync_receipts(
        records=records,
        requests=(request,),
        sources=(),
    )

    assert len(result.rows) == 1
    row = result.rows[0]
    assert row.deduplicated is False
    assert len(row.triggers) == 1
    assert row.triggers[0].discovered_at == "2026-10-15T00:00:01+00:00"


def test_failed_rss_completion_does_not_report_cursor_advanced() -> None:
    sources = (
        SimpleNamespace(
            binding_id="binding-rss",
            account_binding_id="account-rss",
            cursor={"newest_published_seen": "2026-10-15T00:00:00+00:00"},
            last_success_at="2026-10-15T00:00:00+00:00",
        ),
    )
    records = [
        {
            "event": "youtube.source.discovered",
            "event_id": "discover-new-item",
            "timestamp": "2026-10-15T00:05:00+00:00",
            "payload": {
                "item_ref": "video-new",
                "binding_id": "binding-rss",
                "collection_kind": "subscription_feed",
                "collection_ref": "UC-rss",
                "trigger": "poll",
            },
        }
    ]

    result = query_youtube_sync_receipts(records=records, requests=(), sources=sources)

    assert len(result.rows) == 1
    row = result.rows[0]
    assert row.cursor_advanced is False
    assert row.cursor_frontier == "2026-10-15T00:00:00+00:00"
    assert row.triggers[0].discovered_at == "2026-10-15T00:05:00+00:00"


def test_rss_sync_receipt_uses_registered_source_shape() -> None:
    records = [
        {
            "event": "youtube.sync.degraded",
            "event_id": "sync-rss-degraded",
            "trace_id": "trace-rss",
            "timestamp": "2026-10-15T00:05:00+00:00",
            "payload": {
                "binding_id": "binding-rss",
                "run_id": "rss:run-1",
                "reason_code": "persistence_failed",
                "detail": "cursor transaction failed",
            },
        }
    ]

    result = query_youtube_sync_receipts(records=records, requests=(), sources=())

    assert result.rows == ()
    assert result.non_authoritative_records == (
        {
            "event_id": "sync-rss-degraded",
            "trace_id": "trace-rss",
            "event": "youtube.sync.degraded",
            "at": "2026-10-15T00:05:00+00:00",
            "reason_code": "persistence_failed",
            "reason": "source_level_sync_receipt",
            "binding_id": "binding-rss",
            "run_id": "rss:run-1",
        },
    )
