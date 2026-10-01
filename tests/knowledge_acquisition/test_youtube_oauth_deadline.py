"""Scheduled OAuth refresh shares the discovery deadline and lease fence."""

from __future__ import annotations

import traceback
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from app.knowledge_acquisition import source_registry as sr
from app.knowledge_acquisition import youtube_account_binding as yab
from app.knowledge_acquisition import youtube_oauth as oauth
from app.knowledge_acquisition import youtube_token_store as tokstore
from tests.knowledge_acquisition.test_youtube_oauth import (
    SENTINEL_ACCESS_2,
    SENTINEL_CLIENT_SECRET,
    SENTINEL_REFRESH,
    SYNTH_PLAYLIST_REF,
    TEST_CLIENT_ID,
    TEST_STORE_KEY,
    _Provider,
    _binder,
    _client,
    _connect_device,
)

pytestmark = pytest.mark.not_pg


@pytest.fixture()
def runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv(tokstore.KEY_ENV_VAR, TEST_STORE_KEY)
    sr.reset_memory_source_registry()
    yab.reset_memory_account_bindings()
    store = tokstore.YouTubeTokenStore(path=tmp_path / "tokens.enc")
    bindings = yab.AccountBindingStore.for_runtime()
    registry = sr.SourceRegistry.for_runtime()
    provider = _Provider()
    result = _connect_device(_binder(provider, store, bindings, registry))
    binding_id = result["account"]["binding_id"]
    token = store.get(binding_id)
    assert token is not None
    store.put(binding_id, token.with_expired_access())
    source = registry.register(
        collection_kind="owned_playlist", collection_ref=SYNTH_PLAYLIST_REF,
        title="Fixture source", account_binding_id=binding_id,
    )
    token_provider = oauth.TokenProvider(
        binding_id=binding_id, token_store=store, binding_store=bindings,
        source_registry=registry, oauth_client=_client(provider),
    )
    yield SimpleNamespace(
        token_provider=token_provider, store=store, bindings=bindings,
        registry=registry, binding_id=binding_id, source=source,
        path=tmp_path / "tokens.enc", provider=provider,
    )
    sr.reset_memory_source_registry()
    yab.reset_memory_account_bindings()


def _snapshot(runtime) -> tuple[Any, ...]:
    return (
        runtime.path.read_bytes(), runtime.bindings.get(runtime.binding_id),
        runtime.registry.get(runtime.source.binding_id),
    )


def test_refresh_stream_stops_at_deadline_without_credential_or_status_writes(runtime):
    clock = [0.0]
    closed = []

    class SlowStream(httpx.SyncByteStream):
        def __iter__(self):
            for byte in b'{"access_token":"private-body-must-not-escape"}':
                clock[0] += 11.0
                yield bytes([byte])

        def close(self):
            closed.append(True)

    runtime.token_provider._client = oauth.OAuthClient(
        client_id=TEST_CLIENT_ID, client_secret=SENTINEL_CLIENT_SECRET,
        http=httpx.Client(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, stream=SlowStream())
        )),
    )
    before = _snapshot(runtime)
    with pytest.raises(oauth.OAuthDeadlineExceeded) as caught:
        runtime.token_provider.get_access_token(deadline=30.0, monotonic=lambda: clock[0])
    assert clock[0] == 33.0  # each chunk arrived before the 30 s read timeout
    assert closed
    assert _snapshot(runtime) == before
    assert "private-body" not in str(caught.value)
    assert caught.value.reason_code == "api_unavailable"


def test_refresh_checks_lease_again_before_persisting_credentials(runtime, monkeypatch):
    class LeaseLost(RuntimeError):
        pass

    lost = LeaseLost("synthetic lease lost")
    active = [True]

    def check_active():
        if not active[0]:
            raise lost

    def refresh(token, **kwargs):
        active[0] = False
        return oauth.TokenBundle(SENTINEL_ACCESS_2, SENTINEL_REFRESH, 3600, oauth.SCOPE, "Bearer")

    monkeypatch.setattr(runtime.token_provider._client, "refresh", refresh)
    before = _snapshot(runtime)
    with pytest.raises(LeaseLost) as caught:
        runtime.token_provider.get_access_token(check_active=check_active)
    assert caught.value is lost
    assert _snapshot(runtime) == before


def test_lease_loss_during_token_read_does_not_degrade_auth(runtime, monkeypatch):
    class LeaseLost(RuntimeError):
        pass

    lost = LeaseLost("synthetic lease lost")
    active = [True]

    def check_active():
        if not active[0]:
            raise lost

    def unavailable(binding_id):
        active[0] = False
        raise tokstore.TokenStoreKeyMissingError("synthetic missing key")

    before = _snapshot(runtime)
    monkeypatch.setattr(runtime.store, "get", unavailable)
    with pytest.raises(LeaseLost) as caught:
        runtime.token_provider.get_access_token(check_active=check_active)
    assert caught.value is lost
    assert _snapshot(runtime) == before


def test_expired_deadline_does_not_read_credentials_or_start_network(runtime, monkeypatch):
    before = _snapshot(runtime)
    request_count = len(runtime.provider.requests)

    def unexpected_read(binding_id):
        pytest.fail("expired work must not read the token store")

    monkeypatch.setattr(runtime.store, "get", unexpected_read)
    with pytest.raises(oauth.OAuthDeadlineExceeded):
        runtime.token_provider.get_access_token(deadline=3.0, monotonic=lambda: 3.0)
    assert len(runtime.provider.requests) == request_count
    assert _snapshot(runtime) == before


def test_bounded_refresh_caps_http_timeout_and_keeps_token_rotation(runtime):
    requests = []

    def transport(request):
        requests.append(request)
        return httpx.Response(200, json={
            "access_token": SENTINEL_ACCESS_2, "refresh_token": "synthetic-rotated-token",
            "expires_in": 3600, "scope": oauth.SCOPE, "token_type": "Bearer",
        })

    runtime.bindings.set_state(runtime.binding_id, state="degraded", reason_code="auth_expired")
    runtime.token_provider._client = oauth.OAuthClient(
        client_id=TEST_CLIENT_ID, client_secret=SENTINEL_CLIENT_SECRET,
        http=httpx.Client(transport=httpx.MockTransport(transport)),
    )
    value = runtime.token_provider.get_access_token(deadline=20.0, monotonic=lambda: 12.0)
    assert value == SENTINEL_ACCESS_2
    assert set(requests[0].extensions["timeout"].values()) == {8.0}
    assert runtime.store.get(runtime.binding_id).refresh_token == "synthetic-rotated-token"
    assert runtime.bindings.get(runtime.binding_id).state == "connected"


def test_unbounded_refresh_remains_compatible_with_legacy_client(runtime, monkeypatch):
    def legacy_refresh(token):
        return oauth.TokenBundle(SENTINEL_ACCESS_2, None, 3600, oauth.SCOPE, "Bearer")

    monkeypatch.setattr(runtime.token_provider._client, "refresh", legacy_refresh)
    assert runtime.token_provider.get_access_token() == SENTINEL_ACCESS_2
    assert runtime.store.get(runtime.binding_id).refresh_token == SENTINEL_REFRESH


def test_revoked_response_after_lease_loss_does_not_degrade_auth(runtime, monkeypatch):
    lost = RuntimeError("synthetic lease lost")
    active = [True]

    def check_active():
        if not active[0]:
            raise lost

    def revoked(token, **kwargs):
        active[0] = False
        raise oauth.AuthDegradedError("auth_revoked")

    monkeypatch.setattr(runtime.token_provider._client, "refresh", revoked)
    before = _snapshot(runtime)
    with pytest.raises(RuntimeError) as caught:
        runtime.token_provider.get_access_token(check_active=check_active)
    assert caught.value is lost
    assert _snapshot(runtime) == before


def test_lease_loss_after_token_write_prevents_later_status_clear(runtime, monkeypatch):
    lost = RuntimeError("synthetic lease lost")
    active = [True]

    def check_active():
        if not active[0]:
            raise lost

    original_put = runtime.store.put

    def put_then_lose(binding_id, token):
        original_put(binding_id, token)
        active[0] = False

    runtime.bindings.set_state(runtime.binding_id, state="degraded", reason_code="auth_expired")
    before_binding = runtime.bindings.get(runtime.binding_id)
    monkeypatch.setattr(runtime.store, "put", put_then_lose)
    with pytest.raises(RuntimeError) as caught:
        runtime.token_provider.get_access_token(check_active=check_active)
    assert caught.value is lost
    assert runtime.bindings.get(runtime.binding_id) == before_binding


def test_deadline_during_transport_failure_keeps_provider_diagnostic_private(runtime):
    clock = [0.0]

    def transport(request):
        clock[0] = 31.0
        raise httpx.ReadTimeout("private-synthetic-provider-diagnostic")

    runtime.token_provider._client = oauth.OAuthClient(
        client_id=TEST_CLIENT_ID, client_secret=SENTINEL_CLIENT_SECRET,
        http=httpx.Client(transport=httpx.MockTransport(transport)),
    )
    before = _snapshot(runtime)
    with pytest.raises(oauth.OAuthDeadlineExceeded) as caught:
        runtime.token_provider.get_access_token(deadline=30.0, monotonic=lambda: clock[0])
    assert "private-synthetic-provider-diagnostic" not in "".join(
        traceback.format_exception(caught.value)
    )
    assert _snapshot(runtime) == before


@pytest.mark.parametrize("effect", ["account_failure", "source_failure", "status_clear"])
def test_refresh_shared_status_effect_refuses_stale_holder(runtime, effect):
    from contextlib import contextmanager
    from datetime import datetime, timedelta, timezone
    from app.knowledge_acquisition.sync_scheduler import LEASE_KEY, LEASE_TTL_SECONDS
    from app.knowledge_acquisition.sync_state import MemorySyncStateStore, SyncLeaseLostError
    from tests.knowledge_acquisition.test_youtube_oauth import _invalid_grant

    state = MemorySyncStateStore()
    now = [datetime.now(timezone.utc)]
    assert state.acquire_lease(key=LEASE_KEY, holder="old", ttl_seconds=LEASE_TTL_SECONDS, now=now[0])
    if effect == "status_clear":
        runtime.bindings.set_state(runtime.binding_id, state="degraded", reason_code="auth_expired")
    else:
        runtime.provider.token_responses.append(_invalid_grant())
    before_source = runtime.registry.get(runtime.source.binding_id)
    before_binding = runtime.bindings.get(runtime.binding_id)
    admissions = []

    def check_active():
        if not state.heartbeat_lease(key=LEASE_KEY, holder="old", ttl_seconds=LEASE_TTL_SECONDS, now=now[0]):
            raise SyncLeaseLostError("fixture lost ownership")

    @contextmanager
    def commit_guard():
        admissions.append(effect)
        target = 2 if effect == "source_failure" else 1
        if len(admissions) == target:
            now[0] += timedelta(seconds=LEASE_TTL_SECONDS + 1)
            assert state.acquire_lease(key=LEASE_KEY, holder="new", ttl_seconds=LEASE_TTL_SECONDS, now=now[0])
        with state.owned_effect(key=LEASE_KEY, holder="old", now=now[0]) as conn:
            yield conn

    with pytest.raises(SyncLeaseLostError):
        runtime.token_provider.get_access_token(check_active=check_active, commit_guard=commit_guard)
    assert runtime.registry.get(runtime.source.binding_id) == before_source
    if effect == "source_failure":
        # Earlier admitted account failure is legitimate; the later source write is refused.
        assert runtime.bindings.get(runtime.binding_id).state == "degraded"
    else:
        assert runtime.bindings.get(runtime.binding_id) == before_binding
    assert state.get(LEASE_KEY)["holder"] == "new"
