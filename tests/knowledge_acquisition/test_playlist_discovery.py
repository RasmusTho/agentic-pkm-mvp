"""Strict YouTube Source Sync V1 contract: one account and one Inbox."""

from __future__ import annotations

import json
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
import yaml

from app import objects as object_store_module
from app.agent_memory import materialization
from app.knowledge_acquisition import acquisition_requests as request_module
from app.knowledge_acquisition import playlist_discovery as discovery_module
from app.knowledge_acquisition import source_registry as registry_module
from app.knowledge_acquisition import youtube_plugin as plugin
from app.knowledge_acquisition.acquisition_requests import (
    YOUTUBE_SOURCE_DISCOVERED_TOPIC,
    AcquisitionRequests,
    drain_one,
    reset_memory_acquisition_requests,
)
from app.knowledge_acquisition.extraction_registry import clear_registry
from app.knowledge_acquisition.extractors import summary_extractor
from app.knowledge_acquisition.playlist_discovery import (
    SourcePollPersistenceError,
    V1InboxConfigurationError,
    YouTubeInboxSyncV1,
    poll_source,
)
from app.knowledge_acquisition.source_registry import (
    SourceRegistry,
    reset_memory_source_registry,
)
from app.knowledge_acquisition.youtube_api_client import (
    NotModified,
    PlaylistItem,
    PlaylistItemsPage,
    YouTubeApiError,
)
from app.services.outbox import write_outbox_event
from app.vault.manager import VaultContext
from app.write_guard import WriteGuard
from tests.knowledge_acquisition._acquisition_requests_contract import FakeOutboxConn

pytestmark = pytest.mark.not_pg

VIDEO_A = "aaaaaaaaaaa"
VIDEO_B = "bbbbbbbbbbb"
PLAYLIST_A = "PL_v1_inbox_a"
PLAYLIST_B = "PL_v1_inbox_b"


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


class FailingReadQueue:
    def get(self, request_id: str):
        del request_id
        raise OSError("backend read failed with private diagnostic")

    def enqueue(self, **kwargs: Any):
        raise AssertionError(f"enqueue must not run after a failed read: {kwargs!r}")


class FailingRegistry:
    def __init__(self, delegate: SourceRegistry, fail_method: str) -> None:
        self.delegate = delegate
        self.fail_method = fail_method

    def get(self, binding_id: str):
        if self.fail_method == "get":
            raise RuntimeError("PRIVATE_DIAGNOSTIC from registry read")
        return self.delegate.get(binding_id)

    def record_poll_success(self, binding_id: str, *, cursor: dict[str, Any]):
        if self.fail_method == "record_poll_success":
            raise RuntimeError("PRIVATE_DIAGNOSTIC from registry success write")
        return self.delegate.record_poll_success(binding_id, cursor=cursor)

    def record_poll_failure(
        self, binding_id: str, *, reason_code: str, detail: Any = None
    ):
        if self.fail_method == "record_poll_failure":
            raise RuntimeError("PRIVATE_DIAGNOSTIC from registry failure write")
        return self.delegate.record_poll_failure(
            binding_id, reason_code=reason_code, detail=detail
        )


class FailingListRegistry:
    def list_for_account(self, account_binding_id: str):
        del account_binding_id
        raise RuntimeError("PRIVATE_DIAGNOSTIC from registry list")


class CommittedThenRaisedRegistry:
    def __init__(self, delegate: SourceRegistry) -> None:
        self.delegate = delegate

    def get(self, binding_id: str):
        return self.delegate.get(binding_id)

    def record_poll_success(self, binding_id: str, *, cursor: dict[str, Any]):
        self.delegate.record_poll_success(binding_id, cursor=cursor)
        raise OSError("PRIVATE_DIAGNOSTIC after committed success")

    def record_poll_failure(
        self, binding_id: str, *, reason_code: str, detail: Any = None
    ):
        return self.delegate.record_poll_failure(
            binding_id, reason_code=reason_code, detail=detail
        )


def _item(playlist_item_id: str, video_id: str, position: int = 0) -> PlaylistItem:
    return PlaylistItem(
        playlist_item_id=playlist_item_id,
        video_id=video_id,
        position=position,
        published_at="2026-07-20T00:00:00Z",
        title=f"Synthetic Inbox item {position}",
    )


def _page(*items: PlaylistItem, etag: str = '"etag-1"') -> PlaylistItemsPage:
    return PlaylistItemsPage(
        items=tuple(items),
        next_page_token=None,
        etag=etag,
        pagination_truncated=False,
    )


@pytest.fixture(autouse=True)
def _memory_backends(monkeypatch: pytest.MonkeyPatch):
    from app.stores import reset_store_backends

    monkeypatch.setenv("STORE_BACKEND", "memory")
    reset_store_backends()
    reset_memory_source_registry()
    reset_memory_acquisition_requests()
    object_store_module._MEMORY_STORE.clear()
    clear_registry()
    yield
    clear_registry()
    reset_store_backends()
    reset_memory_source_registry()
    reset_memory_acquisition_requests()
    object_store_module._MEMORY_STORE.clear()


@pytest.fixture
def outbox(monkeypatch: pytest.MonkeyPatch) -> FakeOutboxConn:
    conn = FakeOutboxConn()

    def emit(event: Any, conn: Any = None, *, idempotency_key: str) -> str:
        del conn
        return write_outbox_event(event, conn=outbox_conn, idempotency_key=idempotency_key)

    outbox_conn = conn
    monkeypatch.setattr(request_module, "write_outbox_event", emit)
    return conn


def _register_inbox(registry: SourceRegistry, account_binding_id: str):
    row = registry.register(
        collection_kind="inbox_playlist",
        collection_ref=PLAYLIST_A,
        title="Synthetic V1 Inbox",
        account_binding_id=account_binding_id,
    )
    return registry.set_inbox(account_binding_id, row.binding_id)


def _service(
    account_binding_id: str,
    registry: SourceRegistry,
    requests: AcquisitionRequests,
    api: StubApiClient,
) -> YouTubeInboxSyncV1:
    return YouTubeInboxSyncV1(
        account_binding_id=account_binding_id,
        registry=registry,
        requests=requests,
        api_client=api,
        oauth_status=lambda _account: {
            "status": "connected",
            "reason_code": None,
            "refresh_token": "must-not-escape",
        },
    )


def test_v1_selects_exactly_one_enabled_inbox(outbox: FakeOutboxConn) -> None:
    del outbox
    account = str(uuid.uuid4())
    registry = SourceRegistry.for_runtime()
    service = _service(
        account, registry, AcquisitionRequests.for_runtime(), StubApiClient(_page())
    )

    selected = service.select_inbox(
        playlist_ref=PLAYLIST_A, title="Synthetic V1 Inbox"
    )
    same = service.select_inbox(
        playlist_ref=PLAYLIST_A, title="Synthetic V1 Inbox"
    )
    with pytest.raises(V1InboxConfigurationError, match="Liked Videos is unavailable"):
        service.select_inbox(playlist_ref="LL", title="Liked Videos")
    with pytest.raises(V1InboxConfigurationError, match="already has an enabled Inbox"):
        service.select_inbox(playlist_ref=PLAYLIST_B, title="Second Inbox")

    rows = registry.list_for_account(account)
    assert selected.binding_id == same.binding_id
    assert [(row.collection_ref, row.enabled) for row in rows] == [(PLAYLIST_A, True)]

    liked = registry.register(
        collection_kind="liked_videos",
        collection_ref="LL",
        account_binding_id=account,
        title="Liked Videos",
    )
    api = StubApiClient(_page(_item("pli-liked", VIDEO_A)))
    forged_inbox_snapshot = replace(liked, collection_kind="inbox_playlist")
    with pytest.raises(V1InboxConfigurationError, match="only one inbox_playlist"):
        poll_source(
            forged_inbox_snapshot,
            api_client=api,
            requests=AcquisitionRequests.for_runtime(),
            registry=registry,
        )
    assert api.calls == []
    stored_liked = registry.get(liked.binding_id)
    assert stored_liked is not None
    assert stored_liked.cursor == {}
    assert stored_liked.last_success_at is None

    misbound_account = str(uuid.uuid4())
    misbound = registry.register(
        collection_kind="inbox_playlist",
        collection_ref="LL",
        account_binding_id=misbound_account,
        title="Misbound Liked Videos",
    )
    misbound = registry.set_inbox(misbound_account, misbound.binding_id)
    misbound_api = StubApiClient(_page(_item("pli-misbound", VIDEO_A)))
    misbound_service = _service(
        misbound_account,
        registry,
        AcquisitionRequests.for_runtime(),
        misbound_api,
    )
    with pytest.raises(V1InboxConfigurationError, match="Liked Videos is unavailable"):
        misbound_service.sync_now()
    assert misbound_api.calls == []
    stored_misbound = registry.get(misbound.binding_id)
    assert stored_misbound is not None
    assert stored_misbound.cursor == {}
    assert stored_misbound.last_success_at is None


def test_new_inbox_item_enqueues_once_at_production_call_site(
    outbox: FakeOutboxConn,
) -> None:
    account = str(uuid.uuid4())
    registry = SourceRegistry.for_runtime()
    requests = AcquisitionRequests.for_runtime()
    binding = _register_inbox(registry, account)
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
    assert rows[0].discovery_triggers[0]["collection_kind"] == "inbox_playlist"
    assert rows[0].discovery_triggers[0]["playlist_item_id"] == "pli-a"
    assert len(outbox.rows_for(YOUTUBE_SOURCE_DISCOVERED_TOPIC)) == 1


@pytest.mark.parametrize("failure_stage", ["read", "write"])
def test_enqueue_failure_blocks_cursor_prefix(
    outbox: FakeOutboxConn, failure_stage: str
) -> None:
    del outbox
    account = str(uuid.uuid4())
    registry = SourceRegistry.for_runtime()
    requests = AcquisitionRequests.for_runtime()
    binding = _register_inbox(registry, account)
    before = registry.get(binding.binding_id)

    failing_queue: Any = (
        FailingReadQueue() if failure_stage == "read" else FailingQueue(requests)
    )
    with pytest.raises(SourcePollPersistenceError, match="source sync persistence failed") as caught:
        poll_source(
            binding,
            api_client=StubApiClient(
                _page(_item("pli-first", VIDEO_A), _item("pli-fails", VIDEO_B, 1))
            ),
            requests=failing_queue,
            registry=registry,
        )

    after = registry.get(binding.binding_id)
    assert "private diagnostic" not in str(caught.value)
    assert before is not None and after is not None
    assert after.cursor == before.cursor == {}
    assert after.last_success_at is None
    assert after.last_error["reason_code"] == "network_error"
    expected_items = [] if failure_stage == "read" else [VIDEO_A]
    assert [row.item_ref for row in requests.list_all()] == expected_items


@pytest.mark.parametrize(
    "fail_method", ["get", "record_poll_success", "record_poll_failure"]
)
def test_registry_persistence_failures_are_sanitized(
    outbox: FakeOutboxConn, fail_method: str
) -> None:
    del outbox
    account = str(uuid.uuid4())
    registry = SourceRegistry.for_runtime()
    requests = AcquisitionRequests.for_runtime()
    binding = _register_inbox(registry, account)
    api_result: PlaylistItemsPage | YouTubeApiError = _page(
        _item("pli-a", VIDEO_A)
    )
    if fail_method == "record_poll_failure":
        api_result = YouTubeApiError(
            "api_unavailable", 503, "PRIVATE_DIAGNOSTIC from provider"
        )

    with pytest.raises(
        SourcePollPersistenceError, match="source sync persistence failed"
    ) as caught:
        poll_source(
            binding,
            api_client=StubApiClient(api_result),
            requests=requests,
            registry=FailingRegistry(registry, fail_method),
        )

    stored = registry.get(binding.binding_id)
    assert stored is not None
    assert "PRIVATE_DIAGNOSTIC" not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    if fail_method in {"get", "record_poll_success"}:
        assert stored.cursor == {}
        assert stored.last_success_at is None
        assert stored.last_error["reason_code"] == "network_error"
        assert "PRIVATE_DIAGNOSTIC" not in json.dumps(stored.last_error)
    else:
        assert stored.cursor == {}
        assert stored.last_error is None


def test_manual_service_registry_failure_is_sanitized(outbox: FakeOutboxConn) -> None:
    del outbox
    account = str(uuid.uuid4())
    service = YouTubeInboxSyncV1(
        account_binding_id=account,
        registry=FailingListRegistry(),
        requests=AcquisitionRequests.for_runtime(),
        api_client=StubApiClient(_page()),
        oauth_status=lambda _account: {"status": "connected", "reason_code": None},
    )

    for operation in (
        lambda: service.select_inbox(playlist_ref=PLAYLIST_A, title="Inbox"),
        service.sync_now,
    ):
        with pytest.raises(
            SourcePollPersistenceError, match="source sync persistence failed"
        ) as caught:
            operation()
        assert "PRIVATE_DIAGNOSTIC" not in str(caught.value)
        assert caught.value.__cause__ is None
        assert caught.value.__context__ is None

    status = service.status()
    assert status == {
        "status": "degraded",
        "last_success_at": None,
        "latest_error": {
            "reason_code": "network_error",
            "detail": "The YouTube Data API could not be reached.",
        },
    }
    assert "PRIVATE_DIAGNOSTIC" not in json.dumps(status)

    healthy_registry = SourceRegistry.for_runtime()
    oauth_failure_service = YouTubeInboxSyncV1(
        account_binding_id=str(uuid.uuid4()),
        registry=healthy_registry,
        requests=AcquisitionRequests.for_runtime(),
        api_client=StubApiClient(_page()),
        oauth_status=lambda _account: (_ for _ in ()).throw(
            RuntimeError("PRIVATE_DIAGNOSTIC from OAuth status")
        ),
    )
    oauth_failure_status = oauth_failure_service.status()
    assert oauth_failure_status["status"] == "degraded"
    assert oauth_failure_status["latest_error"]["reason_code"] == "api_unavailable"
    assert "PRIVATE_DIAGNOSTIC" not in json.dumps(oauth_failure_status)


def test_committed_success_with_lost_returning_is_reconciled(
    outbox: FakeOutboxConn,
) -> None:
    del outbox
    account = str(uuid.uuid4())
    registry = SourceRegistry.for_runtime()
    requests = AcquisitionRequests.for_runtime()
    binding = _register_inbox(registry, account)

    result = poll_source(
        binding,
        api_client=StubApiClient(_page(_item("pli-a", VIDEO_A))),
        requests=requests,
        registry=CommittedThenRaisedRegistry(registry),
    )

    stored = registry.get(binding.binding_id)
    assert result.degraded is False
    assert result.enqueued == 1
    assert stored is not None
    assert stored.cursor["known_playlist_item_ids"] == ["pli-a"]
    assert stored.last_success_at is not None
    assert stored.last_error is None


def test_no_change_prewrite_failure_is_not_reconciled_as_success(
    outbox: FakeOutboxConn,
) -> None:
    del outbox
    account = str(uuid.uuid4())
    registry = SourceRegistry.for_runtime()
    requests = AcquisitionRequests.for_runtime()
    binding = _register_inbox(registry, account)
    poll_source(
        binding,
        api_client=StubApiClient(_page(_item("pli-a", VIDEO_A))),
        requests=requests,
        registry=registry,
    )
    before = registry.get(binding.binding_id)
    assert before is not None

    with pytest.raises(SourcePollPersistenceError):
        poll_source(
            before,
            api_client=StubApiClient(NotModified(etag='"etag-1"')),
            requests=requests,
            registry=FailingRegistry(registry, "record_poll_success"),
        )

    after = registry.get(binding.binding_id)
    assert after is not None
    assert after.cursor == before.cursor
    assert after.last_success_at == before.last_success_at
    assert after.last_error["reason_code"] == "network_error"


@pytest.mark.parametrize(
    ("reason_code", "status"),
    [("auth_revoked", 401), ("api_unavailable", 503), ("network_error", None)],
)
def test_failed_poll_never_reports_empty_success(
    outbox: FakeOutboxConn, reason_code: str, status: int | None
) -> None:
    account = str(uuid.uuid4())
    registry = SourceRegistry.for_runtime()
    requests = AcquisitionRequests.for_runtime()
    binding = _register_inbox(registry, account)
    poll_source(
        binding,
        api_client=StubApiClient(_page(_item("pli-known", VIDEO_A))),
        requests=requests,
        registry=registry,
    )
    before = registry.get(binding.binding_id)
    result = poll_source(
        before,
        api_client=StubApiClient(
            YouTubeApiError(reason_code, status, "provider secret must not escape")
        ),
        requests=requests,
        registry=registry,
    )
    after = registry.get(binding.binding_id)

    assert result.degraded is True and result.reason_code == reason_code
    assert "secret" not in (result.detail or "")
    assert before is not None and after is not None
    assert after.cursor == before.cursor
    assert after.last_success_at == before.last_success_at
    assert after.last_error["reason_code"] == reason_code
    assert "secret" not in json.dumps(after.last_error)


def test_v1_status_reports_connection_last_success_and_sanitized_error(
    outbox: FakeOutboxConn, monkeypatch: pytest.MonkeyPatch
) -> None:
    del outbox
    account = str(uuid.uuid4())
    registry = SourceRegistry.for_runtime()
    requests = AcquisitionRequests.for_runtime()
    api = StubApiClient(YouTubeApiError("api_unavailable", 503, "private body"))
    service = _service(account, registry, requests, api)
    service.select_inbox(playlist_ref=PLAYLIST_A, title="Synthetic V1 Inbox")

    degraded = service.sync_now()
    degraded_status = service.status()
    assert degraded["status"] == "degraded"
    assert degraded_status["status"] == "degraded"
    assert degraded_status["last_success_at"] is None
    assert degraded_status["latest_error"]["reason_code"] == "api_unavailable"
    assert "private" not in json.dumps(degraded_status)
    assert "refresh_token" not in degraded_status

    api.result = _page(_item("pli-a", VIDEO_A))
    connected = service.sync_now()
    connected_status = service.status()
    assert connected["status"] == "connected"
    assert connected_status["status"] == "connected"
    assert connected_status["last_success_at"] is not None
    assert connected_status["latest_error"] is None

    changed_success_at = connected_status["last_success_at"]
    monkeypatch.setattr(registry_module, "_now_iso", lambda: "2099-01-02T03:04:05+00:00")
    api.result = NotModified(etag='"etag-1"')
    no_change = service.sync_now()
    no_change_status = service.status()
    assert no_change["status"] == "connected"
    assert no_change["not_modified"] is True
    assert no_change_status["status"] == "connected"
    assert no_change_status["last_success_at"] == "2099-01-02T03:04:05+00:00"
    assert no_change_status["last_success_at"] != changed_success_at
    assert no_change_status["latest_error"] is None


def test_manual_inbox_sync_uses_production_poll_route(
    outbox: FakeOutboxConn, monkeypatch: pytest.MonkeyPatch
) -> None:
    del outbox
    account = str(uuid.uuid4())
    registry = SourceRegistry.for_runtime()
    requests = AcquisitionRequests.for_runtime()
    api = StubApiClient(_page(_item("pli-a", VIDEO_A)))
    service = _service(account, registry, requests, api)
    selected = service.select_inbox(
        playlist_ref=PLAYLIST_A, title="Synthetic V1 Inbox"
    )
    production_poll = discovery_module.poll_source
    seen: list[str] = []

    def traced_poll(binding, **kwargs):
        seen.append(binding.binding_id)
        return production_poll(binding, **kwargs)

    monkeypatch.setattr(discovery_module, "poll_source", traced_poll)
    receipt = service.sync_now()

    assert seen == [selected.binding_id]
    assert receipt == {
        "status": "connected",
        "discovered": 1,
        "enqueued": 1,
        "deduped": 0,
        "not_modified": False,
        "reason_code": None,
    }
    assert "token" not in json.dumps(receipt)


def test_inbox_sync_produces_review_required_candidate_never_knowledge(
    outbox: FakeOutboxConn,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    account = str(uuid.uuid4())
    registry = SourceRegistry.for_runtime()
    requests = AcquisitionRequests.for_runtime()
    binding = _register_inbox(registry, account)
    poll_source(
        binding,
        api_client=StubApiClient(_page(_item("pli-a", VIDEO_A))),
        requests=requests,
        registry=registry,
    )

    monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost:5432/app_test")
    monkeypatch.setattr(plugin, "yt_dlp_extract_info", lambda _url: _video_info())
    monkeypatch.setattr(plugin, "fetch_caption_body", lambda _url: _caption_body())
    summary_extractor.register(
        complete=lambda **_kwargs: json.dumps(
            {"summary": "A deterministic Inbox summary.", "confidence": 0.8}
        )
    )

    def forbidden_promotion(*_args: Any, **_kwargs: Any):
        raise AssertionError("Inbox sync must never auto-promote knowledge")

    monkeypatch.setattr(materialization, "materialize_promoted_memory", forbidden_promotion)
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    vault = VaultContext(
        status="selected",
        active_vault_id="vault-test",
        active_vault_name="Vault Test",
        active_vault_path=str(vault_root),
    )
    claimed = requests.claim_batch(1, conn=outbox)
    result = drain_one(
        claimed[0],
        vault_context=vault,
        queue=requests,
        write_guard=WriteGuard(lambda: {"state": "healthy"}),
        conn=outbox,
    )

    note = (vault_root / result.artifact_path).read_text(encoding="utf-8")
    frontmatter = yaml.safe_load(note.split("---", 2)[1])
    assert result.status == "completed"
    assert frontmatter["artifact_class"] == "youtube_source_note"
    assert frontmatter["authority"]["requires_review"] is True
    assert frontmatter["review_state"] == "draft"
    assert frontmatter["triage_state"] == "captured"
    assert not list(vault_root.rglob("*evergreen*"))


def _video_info() -> dict[str, Any]:
    return {
        "id": VIDEO_A,
        "title": "Synthetic Inbox video",
        "channel": "Synthetic Channel",
        "channel_id": "UCsynthetic",
        "upload_date": "20260720",
        "duration": 120,
        "description": "Synthetic fixture",
        "chapters": [],
        "tags": [],
        "language": "en",
        "thumbnail": "https://example.invalid/thumb.jpg",
        "subtitles": {"en": [{"ext": "vtt", "url": "https://example.invalid/caption.vtt"}]},
        "automatic_captions": {},
    }


def _caption_body() -> str:
    return (
        "WEBVTT\n\n"
        "00:00:00.000 --> 00:00:02.000\n"
        "Synthetic Inbox transcript for review.\n"
    )
