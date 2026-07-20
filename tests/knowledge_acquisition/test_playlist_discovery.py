"""YSS-05 (#3920): generic playlist discovery adapter contract.

All source egress is stubbed at the delivered YSS-03 client boundary.  The
tests deliberately exercise the production ``poll_source`` -> YSS-04
``AcquisitionRequests.enqueue`` call site and the real YSS-01 memory registry,
so request-before-cursor and cross-list identity are not proved against a
parallel fake persistence model.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from typing import Any

import pytest

from app.knowledge_acquisition import acquisition_requests as request_module
from app.knowledge_acquisition import playlist_discovery as discovery_module
from app.knowledge_acquisition.acquisition_requests import (
    YOUTUBE_SOURCE_DISCOVERED_TOPIC,
    AcquisitionRequests,
    reset_memory_acquisition_requests,
)
from app.knowledge_acquisition.playlist_discovery import (
    YOUTUBE_SYNC_COMPLETED_TOPIC,
    YOUTUBE_SYNC_DEGRADED_TOPIC,
    SourcePollPersistenceError,
    poll_source,
)
from app.knowledge_acquisition.source_registry import (
    SourceRegistry,
    SourceUnsupportedError,
    reset_memory_source_registry,
)
from app.knowledge_acquisition.youtube_api_client import (
    NotModified,
    PlaylistItem,
    PlaylistItemsPage,
    YouTubeApiError,
)
from app.services.outbox import write_outbox_event
from tests.knowledge_acquisition._acquisition_requests_contract import FakeOutboxConn

pytestmark = pytest.mark.not_pg

VIDEO_A = "aaaaaaaaaaa"
VIDEO_B = "bbbbbbbbbbb"
PLAYLIST_A = "PL_test_playlist_a"
PLAYLIST_B = "PL_test_playlist_b"


class StubApiClient:
    def __init__(self, result: PlaylistItemsPage | NotModified | BaseException) -> None:
        self.result = result
        self.calls: list[dict[str, Any]] = []

    def list_playlist_items(
        self,
        playlist_id: str,
        *,
        etag: str | None = None,
        page_token: str | None = None,
    ) -> PlaylistItemsPage | NotModified:
        self.calls.append(
            {"playlist_id": playlist_id, "etag": etag, "page_token": page_token}
        )
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result

    def quota_status(self) -> dict[str, int | bool]:
        return {"spent_today": len(self.calls), "budget": 10_000, "exhausted": False}


class FailingQueue:
    def __init__(self, delegate: AcquisitionRequests) -> None:
        self.delegate = delegate
        self.enqueue_calls = 0

    def get(self, request_id: str):
        return self.delegate.get(request_id)

    def enqueue(self, **kwargs: Any):
        self.enqueue_calls += 1
        if self.enqueue_calls == 2:
            raise OSError("backend write failed with private diagnostic")
        return self.delegate.enqueue(**kwargs)


def _item(playlist_item_id: str, video_id: str, position: int = 0) -> PlaylistItem:
    return PlaylistItem(
        playlist_item_id=playlist_item_id,
        video_id=video_id,
        position=position,
        published_at="2026-07-20T00:00:00Z",
        title=f"Synthetic item {position}",
    )


def _page(
    *items: PlaylistItem,
    etag: str = '"etag-1"',
    truncated: bool = False,
    next_page_token: str | None = None,
) -> PlaylistItemsPage:
    return PlaylistItemsPage(
        items=tuple(items),
        next_page_token=next_page_token,
        etag=etag,
        pagination_truncated=truncated,
    )


@pytest.fixture(autouse=True)
def _memory_backends(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("STORE_BACKEND", "memory")
    reset_memory_source_registry()
    reset_memory_acquisition_requests()
    yield
    reset_memory_source_registry()
    reset_memory_acquisition_requests()


@pytest.fixture
def outbox(monkeypatch: pytest.MonkeyPatch) -> FakeOutboxConn:
    conn = FakeOutboxConn()

    def emit(event: Any, conn: Any = None, *, idempotency_key: str) -> str:
        del conn
        return write_outbox_event(event, conn=conn_fixture, idempotency_key=idempotency_key)

    conn_fixture = conn
    monkeypatch.setattr(request_module, "write_outbox_event", emit)
    monkeypatch.setattr(discovery_module, "write_outbox_event", emit)
    return conn


def _register(
    registry: SourceRegistry,
    *,
    collection_kind: str = "owned_playlist",
    collection_ref: str = PLAYLIST_A,
    acquisition_policy: dict[str, Any] | None = None,
):
    account_binding_id = None
    if collection_kind in {"inbox_playlist", "owned_playlist", "liked_videos"}:
        account_binding_id = str(uuid.uuid4())
    binding = registry.register(
        collection_kind=collection_kind,
        collection_ref=collection_ref,
        title="Synthetic playlist",
        account_binding_id=account_binding_id,
        acquisition_policy=acquisition_policy,
    )
    if collection_kind == "inbox_playlist":
        binding = registry.set_inbox(account_binding_id, binding.binding_id)
    return binding


def test_new_item_creates_exactly_one_request_at_call_site(outbox: FakeOutboxConn) -> None:
    registry = SourceRegistry.for_runtime()
    requests = AcquisitionRequests.for_runtime()
    binding = _register(registry)
    api = StubApiClient(_page(_item("pli-a", VIDEO_A)))

    first = poll_source(binding, api_client=api, requests=requests, registry=registry)
    second = poll_source(
        registry.get(binding.binding_id), api_client=api, requests=requests, registry=registry
    )

    rows = requests.list_all()
    assert first.discovered == first.enqueued == 1
    assert second.discovered == second.enqueued == 0
    assert len(rows) == 1
    assert rows[0].item_ref == VIDEO_A
    assert len(rows[0].discovery_triggers) == 1
    assert rows[0].discovery_triggers[0] == {
        "binding_id": binding.binding_id,
        "collection_kind": "owned_playlist",
        "playlist_item_id": "pli-a",
        "discovered_at": rows[0].discovery_triggers[0]["discovered_at"],
        "trigger": "poll",
    }
    assert len(outbox.rows_for(YOUTUBE_SOURCE_DISCOVERED_TOPIC)) == 1


def test_cross_list_dedup_preserves_both_triggers(outbox: FakeOutboxConn) -> None:
    registry = SourceRegistry.for_runtime()
    requests = AcquisitionRequests.for_runtime()
    first_binding = _register(registry, collection_ref=PLAYLIST_A)
    second_binding = _register(registry, collection_ref=PLAYLIST_B)

    poll_source(
        first_binding,
        api_client=StubApiClient(_page(_item("pli-a", VIDEO_A))),
        requests=requests,
        registry=registry,
    )
    outcome = poll_source(
        second_binding,
        api_client=StubApiClient(_page(_item("pli-b", VIDEO_A))),
        requests=requests,
        registry=registry,
    )

    rows = requests.list_all()
    assert len(rows) == 1
    assert outcome.deduped == 1
    assert {trigger["binding_id"] for trigger in rows[0].discovery_triggers} == {
        first_binding.binding_id,
        second_binding.binding_id,
    }
    assert {trigger["playlist_item_id"] for trigger in rows[0].discovery_triggers} == {
        "pli-a",
        "pli-b",
    }


def test_pagination_to_frontier_and_capped_overflow_marked(outbox: FakeOutboxConn) -> None:
    registry = SourceRegistry.for_runtime()
    requests = AcquisitionRequests.for_runtime()
    binding = _register(registry)

    poll_source(
        binding,
        api_client=StubApiClient(_page(_item("pli-known", VIDEO_A))),
        requests=requests,
        registry=registry,
    )
    # The YSS-03 client returns its bounded, flattened multi-page result.  A
    # known item at the front must not stop the adapter from disposing the
    # unknown item found behind it; its truncation marker must survive.
    outcome = poll_source(
        registry.get(binding.binding_id),
        api_client=StubApiClient(
            _page(
                _item("pli-known", VIDEO_A),
                _item("pli-behind-frontier", VIDEO_B, position=50),
                etag='"etag-2"',
                truncated=True,
                next_page_token="bounded-overflow-token",
            )
        ),
        requests=requests,
        registry=registry,
    )

    stored = registry.get(binding.binding_id)
    assert outcome.discovered == outcome.enqueued == 1
    assert outcome.backfill_needed is True
    assert stored is not None
    assert stored.cursor["backfill_needed"] is True
    assert stored.cursor["backfill_page_token"] == "bounded-overflow-token"
    assert "pli-behind-frontier" in stored.cursor["known_playlist_item_ids"]
    assert {row.item_ref for row in requests.list_all()} == {VIDEO_A, VIDEO_B}


def test_not_modified_poll_success_without_mutation(outbox: FakeOutboxConn) -> None:
    registry = SourceRegistry.for_runtime()
    requests = AcquisitionRequests.for_runtime()
    binding = _register(registry)
    poll_source(
        binding,
        api_client=StubApiClient(_page(_item("pli-a", VIDEO_A), etag='"stable"')),
        requests=requests,
        registry=registry,
    )
    before = registry.get(binding.binding_id)
    assert before is not None
    api = StubApiClient(NotModified(etag='"stable"'))

    outcome = poll_source(before, api_client=api, requests=requests, registry=registry)
    after = registry.get(binding.binding_id)

    assert outcome.not_modified is True
    assert outcome.discovered == outcome.enqueued == 0
    assert api.calls == [
        {"playlist_id": PLAYLIST_A, "etag": '"stable"', "page_token": None}
    ]
    assert after is not None
    assert after.cursor == before.cursor
    assert after.last_success_at is not None
    assert after.last_success_at != before.last_success_at
    assert after.last_error is None
    assert len(outbox.rows_for(YOUTUBE_SYNC_COMPLETED_TOPIC)) == 2


def test_failed_poll_never_reports_empty_success(outbox: FakeOutboxConn) -> None:
    registry = SourceRegistry.for_runtime()
    requests = AcquisitionRequests.for_runtime()
    failures = (
        ("auth_revoked", 401),
        ("api_unavailable", 503),
        ("network_error", None),
    )

    for reason_code, status in failures:
        binding = _register(registry, collection_ref=f"PL_test_{reason_code}")
        before = registry.get(binding.binding_id)
        result = poll_source(
            binding,
            api_client=StubApiClient(
                YouTubeApiError(reason_code, status, "provider-safe classification")
            ),
            requests=requests,
            registry=registry,
        )
        after = registry.get(binding.binding_id)
        assert result.degraded is True
        assert result.reason_code == reason_code
        assert after is not None and before is not None
        assert after.cursor == before.cursor == {}
        assert after.last_error is not None
        assert after.last_error["reason_code"] == reason_code
        assert after.last_success_at is None

    assert not requests.list_all()
    assert len(outbox.rows_for(YOUTUBE_SYNC_DEGRADED_TOPIC)) == len(failures)
    assert len(outbox.rows_for(YOUTUBE_SYNC_COMPLETED_TOPIC)) == 0


def test_enqueue_failure_blocks_cursor_prefix(outbox: FakeOutboxConn) -> None:
    registry = SourceRegistry.for_runtime()
    requests = AcquisitionRequests.for_runtime()
    binding = _register(registry)
    before = registry.get(binding.binding_id)

    with pytest.raises(SourcePollPersistenceError, match="request persistence failed") as caught:
        poll_source(
            binding,
            api_client=StubApiClient(
                _page(_item("pli-first", VIDEO_A), _item("pli-fails", VIDEO_B, position=1))
            ),
            requests=FailingQueue(requests),
            registry=registry,
        )

    after = registry.get(binding.binding_id)
    assert "private diagnostic" not in str(caught.value)
    assert before is not None and after is not None
    assert after.cursor == before.cursor == {}
    assert after.last_success_at is None
    assert after.last_error is not None
    assert after.last_error["reason_code"] == "network_error"
    # The first request is durable, but no cursor prefix is published past the
    # second item's failed persistence. Retry will converge through idempotency.
    assert [row.item_ref for row in requests.list_all()] == [VIDEO_A]
    assert len(outbox.rows_for(YOUTUBE_SYNC_COMPLETED_TOPIC)) == 0
    assert len(outbox.rows_for(YOUTUBE_SYNC_DEGRADED_TOPIC)) == 1


def test_liked_videos_via_generic_adapter_requires_auth(outbox: FakeOutboxConn) -> None:
    registry = SourceRegistry.for_runtime()
    requests = AcquisitionRequests.for_runtime()
    binding = _register(registry, collection_kind="liked_videos", collection_ref="LL")
    api = StubApiClient(_page(_item("pli-liked", VIDEO_A)))

    success = poll_source(binding, api_client=api, requests=requests, registry=registry)
    assert success.enqueued == 1
    assert api.calls[0]["playlist_id"] == "LL"

    second = _register(registry, collection_kind="liked_videos", collection_ref="LL")
    missing_auth = replace(second, account_binding_id=None)
    before_calls = len(api.calls)
    degraded = poll_source(
        missing_auth, api_client=api, requests=requests, registry=registry
    )
    assert degraded.degraded is True
    assert degraded.reason_code == "auth_missing"
    assert len(api.calls) == before_calls


def test_watch_later_and_history_refused_unsupported(outbox: FakeOutboxConn) -> None:
    registry = SourceRegistry.for_runtime()
    requests = AcquisitionRequests.for_runtime()
    account = str(uuid.uuid4())

    for unsupported in ("WL", "HL"):
        with pytest.raises(SourceUnsupportedError, match="official YouTube Data API"):
            registry.register(
                collection_kind="owned_playlist",
                collection_ref=unsupported,
                title="Unsupported synthetic source",
                account_binding_id=account,
            )

        valid = _register(registry, collection_ref=f"PL_valid_for_{unsupported}")
        api = StubApiClient(_page())
        result = poll_source(
            replace(valid, collection_ref=unsupported),
            api_client=api,
            requests=requests,
            registry=registry,
        )
        assert result.degraded is True
        assert result.reason_code == "source_unsupported"
        assert "official YouTube Data API" in (result.detail or "")
        assert not api.calls


def test_discover_only_traces_without_requests(outbox: FakeOutboxConn) -> None:
    registry = SourceRegistry.for_runtime()
    requests = AcquisitionRequests.for_runtime()
    binding = _register(
        registry,
        acquisition_policy={"mode": "discover_only", "policy_version": 1},
    )

    result = poll_source(
        binding,
        api_client=StubApiClient(_page(_item("pli-discover-only", VIDEO_A))),
        requests=requests,
        registry=registry,
    )
    stored = registry.get(binding.binding_id)

    assert result.discovered == 1
    assert result.enqueued == result.deduped == 0
    assert not requests.list_all()
    assert stored is not None
    assert stored.cursor["dispositions"]["pli-discover-only"] == {
        "item_ref": VIDEO_A,
        "outcome": "discover_only",
    }
    assert len(outbox.rows_for(YOUTUBE_SOURCE_DISCOVERED_TOPIC)) == 1
    assert len(outbox.rows_for(YOUTUBE_SYNC_COMPLETED_TOPIC)) == 1
