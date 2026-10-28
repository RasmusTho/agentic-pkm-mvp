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
            {"binding_id": "binding-a", "collection_kind": "inbox_playlist", "collection_ref": "PL-a", "discovered_at": "2026-10-15T00:00:00+00:00", "trigger": "poll", "playlist_item_id": "pli-a"},
            {"binding_id": "binding-b", "collection_kind": "inbox_playlist", "collection_ref": "PL-b", "discovered_at": "2026-10-15T00:00:01+00:00", "trigger": "poll", "playlist_item_id": "pli-b"},
        ),
    )
    sources = (
        SimpleNamespace(binding_id="binding-a", account_binding_id="account-a", cursor={"version": 1, "frontier_playlist_item_id": "pli-a-newest", "known_playlist_item_ids": ["pli-a-newest", "pli-a"]}, last_success_at="2026-10-15T00:00:02+00:00"),
        SimpleNamespace(binding_id="binding-b", account_binding_id="account-b", cursor={"version": 1, "frontier_playlist_item_id": "pli-b-newest", "known_playlist_item_ids": ["pli-b-newest", "pli-b"]}, last_success_at="2026-10-15T00:00:03+00:00"),
    )
    records = [
        {"event": "youtube.source.discovered", "event_id": "source-1", "timestamp": "2026-10-15T00:00:00+00:00", "payload": {"item_ref": "video-1", "binding_id": "binding-a", "collection_kind": "inbox_playlist", "collection_ref": "PL-a", "trigger": "poll", "playlist_item_id": "pli-a"}},
        {"event": "youtube.source.discovered", "event_id": "source-2", "timestamp": "2026-10-15T00:00:01+00:00", "payload": {"item_ref": "video-1", "binding_id": "binding-b", "collection_kind": "inbox_playlist", "collection_ref": "PL-b", "trigger": "poll", "playlist_item_id": "pli-b"}},
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
    assert row.cursor_frontier is None
    assert row.next_retry_at == "2026-10-15T00:05:00+00:00"
    assert row.account_binding_ids == ("account-a", "account-b")
    assert row.channel_database == "isolated-test-db"
    assert "refresh-token-super-secret" not in json.dumps(projection)


def test_discovery_event_envelope_timestamp_merges_v1_playlist_trigger() -> None:
    request = SimpleNamespace(
        request_id="request-playlist",
        item_ref="video-playlist",
        status="pending",
        requested_at="2026-10-15T00:00:01+00:00",
        completed_at=None,
        attempts=0,
        next_attempt_at=None,
        artifact_path=None,
        content_identity=None,
        discovery_triggers=(
            {
                "binding_id": "binding-playlist",
                "collection_kind": "inbox_playlist",
                "collection_ref": "PL-inbox",
                "discovered_at": "2026-10-15T00:00:01+00:00",
                "trigger": "poll",
                "playlist_item_id": "pli-new",
            },
        ),
    )
    records = [
        {
            "event": "youtube.source.discovered",
            "event_id": "discover-playlist",
            "timestamp": "2026-10-15T00:00:00+00:00",
            "payload": {
                "item_ref": "video-playlist",
                "binding_id": "binding-playlist",
                "collection_kind": "inbox_playlist",
                "collection_ref": "PL-inbox",
                "trigger": "poll",
                "playlist_item_id": "pli-new",
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
    assert row.triggers[0].playlist_item_id == "pli-new"


def test_stored_trigger_keeps_event_collection_ref_after_deduplication() -> None:
    from app.knowledge_acquisition.acquisition_requests import DiscoveryTrigger

    # The production stored row omits collection_ref; only the event carries it.
    stored = DiscoveryTrigger(
        binding_id="binding-playlist",
        collection_kind="inbox_playlist",
        collection_ref="PL-inbox",
        trigger="poll",
        playlist_item_id="pli-new",
    ).stored_dict(discovered_at="2026-10-15T00:00:01+00:00")
    assert "collection_ref" not in stored
    request = SimpleNamespace(
        request_id="request-playlist", item_ref="video-playlist", status="pending",
        requested_at="2026-10-15T00:00:01+00:00", completed_at=None, attempts=0,
        next_attempt_at=None, artifact_path=None, content_identity=None,
        discovery_triggers=(stored,),
    )
    records = [{
        "event": "youtube.source.discovered",
        "event_id": "discover-playlist",
        "timestamp": "2026-10-15T00:00:00+00:00",
        "payload": {
            "item_ref": "video-playlist", "binding_id": "binding-playlist",
            "collection_kind": "inbox_playlist", "collection_ref": "PL-inbox",
            "trigger": "poll", "playlist_item_id": "pli-new",
        },
    }]

    row = query_youtube_sync_receipts(records=records, requests=(request,), sources=()).rows[0]

    assert len(row.triggers) == 1
    assert row.triggers[0].collection_ref == "PL-inbox"
    assert row.triggers[0].discovered_at == "2026-10-15T00:00:01+00:00"


def test_v1_playlist_cursor_uses_registered_shape_and_success_time() -> None:
    sources = (
        SimpleNamespace(
            binding_id="binding-playlist",
            account_binding_id="account-youtube",
            cursor={
                "version": 1,
                "frontier_playlist_item_id": "pli-existing",
                "known_playlist_item_ids": ["pli-existing", "pli-older"],
            },
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
                "binding_id": "binding-playlist",
                "collection_kind": "inbox_playlist",
                "collection_ref": "PL-inbox",
                "trigger": "poll",
                "playlist_item_id": "pli-new",
            },
        }
    ]

    request = SimpleNamespace(
        request_id="request-new",
        item_ref="video-new",
        status="pending",
        requested_at="2026-10-15T00:05:00+00:00",
        completed_at=None,
        attempts=0,
        next_attempt_at=None,
        artifact_path=None,
        content_identity=None,
        discovery_triggers=(
            {
                "binding_id": "binding-playlist",
                "collection_kind": "inbox_playlist",
                "collection_ref": "PL-inbox",
                "discovered_at": "2026-10-15T00:05:00+00:00",
                "trigger": "poll",
                "playlist_item_id": "pli-new",
            },
        ),
    )

    result = query_youtube_sync_receipts(
        records=records, requests=(request,), sources=sources
    )

    assert len(result.rows) == 1
    row = result.rows[0]
    assert row.cursor_advanced is False
    assert row.cursor_frontier == "pli-existing"
    assert row.triggers[0].discovered_at == "2026-10-15T00:05:00+00:00"
    assert row.deduplicated is False


def test_cursor_advanced_requires_each_discovery_binding_to_succeed() -> None:
    request = SimpleNamespace(
        request_id="request-multiple-sources",
        item_ref="video-multiple-sources",
        status="pending",
        requested_at="2026-10-15T00:00:05+00:00",
        completed_at=None,
        attempts=0,
        next_attempt_at=None,
        artifact_path=None,
        content_identity=None,
        discovery_triggers=(
            {
                "binding_id": "binding-a",
                "collection_kind": "inbox_playlist",
                "collection_ref": "PL-a",
                "discovered_at": "2026-10-15T00:00:00+00:00",
                "trigger": "poll",
                "playlist_item_id": "pli-a",
            },
            {
                "binding_id": "binding-b",
                "collection_kind": "inbox_playlist",
                "collection_ref": "PL-b",
                "discovered_at": "2026-10-15T00:00:05+00:00",
                "trigger": "poll",
                "playlist_item_id": "pli-b",
            },
        ),
    )
    sources = (
        SimpleNamespace(
            binding_id="binding-a",
            account_binding_id="account-a",
            cursor={"frontier_playlist_item_id": "pli-a-new"},
            last_success_at="2026-10-15T00:00:06+00:00",
        ),
        SimpleNamespace(
            binding_id="binding-b",
            account_binding_id="account-b",
            cursor={"frontier_playlist_item_id": "pli-b-old"},
            last_success_at="2026-10-15T00:00:01+00:00",
        ),
    )
    records = [
        {
            "event": "youtube.source.discovered",
            "event_id": "discover-a",
            "timestamp": "2026-10-15T00:00:00+00:00",
            "payload": {
                "item_ref": "video-multiple-sources",
                "binding_id": "binding-a",
                "collection_kind": "inbox_playlist",
                "collection_ref": "PL-a",
                "trigger": "poll",
                "playlist_item_id": "pli-a",
            },
        },
        {
            "event": "youtube.source.discovered",
            "event_id": "discover-b",
            "timestamp": "2026-10-15T00:00:05+00:00",
            "payload": {
                "item_ref": "video-multiple-sources",
                "binding_id": "binding-b",
                "collection_kind": "inbox_playlist",
                "collection_ref": "PL-b",
                "trigger": "poll",
                "playlist_item_id": "pli-b",
            },
        },
    ]

    result = query_youtube_sync_receipts(
        records=records, requests=(request,), sources=sources
    )

    assert len(result.rows) == 1
    assert result.rows[0].cursor_advanced is False
    assert result.rows[0].cursor_frontier is None


def test_deferred_sync_event_is_a_source_level_compatibility_diagnostic() -> None:
    # The V1 producer does not emit youtube.sync.*; retain read compatibility
    # without presenting synthetic future events as shipped production receipts.
    records = [
        {
            "event": "youtube.sync.degraded",
            "event_id": "sync-rss-degraded",
            "trace_id": "trace-rss",
            "timestamp": "2026-10-15T00:05:00+00:00",
            "payload": {
                "binding_id": "binding-future",
                "run_id": "future:run-1",
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
            "binding_id": "binding-future",
            "run_id": "future:run-1",
        },
    )
