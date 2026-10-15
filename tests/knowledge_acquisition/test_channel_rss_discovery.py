"""YSS-07 Takeout import and channel RSS production discovery contract."""

from __future__ import annotations

import csv
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from app.events.topic_schema_registry import validate_topic_payload
from app.knowledge_acquisition import acquisition_requests, channel_rss_discovery
from app.knowledge_acquisition.acquisition_requests import (
    AcquisitionRequests,
    DiscoveryTrigger,
    drain_one,
    request_identity,
    reset_memory_acquisition_requests,
)
from app.knowledge_acquisition.source_registry import (
    SourceBinding,
    SourceRegistry,
    reset_memory_source_registry,
)
from app.knowledge_acquisition.sync_scheduler import LEASE_KEY, LEASE_TTL_SECONDS
from app.knowledge_acquisition.sync_state import MemorySyncStateStore, SyncLeaseLostError
from app.knowledge_acquisition.youtube_onboarding import import_takeout_registry

pytestmark = pytest.mark.not_pg

CHANNEL_A = "UC" + "a" * 22
CHANNEL_B = "UC" + "b" * 22
CHANNEL_C = "UC" + "c" * 22
CHANNEL_D = "UC" + "d" * 22

_RAW_POLL_SOURCE = channel_rss_discovery.poll_source


def _poll_with_lease(
    binding: SourceBinding,
    *,
    registry: SourceRegistry,
    requests: AcquisitionRequests,
    _state: MemorySyncStateStore | None = None,
    _holder: str = "rss-test-holder",
    _check_active: Any = None,
    _commit_guard: Any = None,
    **kwargs: Any,
) -> channel_rss_discovery.ChannelRSSPollResult:
    state = _state or MemorySyncStateStore()
    now = datetime.now(timezone.utc)
    assert state.acquire_lease(
        key=LEASE_KEY,
        holder=_holder,
        ttl_seconds=LEASE_TTL_SECONDS,
        now=now,
    )

    def check_active() -> None:
        if not state.heartbeat_lease(
            key=LEASE_KEY,
            holder=_holder,
            ttl_seconds=LEASE_TTL_SECONDS,
            now=datetime.now(timezone.utc),
        ):
            raise SyncLeaseLostError("YouTube discovery lease ownership was lost")

    def commit_guard():
        return state.owned_effect(
            key=LEASE_KEY,
            holder=_holder,
            now=datetime.now(timezone.utc),
        )

    return _RAW_POLL_SOURCE(
        binding,
        registry=registry,
        requests=requests,
        check_active=_check_active or check_active,
        commit_guard=_commit_guard or commit_guard,
        **kwargs,
    )


def _feed(channel_id: str, *items: tuple[str, str]) -> bytes:
    entries = "".join(
        f"""<entry>
<id>yt:video:{video_id}</id><yt:videoId>{video_id}</yt:videoId>
<yt:channelId>{channel_id}</yt:channelId><published>{published}</published>
</entry>"""
        for video_id, published in items
    )
    return (
        f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:yt="http://www.youtube.com/xml/schemas/2015">
<yt:channelId>{channel_id}</yt:channelId>{entries}</feed>"""
    ).encode()


@pytest.fixture
def runtime(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setattr(channel_rss_discovery, "poll_source", _poll_with_lease)
    reset_memory_source_registry()
    reset_memory_acquisition_requests()
    registry = SourceRegistry.for_runtime()
    requests = AcquisitionRequests.for_runtime()
    yield registry, requests
    reset_memory_source_registry()
    reset_memory_acquisition_requests()


@pytest.fixture
def captured_events(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any], str]]:
    events: list[tuple[str, dict[str, Any], str]] = []

    def capture(event: Any, conn: Any = None, *, idempotency_key: str, **_kwargs: Any) -> str:
        validate_topic_payload(event.event_type, event.payload)
        events.append((event.event_type, dict(event.payload), idempotency_key))
        return "captured-event"

    monkeypatch.setattr(channel_rss_discovery, "write_outbox_event", capture)
    monkeypatch.setattr(acquisition_requests, "write_outbox_event", capture)
    return events


def _binding(
    registry: SourceRegistry,
    channel_id: str = CHANNEL_A,
    *,
    mode: str = "discover_only",
    filters: dict[str, Any] | None = None,
) -> SourceBinding:
    policy: dict[str, Any] = {"mode": mode}
    if filters is not None:
        policy["filters"] = filters
    return registry.register(
        collection_kind="subscription_feed",
        collection_ref=channel_id,
        title="Synthetic channel",
        acquisition_policy=policy,
    )


def _receipt(video_id: str, **_kwargs: Any) -> Any:
    from app.knowledge_acquisition.acquire import AcquireStageReceipt, AcquisitionReceipt

    return AcquisitionReceipt(
        source_kind="youtube_url",
        item_ref=video_id,
        content_identity=f"sha256:{video_id}",
        raw_record_id=f"raw:{video_id}",
        is_new_raw=True,
        acquisition_method="caption_track",
        stages=(AcquireStageReceipt(stage="candidate", status="written", artifact_path=f"Sources/{video_id}.md"),),
        dead_lettered=(),
    )


def test_takeout_import_idempotent_with_conservative_default(
    tmp_path: Path, runtime: tuple[SourceRegistry, AcquisitionRequests]
) -> None:
    registry, _requests = runtime
    root = tmp_path / "Takeout"
    root.mkdir()
    with (root / "subscriptions.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Channel ID", "Channel Title", "Channel URL"])
        writer.writerow([CHANNEL_A, "Synthetic channel", f"https://www.youtube.com/channel/{CHANNEL_A}"])
        writer.writerow([CHANNEL_A, "Duplicate title", f"https://www.youtube.com/channel/{CHANNEL_A}"])
    with (root / "playlists.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Playlist ID", "Playlist Title"])
        writer.writerow(["PLsynthetic1", "Owned list"])
        writer.writerow(["LL", "Liked videos"])

    with pytest.raises(ValueError, match="account_binding_id is required"):
        import_takeout_registry(root, registry=registry)
    assert registry.list_all() == ()  # playlist preflight happens before any import write

    account_id = "d2c8eea1-a842-474a-b2a4-6448bd818551"
    first = import_takeout_registry(root, registry=registry, account_binding_id=account_id)
    assert first.imported == 3
    assert first.deduplicated == 0
    rows = {row.binding_id: row for row in registry.list_all()}
    subscription = next(row for row in rows.values() if row.collection_kind == "subscription_feed")
    owned = next(row for row in rows.values() if row.collection_kind == "owned_playlist")
    liked = next(row for row in rows.values() if row.collection_kind == "liked_videos")
    assert subscription.account_binding_id is None
    assert owned.account_binding_id == liked.account_binding_id == account_id
    assert subscription.acquisition_policy["mode"] == "discover_only"
    assert subscription.provenance["origin"] == "takeout_import"
    assert owned.provenance["origin"] == liked.provenance["origin"] == "takeout_import"
    changed = registry.update_acquisition_policy(subscription.binding_id, {"mode": "acquire_transcript"})
    registry.record_poll_success(subscription.binding_id, cursor={"recent_entry_ids": ["yt:video:existing"]})

    second = import_takeout_registry(root, registry=registry, account_binding_id=account_id)
    assert second.imported == 0
    assert second.deduplicated == 3
    reread = registry.get(subscription.binding_id)
    assert reread is not None
    assert reread.cursor == {"recent_entry_ids": ["yt:video:existing"]}
    assert reread.acquisition_policy == changed.acquisition_policy

    # Snapshot imports never delete registry rows missing from a later export.
    (root / "subscriptions.csv").write_text("Channel ID,Channel Title,Channel URL\n", encoding="utf-8")
    import_takeout_registry(root, registry=registry, account_binding_id=account_id)
    assert registry.get(subscription.binding_id) is not None


def test_rss_incremental_cursor_and_request_before_cursor(
    runtime: tuple[SourceRegistry, AcquisitionRequests], captured_events: list[tuple[str, dict[str, Any], str]]
) -> None:
    registry, requests = runtime
    binding = _binding(registry)
    data = _feed(
        CHANNEL_A,
        ("aaaaaaaaaaa", "2026-09-28T10:00:00Z"),
        ("bbbbbbbbbbb", "2026-09-28T09:00:00Z"),
    )

    class RequestBeforeCursor:
        def __getattr__(self, name: str) -> Any:
            return getattr(requests, name)

        def enqueue(self, **kwargs: Any) -> Any:
            current = registry.get(binding.binding_id)
            assert current is not None and current.cursor == {}
            return requests.enqueue(**kwargs)

        def enqueue_with_outcome(self, **kwargs: Any) -> Any:
            current = registry.get(binding.binding_id)
            assert current is not None and current.cursor == {}
            return requests.enqueue_with_outcome(**kwargs)

        def record_discovery(self, **kwargs: Any) -> None:
            current = registry.get(binding.binding_id)
            assert current is not None and current.cursor == {}
            requests.record_discovery(**kwargs)

    result = channel_rss_discovery.poll_source(
        binding,
        registry=registry,
        requests=RequestBeforeCursor(),  # type: ignore[arg-type]
        fetch_feed=lambda _channel_id: data,
    )
    assert result.discovered == 2
    assert result.enqueued == 0  # conservative default records only traced discovery
    assert requests.list_all() == ()
    assert {event[0] for event in captured_events} == {"youtube.source.discovered", "youtube.sync.completed"}
    stored = registry.get(binding.binding_id)
    assert stored is not None
    assert stored.cursor["newest_published_seen"] == "2026-09-28T10:00:00+00:00"
    assert stored.cursor["recent_entry_ids"] == ["yt:video:aaaaaaaaaaa", "yt:video:bbbbbbbbbbb"]


def test_overlapping_rss_poll_cannot_rewind_cursor_or_emit_stale_success(
    runtime: tuple[SourceRegistry, AcquisitionRequests],
    captured_events: list[tuple[str, dict[str, Any], str]],
) -> None:
    registry, requests = runtime
    binding = _binding(registry)
    state = MemorySyncStateStore()
    newer_results: list[channel_rss_discovery.ChannelRSSPollResult] = []

    def older_feed(_channel_id: str) -> bytes:
        newer_results.append(
            _poll_with_lease(
                binding,
                registry=registry,
                requests=requests,
                _state=state,
                _holder="same-runner",
                fetch_feed=lambda _ref: _feed(
                    CHANNEL_A, ("bbbbbbbbbbb", "2026-10-02T10:00:00Z")
                ),
            )
        )
        return _feed(CHANNEL_A, ("aaaaaaaaaaa", "2026-10-01T10:00:00Z"))

    older = _poll_with_lease(
        binding,
        registry=registry,
        requests=requests,
        _state=state,
        _holder="same-runner",
        fetch_feed=older_feed,
    )

    stored = registry.get(binding.binding_id)
    assert stored is not None
    assert stored.cursor["newest_published_seen"] == "2026-10-02T10:00:00+00:00"
    assert stored.cursor["recent_entry_ids"] == ["yt:video:bbbbbbbbbbb"]
    assert len(newer_results) == 1 and not newer_results[0].degraded
    assert older.superseded and not older.degraded
    completed = [
        event for event in captured_events
        if event[0] == "youtube.sync.completed" and event[1]["binding_id"] == binding.binding_id
    ]
    assert len(completed) == 1
    assert completed[0][1]["run_id"] == newer_results[0].run_id


def test_rss_old_lease_holder_stops_before_discovery_write_after_takeover(
    runtime: tuple[SourceRegistry, AcquisitionRequests],
    captured_events: list[tuple[str, dict[str, Any], str]],
) -> None:
    registry, requests = runtime
    binding = _binding(registry)
    state = MemorySyncStateStore()
    clock = [datetime(2026, 10, 15, tzinfo=timezone.utc)]
    old_holder = "old-runner"
    replacement = "replacement-runner"
    assert state.acquire_lease(
        key=LEASE_KEY, holder=old_holder, ttl_seconds=60, now=clock[0]
    )

    def check_old_holder() -> None:
        lease = state.get(LEASE_KEY)
        if (
            lease is None
            or lease["holder"] != old_holder
            or clock[0] >= datetime.fromisoformat(lease["expires_at"])
        ):
            raise SyncLeaseLostError("YouTube discovery lease ownership was lost")

    def owned_old_effect():
        return state.owned_effect(key=LEASE_KEY, holder=old_holder, now=clock[0])

    def take_over_before_disposition(_channel_id: str) -> bytes:
        clock[0] += timedelta(seconds=61)
        assert state.acquire_lease(
            key=LEASE_KEY,
            holder=replacement,
            ttl_seconds=60,
            now=clock[0],
        )
        return _feed(CHANNEL_A, ("aaaaaaaaaaa", "2026-10-01T10:00:00Z"))

    with pytest.raises(SyncLeaseLostError):
        _RAW_POLL_SOURCE(
            binding,
            registry=registry,
            requests=requests,
            check_active=check_old_holder,
            commit_guard=owned_old_effect,
            fetch_feed=take_over_before_disposition,
        )

    stored = registry.get(binding.binding_id)
    assert stored is not None and stored.cursor == {}
    assert requests.list_all() == ()
    assert not any(event[1].get("binding_id") == binding.binding_id for event in captured_events)


def test_rss_completion_counts_atomic_queue_dedup_after_overlapping_poll(
    runtime: tuple[SourceRegistry, AcquisitionRequests],
    captured_events: list[tuple[str, dict[str, Any], str]],
) -> None:
    registry, requests = runtime
    binding_a = _binding(registry, CHANNEL_A, mode="acquire_transcript")
    binding_b = _binding(registry, CHANNEL_B, mode="acquire_transcript")
    state = MemorySyncStateStore()
    competing_results: list[channel_rss_discovery.ChannelRSSPollResult] = []

    class InterleavingRequests:
        def __getattr__(self, name: str) -> Any:
            return getattr(requests, name)

        def get(self, request_id: str) -> Any:
            observed = requests.get(request_id)
            if observed is None and not competing_results:
                competing_results.append(
                    _poll_with_lease(
                        binding_b,
                        registry=registry,
                        requests=requests,
                        _state=state,
                        _holder="same-runner",
                        fetch_feed=lambda _channel_id: _feed(
                            CHANNEL_B, ("aaaaaaaaaaa", "2026-10-01T10:00:00Z")
                        ),
                    )
                )
            return observed

    first = _poll_with_lease(
        binding_a,
        registry=registry,
        requests=InterleavingRequests(),  # type: ignore[arg-type]
        _state=state,
        _holder="same-runner",
        fetch_feed=lambda _channel_id: _feed(
            CHANNEL_A, ("aaaaaaaaaaa", "2026-10-01T10:00:00Z")
        ),
    )
    if not competing_results:
        # The atomic outcome path has no stale preflight-read gap. Run the
        # second poll after the first disposition to verify its dedup receipt.
        competing_results.append(
            _poll_with_lease(
                binding_b,
                registry=registry,
                requests=requests,
                _state=state,
                _holder="same-runner",
                fetch_feed=lambda _channel_id: _feed(
                    CHANNEL_B, ("aaaaaaaaaaa", "2026-10-01T10:00:00Z")
                ),
            )
        )

    assert not first.degraded
    assert len(competing_results) == 1 and not competing_results[0].degraded
    assert len(requests.list_all()) == 1
    completed = [
        event[1]
        for event in captured_events
        if event[0] == "youtube.sync.completed"
        and event[1]["binding_id"] in {binding_a.binding_id, binding_b.binding_id}
    ]
    assert len(completed) == 2
    assert sorted((payload["enqueued"], payload["deduped"]) for payload in completed) == [
        (0, 1),
        (1, 0),
    ]


def test_policy_modes_and_version_bump_not_retroactive(
    runtime: tuple[SourceRegistry, AcquisitionRequests]
) -> None:
    registry, requests = runtime
    binding = _binding(registry, mode="discover_only")
    feed_items = [
        ("aaaaaaaaaaa", "2026-09-28T10:00:00Z"),
        ("bbbbbbbbbbb", "2026-09-28T09:00:00Z"),
    ]
    channel_rss_discovery.poll_source(
        binding, registry=registry, requests=requests, fetch_feed=lambda _channel_id: _feed(CHANNEL_A, feed_items[0])
    )
    updated = registry.update_acquisition_policy(binding.binding_id, {"mode": "acquire_transcript"})
    assert updated.acquisition_policy["policy_version"] == 2
    result = channel_rss_discovery.poll_source(
        updated, registry=registry, requests=requests, fetch_feed=lambda _channel_id: _feed(CHANNEL_A, *feed_items)
    )
    assert result.discovered == 1
    assert result.enqueued == 1
    queued = requests.list_all()
    assert len(queued) == 1
    assert queued[0].item_ref == "bbbbbbbbbbb"
    assert queued[0].policy_version == 2
    assert queued[0].policy_snapshot["mode"] == "acquire_transcript"
    assert requests.get(request_identity("youtube_url", "aaaaaaaaaaa", 2)) is None


def test_all_four_modes_use_truthful_production_drain(
    runtime: tuple[SourceRegistry, AcquisitionRequests],
    captured_events: list[tuple[str, dict[str, Any], str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.knowledge_acquisition import acquire as acquire_module

    registry, requests = runtime
    metadata_calls: list[str] = []
    metadata_producer_calls: list[dict[str, Any]] = []
    policy = {
        "language_allowlist": ["en"],
        "min_duration_seconds": 30,
        "max_duration_seconds": 300,
    }
    items = (
        ("aaaaaaaaaaa", "2026-09-28T10:00:00Z"),
        ("bbbbbbbbbbb", "2026-09-28T10:01:00Z"),
        ("ccccccccccc", "2026-09-28T10:02:00Z"),
        ("ddddddddddd", "2026-09-28T10:03:00Z"),
    )
    modes = (
        ("discover_only", None),
        ("candidate_metadata_only", None),
        ("acquire_transcript", None),
        ("acquire_if_filter_matches", policy),
    )

    def metadata_only_producer(*_args: Any, **kwargs: Any) -> Any:
        metadata_producer_calls.append(kwargs)
        return _receipt("bbbbbbbbbbb")

    monkeypatch.setattr(acquire_module, "acquire_metadata_only", metadata_only_producer)
    channel_ids = ["UC" + char * 22 for char in "abcd"]
    for index, ((mode, filters), (video_id, published), channel_id) in enumerate(zip(modes, items, channel_ids)):
        metadata_producer_calls_before = len(metadata_producer_calls)
        if mode == "acquire_if_filter_matches":
            filters = {**policy, "channel_allowlist": [channel_id]}
        binding = _binding(registry, channel_id, mode=mode, filters=filters)

        def metadata_fetcher(url: str, *, _video_id: str = video_id, _index: int = index) -> dict[str, Any]:
            metadata_calls.append(url)
            if _index == 3:
                return {"language": "en-US", "duration": 120}
            return {"language": "en", "duration": 120}

        result = channel_rss_discovery.poll_source(
            binding,
            registry=registry,
            requests=requests,
            fetch_feed=lambda _channel_id, _channel=channel_id, _video=video_id, _published=published: _feed(
                _channel, (_video, _published)
            ),
            metadata_fetcher=metadata_fetcher,
        )
        assert result.discovered == 1
        if mode == "discover_only":
            assert result.enqueued == 0
        else:
            assert result.enqueued == 1
            row = requests.get(request_identity("youtube_url", video_id, 1))
            assert row is not None
            expected_mode = "acquire_transcript" if mode == "acquire_if_filter_matches" else mode
            assert row.policy_snapshot["mode"] == expected_mode
            if mode == "acquire_if_filter_matches":
                assert "filters" not in row.policy_snapshot

            claimed = requests.claim_batch(1)
            assert claimed
            call_kwargs: list[dict[str, Any]] = []

            def transcript_acquire(*_args: Any, **kwargs: Any) -> Any:
                call_kwargs.append(kwargs)
                return _receipt(video_id)

            drained = drain_one(
                claimed[0],
                vault_context=None,
                queue=requests,
                acquire_fn=None if mode == "candidate_metadata_only" else transcript_acquire,
            )
            assert drained.status == "completed"
            if mode == "candidate_metadata_only":
                assert len(metadata_producer_calls) == metadata_producer_calls_before + 1
                assert metadata_producer_calls[-1]["extractor_ids"] == ()
                assert metadata_producer_calls[-1]["extractor_requirements"] is None
            else:
                assert len(metadata_producer_calls) == metadata_producer_calls_before
    assert len(metadata_calls) == 1  # language/duration preflight only; other modes do not fetch metadata
    assert len(metadata_producer_calls) == 1

    # Unsupported snapshots fail with a truthful item-scoped refusal before acquisition.
    unsupported = requests.enqueue(
        source_kind="youtube_url",
        item_ref="eeeeeeeeeee",
        source_ref="https://www.youtube.com/watch?v=eeeeeeeeeee",
        trigger=DiscoveryTrigger(
            binding_id="unsupported-binding",
            collection_kind="subscription_feed",
            collection_ref=CHANNEL_A,
            trigger="poll",
        ),
        policy_snapshot={"mode": "unsupported_mode", "policy_version": 7},
    )
    claimed_unsupported = requests.claim_batch(1)
    refused = drain_one(
        next(row for row in claimed_unsupported if row.request_id == unsupported.request_id),
        vault_context=None,
        queue=requests,
        acquire_fn=lambda *_args, **_kwargs: pytest.fail("unsupported policy must fail before acquisition"),
    )
    assert refused.status == "dead_lettered"
    assert refused.last_failure is not None and refused.last_failure["reason_code"] == "policy_unsupported"


def test_feed_failure_never_empty_success(
    runtime: tuple[SourceRegistry, AcquisitionRequests], captured_events: list[tuple[str, dict[str, Any], str]]
) -> None:
    registry, requests = runtime
    binding = _binding(registry)
    result = channel_rss_discovery.poll_source(
        binding,
        registry=registry,
        requests=requests,
        fetch_feed=lambda _channel_id: (_ for _ in ()).throw(
            channel_rss_discovery.RSSFeedError("rss_feed_unavailable", "fixture failure")
        ),
    )
    assert result.degraded
    assert result.reason_code == "rss_feed_unavailable"
    assert requests.list_all() == ()
    stored = registry.get(binding.binding_id)
    assert stored is not None and stored.cursor == {}
    assert stored.last_error is not None
    assert stored.last_error["reason_code"] == "rss_feed_unavailable"
    assert "youtube.sync.completed" not in {event[0] for event in captured_events}
    assert "youtube.sync.degraded" in {event[0] for event in captured_events}


def test_filter_metadata_failure_no_cursor(
    runtime: tuple[SourceRegistry, AcquisitionRequests], captured_events: list[tuple[str, dict[str, Any], str]]
) -> None:
    registry, requests = runtime
    filters = {"language_allowlist": ["en"]}
    binding = _binding(registry, mode="acquire_if_filter_matches", filters=filters)
    result = channel_rss_discovery.poll_source(
        binding,
        registry=registry,
        requests=requests,
        fetch_feed=lambda _channel_id: _feed(CHANNEL_A, ("aaaaaaaaaaa", "2026-09-28T10:00:00Z")),
        metadata_fetcher=lambda _url: {},
    )
    assert result.degraded
    assert result.reason_code == "filter_metadata_unavailable"
    stored = registry.get(binding.binding_id)
    assert stored is not None and stored.cursor == {}
    assert requests.list_all() == ()
    assert "youtube.sync.completed" not in {event[0] for event in captured_events}


def test_channel_only_filter_has_no_metadata_egress_and_nonmatch_is_traced(
    runtime: tuple[SourceRegistry, AcquisitionRequests],
    captured_events: list[tuple[str, dict[str, Any], str]],
) -> None:
    registry, requests = runtime
    channel_only = _binding(
        registry,
        mode="acquire_if_filter_matches",
        filters={"channel_allowlist": [CHANNEL_A]},
    )
    matched = channel_rss_discovery.poll_source(
        channel_only,
        registry=registry,
        requests=requests,
        fetch_feed=lambda _channel_id: _feed(
            CHANNEL_A, ("aaaaaaaaaaa", "2026-09-28T10:00:00Z")
        ),
        metadata_fetcher=lambda _url: pytest.fail("channel-only filters must not fetch metadata"),
    )
    assert matched.enqueued == 1

    language_filter = _binding(
        registry,
        CHANNEL_B,
        mode="acquire_if_filter_matches",
        filters={"language_allowlist": ["sv"]},
    )
    nonmatch = channel_rss_discovery.poll_source(
        language_filter,
        registry=registry,
        requests=requests,
        fetch_feed=lambda _channel_id: _feed(
            CHANNEL_B, ("bbbbbbbbbbb", "2026-09-28T11:00:00Z")
        ),
        metadata_fetcher=lambda _url: {"language": "en-US"},
    )
    assert nonmatch.filtered_out == 1
    assert requests.get(request_identity("youtube_url", "bbbbbbbbbbb", 1)) is None
    stored = registry.get(language_filter.binding_id)
    assert stored is not None and stored.cursor["recent_entry_ids"] == ["yt:video:bbbbbbbbbbb"]
    assert any(
        event[0] == "youtube.source.discovered"
        and event[1]["binding_id"] == language_filter.binding_id
        for event in captured_events
    )


def test_incompatible_shared_request_policies_degrade_in_both_arrival_orders(
    runtime: tuple[SourceRegistry, AcquisitionRequests],
    captured_events: list[tuple[str, dict[str, Any], str]],
) -> None:
    registry, requests = runtime
    scenarios = (
        ("aaaaaaaaaaa", CHANNEL_A, "acquire_transcript", CHANNEL_B, "candidate_metadata_only"),
        ("bbbbbbbbbbb", CHANNEL_C, "candidate_metadata_only", CHANNEL_D, "acquire_transcript"),
    )
    for video_id, existing_channel, existing_mode, polling_channel, polling_mode in scenarios:
        existing_binding = _binding(registry, existing_channel, mode=existing_mode)
        polling_binding = _binding(registry, polling_channel, mode=polling_mode)
        requests.enqueue(
            source_kind="youtube_url",
            item_ref=video_id,
            source_ref=f"https://www.youtube.com/watch?v={video_id}",
            trigger=DiscoveryTrigger(
                binding_id=existing_binding.binding_id,
                collection_kind=existing_binding.collection_kind,
                collection_ref=existing_binding.collection_ref,
                trigger="poll",
            ),
            policy_snapshot=existing_binding.acquisition_policy,
        )
        result = channel_rss_discovery.poll_source(
            polling_binding,
            registry=registry,
            requests=requests,
            fetch_feed=lambda _channel_id, video_id=video_id: _feed(
                polling_binding.collection_ref, (video_id, "2026-09-28T10:00:00Z")
            ),
        )
        assert result.degraded and result.reason_code == "policy_conflict"
        current = registry.get(polling_binding.binding_id)
        assert current is not None and current.cursor == {}
        stored = requests.get(request_identity("youtube_url", video_id, 1))
        assert stored is not None and stored.policy_snapshot["mode"] == existing_mode
        assert "youtube.sync.completed" not in {
            event[0]
            for event in captured_events
            if event[1].get("binding_id") == polling_binding.binding_id
        }
        assert any(
            event[0] == "youtube.source.discovered"
            and event[1]["binding_id"] == polling_binding.binding_id
            and event[1]["item_ref"] == video_id
            for event in captured_events
        )


def test_completion_receipt_write_failure_never_advances_cursor(
    runtime: tuple[SourceRegistry, AcquisitionRequests],
    captured_events: list[tuple[str, dict[str, Any], str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, requests = runtime
    binding = _binding(registry)
    write_event = channel_rss_discovery.write_outbox_event

    def fail_completion(event: Any, *args: Any, **kwargs: Any) -> str:
        if event.event_type == "youtube.sync.completed":
            raise OSError("synthetic outbox failure")
        return write_event(event, *args, **kwargs)

    monkeypatch.setattr(channel_rss_discovery, "write_outbox_event", fail_completion)
    result = channel_rss_discovery.poll_source(
        binding,
        registry=registry,
        requests=requests,
        fetch_feed=lambda _channel_id: _feed(
            CHANNEL_A, ("aaaaaaaaaaa", "2026-09-28T10:00:00Z")
        ),
    )
    assert result.degraded and result.reason_code == "network_error"
    stored = registry.get(binding.binding_id)
    assert stored is not None and stored.cursor == {}
    assert stored.last_error is not None and stored.last_error["reason_code"] == "network_error"
    assert not any(
        event[0] == "youtube.sync.completed" and event[1]["binding_id"] == binding.binding_id
        for event in captured_events
    )


def test_named_database_without_receipt_transaction_fails_before_cursor_advance(
    runtime: tuple[SourceRegistry, AcquisitionRequests],
    captured_events: list[tuple[str, dict[str, Any], str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, requests = runtime
    binding = _binding(registry)
    monkeypatch.setattr(channel_rss_discovery, "_transaction_required", lambda: True)
    with pytest.raises(RuntimeError, match="ownership transaction"):
        channel_rss_discovery.poll_source(
            binding,
            registry=registry,
            requests=requests,
            fetch_feed=lambda _channel_id: _feed(
                CHANNEL_A, ("aaaaaaaaaaa", "2026-09-28T10:00:00Z")
            ),
        )
    stored = registry.get(binding.binding_id)
    assert stored is not None and stored.cursor == {}
    assert not any(event[0] == "youtube.sync.completed" for event in captured_events)


def test_registry_receipts_receive_the_shared_outbox_transaction(
    runtime: tuple[SourceRegistry, AcquisitionRequests],
    captured_events: list[tuple[str, dict[str, Any], str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, requests = runtime
    successful_binding = _binding(registry)
    degraded_binding = _binding(registry, CHANNEL_B)
    connections: list[Any] = []

    class TransactionConnection:
        pass

    @contextmanager
    def owned_transaction():
        connection = TransactionConnection()
        connections.append(connection)
        yield connection

    success_calls: list[Any] = []
    failure_calls: list[Any] = []
    original_success = registry.record_poll_success
    original_failure = registry.record_poll_failure

    def record_success(binding_id: str, **kwargs: Any) -> Any:
        success_calls.append(kwargs.get("transaction_conn"))
        return original_success(binding_id, **kwargs)

    def record_failure(binding_id: str, **kwargs: Any) -> Any:
        failure_calls.append(kwargs.get("transaction_conn"))
        return original_failure(binding_id, **kwargs)

    monkeypatch.setattr(channel_rss_discovery, "_transaction_required", lambda: True)
    monkeypatch.setattr(registry, "record_poll_success", record_success)
    monkeypatch.setattr(registry, "record_poll_failure", record_failure)

    completed = channel_rss_discovery.poll_source(
        successful_binding,
        registry=registry,
        requests=requests,
        _commit_guard=owned_transaction,
        fetch_feed=lambda _channel_id: _feed(
            CHANNEL_A, ("aaaaaaaaaaa", "2026-09-28T10:00:00Z")
        ),
    )
    degraded = channel_rss_discovery.poll_source(
        degraded_binding,
        registry=registry,
        requests=requests,
        _commit_guard=owned_transaction,
        fetch_feed=lambda _channel_id: b"<broken",
    )

    assert not completed.degraded and degraded.degraded
    assert success_calls == [connections[1]]
    assert failure_calls == [connections[2]]
    assert any(event[0] == "youtube.sync.completed" for event in captured_events)
    assert any(event[0] == "youtube.sync.degraded" for event in captured_events)


def test_invalid_subscription_channel_degrades_with_registered_payload_schema(
    runtime: tuple[SourceRegistry, AcquisitionRequests],
    captured_events: list[tuple[str, dict[str, Any], str]],
) -> None:
    registry, requests = runtime
    binding = _binding(registry, "UCinvalid")
    result = channel_rss_discovery.poll_source(
        binding,
        registry=registry,
        requests=requests,
        fetch_feed=lambda _channel_id: pytest.fail("invalid channel ids must be refused before egress"),
    )
    assert result.degraded and result.reason_code == "source_mismatch"
    degraded = next(event for event in captured_events if event[0] == "youtube.sync.degraded")
    assert degraded[1]["collection_ref"] == "UCinvalid"


def test_xml_hardening_no_external_entities_bounded_size() -> None:
    malicious = (
        b'<!DOCTYPE feed [<!ENTITY external SYSTEM "file:///etc/passwd">]>'
        b'<feed xmlns="http://www.w3.org/2005/Atom"/>'
    )
    with pytest.raises(channel_rss_discovery.RSSFeedError, match="DTD and entity"):
        channel_rss_discovery.parse_channel_feed(malicious, expected_channel_id=CHANNEL_A)
    utf16_malicious = (
        '<?xml version="1.0" encoding="UTF-16"?>'
        '<!DOCTYPE feed [<!ENTITY injected "expanded">]>'
        '<feed xmlns="http://www.w3.org/2005/Atom"><title>&injected;</title></feed>'
    ).encode("utf-16")
    with pytest.raises(channel_rss_discovery.RSSFeedError, match="UTF-8"):
        channel_rss_discovery.parse_channel_feed(utf16_malicious, expected_channel_id=CHANNEL_A)
    for byte_order in ("utf-16-le", "utf-16-be"):
        bomless_utf16_malicious = (
            '<?xml version="1.0" encoding="UTF-16"?>'
            '<!DOCTYPE feed [<!ENTITY injected "expanded">]>'
            '<feed xmlns="http://www.w3.org/2005/Atom"><title>&injected;</title></feed>'
        ).encode(byte_order)
        with pytest.raises(channel_rss_discovery.RSSFeedError, match="NUL"):
            channel_rss_discovery.parse_channel_feed(
                bomless_utf16_malicious, expected_channel_id=CHANNEL_A
            )
    with pytest.raises(channel_rss_discovery.RSSFeedError) as oversized:
        channel_rss_discovery.parse_channel_feed(
            b"x" * (channel_rss_discovery.MAX_FEED_BYTES + 1), expected_channel_id=CHANNEL_A
        )
    assert oversized.value.reason_code == "rss_feed_too_large"


def test_sync_events_match_registered_schema_and_failure_never_completes(
    runtime: tuple[SourceRegistry, AcquisitionRequests], captured_events: list[tuple[str, dict[str, Any], str]]
) -> None:
    registry, requests = runtime
    binding = _binding(registry)
    channel_rss_discovery.poll_source(
        binding,
        registry=registry,
        requests=requests,
        fetch_feed=lambda _channel_id: _feed(CHANNEL_A, ("aaaaaaaaaaa", "2026-09-28T10:00:00Z")),
    )
    completed = next(event for event in captured_events if event[0] == "youtube.sync.completed")
    assert completed[1]["collection_kind"] == "subscription_feed"
    assert completed[1]["quota_units_spent"] == 0
    assert completed[2]

    failed_binding = _binding(registry, CHANNEL_B)
    failed = channel_rss_discovery.poll_source(
        failed_binding,
        registry=registry,
        requests=requests,
        fetch_feed=lambda _channel_id: b"<broken",
    )
    assert failed.degraded
    failed_events = [event[0] for event in captured_events if event[1].get("binding_id") == failed_binding.binding_id]
    assert "youtube.sync.degraded" in failed_events
    assert "youtube.sync.completed" not in failed_events


def test_feed_url_is_fixed_host_and_redirects_are_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    assert channel_rss_discovery.build_feed_url(CHANNEL_A) == (
        f"https://www.youtube.com/feeds/videos.xml?channel_id={CHANNEL_A}"
    )
    with pytest.raises(channel_rss_discovery.RSSFeedError):
        channel_rss_discovery.build_feed_url("https://example.com/?channel_id=bad")
    calls: list[str] = []

    class Response:
        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_args: Any) -> None:
            return None

        def geturl(self) -> str:
            return channel_rss_discovery.build_feed_url(CHANNEL_A)

        def read(self, _limit: int) -> bytes:
            return b"<feed/>"

    class Opener:
        def open(self, request: Any, timeout: int) -> Response:
            calls.append(request.full_url)
            assert timeout == channel_rss_discovery.HTTP_TIMEOUT_SECONDS
            return Response()

    monkeypatch.setattr(channel_rss_discovery, "assert_source_egress_allowed", lambda _seam: None)
    monkeypatch.setattr(channel_rss_discovery, "build_opener", lambda *_handlers: Opener())
    content = channel_rss_discovery.fetch_channel_feed(CHANNEL_A)
    assert content == b"<feed/>"
    assert calls == [channel_rss_discovery.build_feed_url(CHANNEL_A)]
