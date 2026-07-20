"""YSS-02 (#3917): OAuth account binding + encrypted token store.

Every network egress is stubbed at the httpx transport layer
(``httpx.MockTransport``), so the production request-building code paths run
unchanged and the outgoing requests can be asserted directly (AC7). No real
Google credentials, no real playlist/channel/account identifiers (INV-YSS-9);
every id here is a synthetic ``__test__`` constant.

The binding contract is ``docs/YOUTUBE_SOURCE_SYNC/SOURCE_SYNC_CONTRACT.md ::
Secrets and private bindings`` and INV-YSS-4 / INV-YSS-5 in that dir's README.
"""

from __future__ import annotations

import json
import logging
import secrets
import stat
import subprocess
import sys
import threading
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from app.knowledge_acquisition import source_registry as sr
from app.knowledge_acquisition import youtube_account_binding as yab
from app.knowledge_acquisition import youtube_oauth as oauth
from app.knowledge_acquisition import youtube_token_store as tokstore

# --- Synthetic constants (INV-YSS-9: never a real id, ever) -----------------

SYNTH_CHANNEL_ID = "UC__test__synthetic_channel_00"
SYNTH_CHANNEL_TITLE = "Test Fixture Channel"
SYNTH_PLAYLIST_REF = "PL__test__synthetic_playlist_00"

# Planted secrets: if any of these ever surfaces in a log line, receipt,
# exception, or --json payload, AC5 fails. They are deliberately distinctive.
SENTINEL_REFRESH = "sentinel-REFRESH-must-never-leak-" + secrets.token_hex(8)
SENTINEL_REFRESH_2 = "sentinel-REFRESH2-must-never-leak-" + secrets.token_hex(8)
SENTINEL_ACCESS = "sentinel-ACCESS-must-never-leak-" + secrets.token_hex(8)
SENTINEL_ACCESS_2 = "sentinel-ACCESS2-must-never-leak-" + secrets.token_hex(8)
SENTINEL_CLIENT_SECRET = "sentinel-CLIENTSECRET-must-never-leak-" + secrets.token_hex(8)
SENTINEL_DEVICE_CODE = "sentinel-DEVICECODE-must-never-leak-" + secrets.token_hex(8)

TEST_CLIENT_ID = "test-client-id.apps.googleusercontent.example"
# 64 hex chars => 32 bytes AES-256 key
TEST_STORE_KEY = secrets.token_hex(32)

_ALL_SENTINELS = (
    SENTINEL_REFRESH,
    SENTINEL_REFRESH_2,
    SENTINEL_ACCESS,
    SENTINEL_ACCESS_2,
    SENTINEL_CLIENT_SECRET,
    SENTINEL_DEVICE_CODE,
)


def _assert_no_exception_chain(error: BaseException) -> None:
    """Secret-bearing failures must not survive in hidden exception links."""
    seen: set[int] = set()
    pending = [error]
    while pending:
        current = pending.pop()
        assert id(current) not in seen
        seen.add(id(current))
        assert current.__cause__ is None
        assert current.__context__ is None


# --- Transport stub ---------------------------------------------------------


class _Provider:
    """Scriptable Google-OAuth stub bound to a ``httpx.MockTransport``.

    Records every request so tests can assert on the production call site.
    """

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.token_responses: list[httpx.Response] = []
        self.revoke_responses: list[httpx.Response] = []
        self.revoked: list[dict[str, str]] = []
        self.revoke_started = threading.Event()
        self.revoke_release: threading.Event | None = None
        self.device_granted = True

    def _body(self, request: httpx.Request) -> dict[str, str]:
        raw = request.content.decode() if request.content else ""
        return {k: v[0] for k, v in parse_qs(raw).items()}

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = urlsplit(str(request.url)).path
        if path.endswith("/device/code"):
            return httpx.Response(
                200,
                request=request,
                json={
                    "device_code": SENTINEL_DEVICE_CODE,
                    "user_code": "WXYZ-ABCD",
                    "verification_url": "https://www.google.com/device",
                    "verification_url_complete": "https://www.google.com/device?user_code=WXYZ-ABCD",
                    "expires_in": 1800,
                    "interval": 5,
                },
            )
        if path.endswith("/token"):
            if self.token_responses:
                return self.token_responses.pop(0)
            return httpx.Response(
                200,
                request=request,
                json={
                    "access_token": SENTINEL_ACCESS,
                    "refresh_token": SENTINEL_REFRESH,
                    "expires_in": 3600,
                    "scope": oauth.SCOPE,
                    "token_type": "Bearer",
                },
            )
        if path.endswith("/revoke"):
            self.revoked.append(self._body(request))
            self.revoke_started.set()
            if self.revoke_release is not None:
                self.revoke_release.wait(timeout=5)
            if self.revoke_responses:
                return self.revoke_responses.pop(0)
            return httpx.Response(200, request=request, json={})
        return httpx.Response(404, request=request, json={"error": "not_found"})  # pragma: no cover


def _granted_token(access: str = SENTINEL_ACCESS, refresh: str = SENTINEL_REFRESH) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "access_token": access,
            "refresh_token": refresh,
            "expires_in": 3600,
            "scope": oauth.SCOPE,
            "token_type": "Bearer",
        },
    )


def _invalid_grant() -> httpx.Response:
    return httpx.Response(400, json={"error": "invalid_grant", "error_description": "Token has been revoked."})


def _client(provider: _Provider, *, follow_redirects: bool = False) -> oauth.OAuthClient:
    http = httpx.Client(
        transport=httpx.MockTransport(provider.handler),
        follow_redirects=follow_redirects,
    )
    return oauth.OAuthClient(client_id=TEST_CLIENT_ID, client_secret=SENTINEL_CLIENT_SECRET, http=http)


def _identity_probe(_access_token: str) -> oauth.ChannelIdentity:
    return oauth.ChannelIdentity(channel_id=SYNTH_CHANNEL_ID, channel_title=SYNTH_CHANNEL_TITLE)


# --- Fixtures ---------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_memory_backends(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv(tokstore.KEY_ENV_VAR, TEST_STORE_KEY)
    monkeypatch.setenv(oauth.CLIENT_ID_ENV, TEST_CLIENT_ID)
    monkeypatch.setenv(oauth.CLIENT_SECRET_ENV, SENTINEL_CLIENT_SECRET)
    sr.reset_memory_source_registry()
    yab.reset_memory_account_bindings()
    yield
    sr.reset_memory_source_registry()
    yab.reset_memory_account_bindings()


@pytest.fixture()
def store(tmp_path: Path) -> tokstore.YouTubeTokenStore:
    return tokstore.YouTubeTokenStore(path=tmp_path / "youtube_token_store.enc")


@pytest.fixture()
def bindings() -> yab.AccountBindingStore:
    return yab.AccountBindingStore.for_runtime()


@pytest.fixture()
def registry() -> sr.SourceRegistry:
    return sr.SourceRegistry.for_runtime()


def _binder(
    provider: _Provider,
    store: tokstore.YouTubeTokenStore,
    bindings: yab.AccountBindingStore,
    registry: sr.SourceRegistry,
    *,
    follow_redirects: bool = False,
    identity_probe: oauth.IdentityProbe = _identity_probe,
) -> oauth.YouTubeAccountBinder:
    return oauth.YouTubeAccountBinder(
        oauth_client=_client(provider, follow_redirects=follow_redirects),
        token_store=store,
        binding_store=bindings,
        source_registry=registry,
        identity_probe=identity_probe,
    )


def _connect_device(binder: oauth.YouTubeAccountBinder) -> dict:
    connection = binder.start_device_connection()
    return binder.finish_device_connection(connection)


# --- AC1 --------------------------------------------------------------------


def test_device_flow_persists_encrypted_only(store, bindings, registry, tmp_path):
    provider = _Provider()
    binder = _binder(provider, store, bindings, registry)

    result = _connect_device(binder)
    assert result["status"] == "connected"
    binding_id = result["account"]["binding_id"]

    # The token round-trips through the encrypted store with the key present.
    loaded = store.get(binding_id)
    assert loaded is not None
    assert loaded.refresh_token == SENTINEL_REFRESH
    assert loaded.access_token == SENTINEL_ACCESS

    # ...but the on-disk bytes carry no plaintext token material.
    raw = (tmp_path / "youtube_token_store.enc").read_bytes()
    for sentinel in (SENTINEL_REFRESH, SENTINEL_ACCESS):
        assert sentinel.encode() not in raw
    # ...and are unreadable without the key (fail closed, no plaintext path).
    import os

    del os.environ[tokstore.KEY_ENV_VAR]
    reopened = tokstore.YouTubeTokenStore(path=tmp_path / "youtube_token_store.enc")
    with pytest.raises(tokstore.TokenStoreKeyMissingError):
        reopened.get(binding_id)


# --- AC2 --------------------------------------------------------------------


def test_loopback_flow_rejects_tampered_state(store, bindings, registry):
    provider = _Provider()
    client = _client(provider)

    flow = oauth.start_loopback_flow(client, redirect_uri="http://127.0.0.1:8765/callback")

    parts = urlsplit(flow.authorization_url)
    assert parts.netloc == "accounts.google.com"
    params = {k: v[0] for k, v in parse_qs(parts.query).items()}
    assert params["scope"] == oauth.SCOPE
    assert params["code_challenge_method"] == "S256"
    assert params["code_challenge"] and params["code_challenge"] != flow.code_verifier
    assert params["state"] == flow.state
    assert params["response_type"] == "code"

    # A tampered state must be refused before any code exchange happens.
    with pytest.raises(oauth.OAuthStateMismatchError):
        oauth.complete_loopback_flow(
            client, flow, returned_state=flow.state + "-tampered", returned_code="whatever"
        )
    assert not any(urlsplit(str(r.url)).path.endswith("/token") for r in provider.requests)

    # The honest state exchanges the code, forwarding the PKCE verifier.
    bundle = oauth.complete_loopback_flow(
        client, flow, returned_state=flow.state, returned_code="auth-code-xyz"
    )
    assert bundle.access_token == SENTINEL_ACCESS
    token_req = next(r for r in provider.requests if urlsplit(str(r.url)).path.endswith("/token"))
    body = {k: v[0] for k, v in parse_qs(token_req.content.decode()).items()}
    assert body["code_verifier"] == flow.code_verifier
    assert body["grant_type"] == "authorization_code"


# --- AC3 --------------------------------------------------------------------


def test_missing_store_key_fails_closed(store, bindings, registry, monkeypatch):
    provider = _Provider()
    binder = _binder(provider, store, bindings, registry)
    result = _connect_device(binder)
    binding_id = result["account"]["binding_id"]

    # Key vanishes (e.g. host secret not re-provisioned after restart).
    monkeypatch.delenv(tokstore.KEY_ENV_VAR, raising=False)

    status = binder.status(binding_id)
    assert status["status"] == "degraded"
    assert status["reason_code"] == "auth_key_missing"

    provider_client = _client(provider)
    tp = oauth.TokenProvider(
        binding_id=binding_id,
        token_store=store,
        oauth_client=provider_client,
        binding_store=bindings,
        source_registry=registry,
    )
    with pytest.raises(oauth.AuthDegradedError) as excinfo:
        tp.get_access_token()
    assert excinfo.value.reason_code == "auth_key_missing"

    # No plaintext read path exists: the store itself refuses without a key.
    with pytest.raises(tokstore.TokenStoreKeyMissingError):
        store.get(binding_id)


@pytest.mark.parametrize("configured_key", [None, "not-valid-hex"])
def test_connect_token_store_failure_does_not_create_connected_binding(
    store, bindings, registry, monkeypatch, configured_key
):
    provider = _Provider()
    binder = _binder(provider, store, bindings, registry)
    if configured_key is None:
        monkeypatch.delenv(tokstore.KEY_ENV_VAR, raising=False)
    else:
        monkeypatch.setenv(tokstore.KEY_ENV_VAR, configured_key)

    with pytest.raises(tokstore.TokenStoreKeyMissingError):
        _connect_device(binder)

    assert bindings.list_all() == ()
    assert store.binding_ids() == ()
    assert not any(urlsplit(str(r.url)).path.endswith("/token") for r in provider.requests)


def test_connect_store_io_preflight_fails_before_provider_poll(
    store, bindings, registry, monkeypatch
):
    provider = _Provider()
    binder = _binder(provider, store, bindings, registry)

    def fail_readiness():
        raise OSError("synthetic token-store readiness failure")

    monkeypatch.setattr(store, "preflight_write_ready", fail_readiness)

    with pytest.raises(OSError, match="synthetic token-store readiness failure"):
        _connect_device(binder)

    assert not any(urlsplit(str(r.url)).path.endswith("/token") for r in provider.requests)
    assert provider.revoked == []
    assert bindings.list_all() == ()


def test_identity_probe_failure_is_provider_compensated_without_secret_leak(
    store, bindings, registry
):
    provider = _Provider()

    def fail_identity(_access_token):
        raise RuntimeError(SENTINEL_ACCESS)

    binder = _binder(
        provider,
        store,
        bindings,
        registry,
        identity_probe=fail_identity,
    )

    with pytest.raises(oauth.OAuthGrantDurabilityError) as excinfo:
        _connect_device(binder)

    assert excinfo.value.reason_code == "grant_compensated"
    assert excinfo.value.pending_grant_id is None
    assert provider.revoked == [{"token": SENTINEL_REFRESH}]
    assert store.binding_ids() == ()
    assert bindings.list_all() == ()
    rendered = repr(excinfo.value) + str(excinfo.value)
    assert SENTINEL_ACCESS not in rendered
    assert SENTINEL_REFRESH not in rendered
    _assert_no_exception_chain(excinfo.value)


def test_incomplete_grant_with_refresh_token_is_compensated_not_discarded(
    store, bindings, registry
):
    provider = _Provider()
    provider.token_responses.append(
        httpx.Response(
            200,
            json={
                "refresh_token": SENTINEL_REFRESH,
                "expires_in": 3600,
                "scope": oauth.SCOPE,
                "token_type": "Bearer",
            },
        )
    )
    binder = _binder(provider, store, bindings, registry)

    with pytest.raises(oauth.OAuthGrantDurabilityError) as excinfo:
        _connect_device(binder)

    assert excinfo.value.reason_code == "grant_compensated"
    assert provider.revoked == [{"token": SENTINEL_REFRESH}]
    assert store.binding_ids() == ()
    assert bindings.list_all() == ()
    assert SENTINEL_REFRESH not in (repr(excinfo.value) + str(excinfo.value))


def test_identity_probe_and_compensation_failure_preserve_encrypted_pending_authority(
    store, bindings, registry, tmp_path
):
    provider = _Provider()
    provider.revoke_responses.append(
        httpx.Response(
            503,
            json={"error": "temporarily_unavailable", "error_description": SENTINEL_ACCESS},
        )
    )

    def fail_identity(_access_token):
        raise RuntimeError(SENTINEL_REFRESH)

    binder = _binder(
        provider,
        store,
        bindings,
        registry,
        identity_probe=fail_identity,
    )

    with pytest.raises(oauth.OAuthGrantDurabilityError) as excinfo:
        _connect_device(binder)

    assert excinfo.value.reason_code == "grant_pending"
    pending_id = excinfo.value.pending_grant_id
    assert pending_id is not None
    assert store.binding_ids() == (pending_id,)
    assert store.get(pending_id).refresh_token == SENTINEL_REFRESH
    assert bindings.list_all() == ()
    raw = (tmp_path / "youtube_token_store.enc").read_bytes()
    assert SENTINEL_REFRESH.encode() not in raw
    assert SENTINEL_ACCESS.encode() not in raw
    rendered = repr(excinfo.value) + str(excinfo.value)
    assert SENTINEL_REFRESH not in rendered
    assert SENTINEL_ACCESS not in rendered
    _assert_no_exception_chain(excinfo.value)

    retried = binder.retry_pending_grant_compensation(pending_id)
    assert retried == {"status": "compensated", "pending_grant_id": pending_id}
    assert store.binding_ids() == ()


def test_pending_journal_write_failure_is_provider_compensated(
    store, bindings, registry, monkeypatch
):
    provider = _Provider()
    binder = _binder(provider, store, bindings, registry)

    def fail_pending_write(_binding_id, _token):
        raise OSError("synthetic pending journal write failure")

    monkeypatch.setattr(store, "put", fail_pending_write)

    with pytest.raises(oauth.OAuthGrantDurabilityError) as excinfo:
        _connect_device(binder)

    assert excinfo.value.reason_code == "grant_compensated"
    _assert_no_exception_chain(excinfo.value)
    assert provider.revoked == [{"token": SENTINEL_REFRESH}]
    assert store.binding_ids() == ()
    assert bindings.list_all() == ()


def test_pending_write_and_compensation_failure_retry_preserves_authority(
    store, bindings, registry, monkeypatch
):
    provider = _Provider()
    provider.revoke_responses.append(
        httpx.Response(503, json={"error": "temporarily_unavailable"})
    )
    binder = _binder(provider, store, bindings, registry)
    original_put = store.put
    writes = 0

    def fail_first_pending_write(binding_id, token):
        nonlocal writes
        writes += 1
        if writes == 1:
            raise OSError("synthetic first pending write failure")
        original_put(binding_id, token)

    monkeypatch.setattr(store, "put", fail_first_pending_write)

    with pytest.raises(oauth.OAuthGrantDurabilityError) as excinfo:
        _connect_device(binder)

    assert excinfo.value.reason_code == "grant_pending"
    pending_id = excinfo.value.pending_grant_id
    assert pending_id is not None
    assert writes == 2
    assert store.get(pending_id).refresh_token == SENTINEL_REFRESH
    assert bindings.list_all() == ()


def test_pending_journal_write_lost_ack_returns_retry_handle_without_revocation(
    store, bindings, registry, monkeypatch
):
    provider = _Provider()
    binder = _binder(provider, store, bindings, registry)
    original_put = store.put
    first_write = True

    def persist_pending_then_lose_ack(binding_id, token):
        nonlocal first_write
        original_put(binding_id, token)
        if first_write:
            first_write = False
            raise OSError(SENTINEL_REFRESH)

    monkeypatch.setattr(store, "put", persist_pending_then_lose_ack)

    with pytest.raises(oauth.OAuthGrantDurabilityError) as excinfo:
        _connect_device(binder)

    assert excinfo.value.reason_code == "grant_pending"
    pending_id = excinfo.value.pending_grant_id
    assert pending_id is not None
    assert store.binding_ids() == (pending_id,)
    assert store.get(pending_id).refresh_token == SENTINEL_REFRESH
    assert provider.revoked == []
    assert SENTINEL_REFRESH not in (repr(excinfo.value) + str(excinfo.value))
    _assert_no_exception_chain(excinfo.value)


def test_pending_parent_directory_fsync_lost_ack_keeps_retry_authority(
    store, bindings, registry, monkeypatch
):
    provider = _Provider()
    binder = _binder(provider, store, bindings, registry)
    original_fsync = tokstore.os.fsync
    directory_fsyncs = 0

    def lose_second_directory_fsync_ack(descriptor):
        nonlocal directory_fsyncs
        if stat.S_ISDIR(tokstore.os.fstat(descriptor).st_mode):
            directory_fsyncs += 1
            if directory_fsyncs == 2:
                raise OSError(SENTINEL_REFRESH)
        original_fsync(descriptor)

    monkeypatch.setattr(tokstore.os, "fsync", lose_second_directory_fsync_ack)

    with pytest.raises(oauth.OAuthGrantDurabilityError) as excinfo:
        _connect_device(binder)

    assert directory_fsyncs == 2  # readiness, then pending-grant journal
    assert excinfo.value.reason_code == "grant_pending"
    pending_id = excinfo.value.pending_grant_id
    assert pending_id is not None
    assert store.binding_ids() == (pending_id,)
    assert store.get(pending_id).refresh_token == SENTINEL_REFRESH
    assert provider.revoked == []
    assert SENTINEL_REFRESH not in (repr(excinfo.value) + str(excinfo.value))
    _assert_no_exception_chain(excinfo.value)


def test_binding_store_write_failure_leaves_pending_grant_recoverable(
    store, bindings, registry, monkeypatch
):
    provider = _Provider()
    binder = _binder(provider, store, bindings, registry)
    original_put = store.put
    writes: list[str] = []

    def fail_canonical_write(binding_id, token):
        writes.append(binding_id)
        if len(writes) == 2:
            raise OSError(SENTINEL_REFRESH)
        original_put(binding_id, token)

    monkeypatch.setattr(store, "put", fail_canonical_write)

    with pytest.raises(oauth.OAuthGrantDurabilityError) as excinfo:
        _connect_device(binder)

    assert excinfo.value.reason_code == "grant_pending"
    assert len(writes) == 2
    pending_id = excinfo.value.pending_grant_id
    assert pending_id == writes[0]
    assert pending_id.startswith("pending-youtube-grant-")
    assert store.binding_ids() == (pending_id,)
    assert store.get(pending_id).refresh_token == SENTINEL_REFRESH
    assert bindings.list_all() == ()
    assert SENTINEL_REFRESH not in (repr(excinfo.value) + str(excinfo.value))
    _assert_no_exception_chain(excinfo.value)


def test_reconnect_write_failure_does_not_mistake_old_token_for_new_grant_durability(
    store, bindings, registry, monkeypatch
):
    provider = _Provider()
    binder = _binder(provider, store, bindings, registry)
    connected = _connect_device(binder)
    binding_id = connected["account"]["binding_id"]
    provider.token_responses.append(
        _granted_token(access=SENTINEL_ACCESS_2, refresh=SENTINEL_REFRESH_2)
    )
    reconnect = binder.start_reconnect(binding_id)
    original_put = store.put
    writes: list[str] = []

    def fail_reconnect_canonical_write(target_id, token):
        writes.append(target_id)
        if len(writes) == 2:
            raise OSError(SENTINEL_REFRESH_2)
        original_put(target_id, token)

    monkeypatch.setattr(store, "put", fail_reconnect_canonical_write)

    with pytest.raises(oauth.OAuthGrantDurabilityError) as excinfo:
        binder.finish_device_connection(reconnect)

    assert excinfo.value.reason_code == "grant_pending"
    pending_id = excinfo.value.pending_grant_id
    assert pending_id == writes[0]
    assert pending_id.startswith("pending-youtube-grant-")
    assert writes[1] == binding_id
    assert set(store.binding_ids()) == {binding_id, pending_id}
    assert store.get(binding_id).refresh_token == SENTINEL_REFRESH
    assert store.get(pending_id).refresh_token == SENTINEL_REFRESH_2
    assert SENTINEL_REFRESH_2 not in (repr(excinfo.value) + str(excinfo.value))
    _assert_no_exception_chain(excinfo.value)


def test_reconnect_canonical_write_lost_ack_rolls_forward_without_revoking_new_grant(
    store, bindings, registry, monkeypatch
):
    provider = _Provider()
    binder = _binder(provider, store, bindings, registry)
    connected = _connect_device(binder)
    binding_id = connected["account"]["binding_id"]
    provider.token_responses.append(
        _granted_token(access=SENTINEL_ACCESS_2, refresh=SENTINEL_REFRESH_2)
    )
    reconnect = binder.start_reconnect(binding_id)
    pending_id = oauth._pending_grant_id(reconnect.handle.device_code, binding_id)
    original_put = store.put

    def persist_canonical_then_lose_ack(target_id, token):
        original_put(target_id, token)
        if target_id == binding_id:
            raise OSError(SENTINEL_REFRESH_2)

    monkeypatch.setattr(store, "put", persist_canonical_then_lose_ack)

    result = binder.finish_device_connection(reconnect)

    assert result == {
        "status": "connected",
        "account": {"binding_id": binding_id, "channel_title": SYNTH_CHANNEL_TITLE},
    }
    assert store.binding_ids() == (binding_id,)
    assert store.get(binding_id).refresh_token == SENTINEL_REFRESH_2
    assert provider.revoked == []

    # A stale retry handle is absent and therefore can never revoke the new
    # canonical grant whose exact readback already proved lost-ack success.
    retried = binder.retry_pending_grant_compensation(pending_id)
    assert retried == {"status": "absent", "pending_grant_id": pending_id}
    assert provider.revoked == []


def test_connect_post_commit_exception_reconciles_without_deleting_token(
    store, bindings, registry, monkeypatch
):
    provider = _Provider()
    binder = _binder(provider, store, bindings, registry)
    original_create = bindings.create
    committed_ids: list[str] = []

    def create_then_lose_acknowledgement(**kwargs):
        committed = original_create(**kwargs)
        committed_ids.append(committed.account_binding_id)
        raise RuntimeError("synthetic lost insert acknowledgement")

    monkeypatch.setattr(bindings, "create", create_then_lose_acknowledgement)

    first = _connect_device(binder)
    binding_id = first["account"]["binding_id"]

    assert first["status"] == "connected"
    assert committed_ids == [binding_id]
    assert bindings.get(binding_id).state == "connected"
    assert store.get(binding_id).refresh_token == SENTINEL_REFRESH

    # A retry converges through the same channel row instead of creating a
    # second binding or credential record.
    second = _connect_device(binder)
    assert second["account"]["binding_id"] == binding_id
    assert len(bindings.list_all()) == 1
    assert store.binding_ids() == (binding_id,)


def test_connect_precommit_binding_failure_preserves_deterministic_retry_authority(
    store, bindings, registry, monkeypatch
):
    binder = _binder(_Provider(), store, bindings, registry)

    def fail_before_insert(**_kwargs):
        raise RuntimeError("synthetic pre-insert failure")

    monkeypatch.setattr(bindings, "create", fail_before_insert)

    with pytest.raises(RuntimeError, match="synthetic pre-insert failure"):
        _connect_device(binder)

    assert bindings.list_all() == ()
    first_candidate_ids = store.binding_ids()
    assert len(first_candidate_ids) == 1
    assert store.get(first_candidate_ids[0]).refresh_token == SENTINEL_REFRESH

    # Another failed attempt targets the same idempotency key rather than
    # accumulating uncorrelated credential records.
    with pytest.raises(RuntimeError, match="synthetic pre-insert failure"):
        _connect_device(binder)
    assert store.binding_ids() == first_candidate_ids


def test_connect_delayed_commit_after_negative_readbacks_preserves_and_converges(
    store, bindings, registry, monkeypatch
):
    binder = _binder(_Provider(), store, bindings, registry)
    original_create = bindings.create
    original_get = bindings.get
    original_get_by_channel_id = bindings.get_by_channel_id
    create_kwargs: dict[str, object] = {}
    readbacks: list[str] = []

    def lose_ack_before_delayed_commit(**kwargs):
        create_kwargs.update(kwargs)
        raise RuntimeError("synthetic delayed insert acknowledgement")

    def negative_exact_readback(_binding_id):
        readbacks.append("exact")
        return None

    def negative_channel_readback(_channel_id):
        if not create_kwargs:
            # Initial identity resolution happens before create is attempted.
            return None
        readbacks.append("channel")
        # The insert becomes visible only after both negative snapshots. This
        # is precisely why absence at either read is not temporal proof.
        original_create(**create_kwargs)
        return None

    monkeypatch.setattr(bindings, "create", lose_ack_before_delayed_commit)
    monkeypatch.setattr(bindings, "get", negative_exact_readback)
    monkeypatch.setattr(bindings, "get_by_channel_id", negative_channel_readback)

    with pytest.raises(RuntimeError, match="synthetic delayed insert acknowledgement"):
        _connect_device(binder)

    assert readbacks == ["exact", "channel"]
    candidate_id = str(create_kwargs["account_binding_id"])
    assert store.binding_ids() == (candidate_id,)
    assert store.get(candidate_id).refresh_token == SENTINEL_REFRESH

    monkeypatch.setattr(bindings, "create", original_create)
    monkeypatch.setattr(bindings, "get", original_get)
    monkeypatch.setattr(bindings, "get_by_channel_id", original_get_by_channel_id)

    # Retry resolves the delayed row, retains its deterministic id, and does
    # not create a second binding or credential record.
    retried = _connect_device(binder)
    assert retried["account"]["binding_id"] == candidate_id
    assert [row.account_binding_id for row in bindings.list_all()] == [candidate_id]
    assert store.binding_ids() == (candidate_id,)


def test_connect_indeterminate_create_readback_preserves_token(
    store, bindings, registry, monkeypatch
):
    binder = _binder(_Provider(), store, bindings, registry)

    def fail_create(**_kwargs):
        raise RuntimeError("synthetic indeterminate create")

    def fail_readback(_binding_id):
        raise RuntimeError("synthetic readback outage")

    monkeypatch.setattr(bindings, "create", fail_create)
    monkeypatch.setattr(bindings, "get", fail_readback)

    with pytest.raises(RuntimeError, match="synthetic indeterminate create"):
        _connect_device(binder)

    # The only encrypted authority for revoking the just-issued remote grant
    # survives until authoritative binding readback is available.
    assert len(store.binding_ids()) == 1
    assert store.get(store.binding_ids()[0]).refresh_token == SENTINEL_REFRESH


def test_failed_first_connect_status_is_not_connected_without_token_record(
    store, bindings, registry
):
    # Models the partial row left by the pre-fix connect ordering. Status must
    # fail closed even when it encounters that durable state after restart.
    binding = bindings.create(
        provider_channel_id=SYNTH_CHANNEL_ID,
        display_label=SYNTH_CHANNEL_TITLE,
        scopes=[oauth.SCOPE],
        account_binding_id="binding-without-token",
    )
    assert store.has_record(binding.account_binding_id) is False

    status = _binder(_Provider(), store, bindings, registry).status(binding.account_binding_id)

    assert status["status"] == "degraded"
    assert status["reason_code"] == "auth_missing"


# --- AC4 --------------------------------------------------------------------


def test_revoked_auth_degrades_without_cursor_mutation(store, bindings, registry):
    provider = _Provider()
    binder = _binder(provider, store, bindings, registry)
    result = _connect_device(binder)
    binding_id = result["account"]["binding_id"]

    # A dependent authenticated source under this binding.
    source = registry.register(
        collection_kind="owned_playlist",
        collection_ref=SYNTH_PLAYLIST_REF,
        title="Owned",
        account_binding_id=binding_id,
    )
    cursor_before = dict(source.cursor)

    # Force a refresh whose refresh_token the provider now rejects.
    store.put(
        binding_id,
        store.get(binding_id).with_expired_access(),
    )
    provider.token_responses.append(_invalid_grant())

    tp = oauth.TokenProvider(
        binding_id=binding_id,
        token_store=store,
        oauth_client=_client(provider),
        binding_store=bindings,
        source_registry=registry,
    )
    with pytest.raises(oauth.AuthDegradedError) as excinfo:
        tp.get_access_token()
    assert excinfo.value.reason_code == "auth_revoked"

    # Binding + dependent source both read auth_revoked.
    assert bindings.get(binding_id).state == "degraded"
    assert bindings.get(binding_id).reason_code == "auth_revoked"
    degraded_source = registry.get(source.binding_id)
    assert degraded_source.last_error is not None
    assert degraded_source.last_error["reason_code"] == "auth_revoked"
    # No cursor was mutated by the auth failure (INV-YSS-4/INV-YSS-1), and the
    # source row stays enabled (degraded, recoverable — not disconnected).
    assert degraded_source.cursor == cursor_before
    assert degraded_source.enabled is True


# --- AC5 --------------------------------------------------------------------


def test_no_secret_in_logs_events_receipts_or_json(store, bindings, registry, caplog):
    caplog.set_level(logging.DEBUG)
    provider = _Provider()
    binder = _binder(provider, store, bindings, registry)

    emitted: list[dict] = []

    connect_result = _connect_device(binder)
    emitted.append(connect_result)
    binding_id = connect_result["account"]["binding_id"]
    emitted.append(binder.status(binding_id))

    # A successful refresh, then a failing (revoked) one.
    store.put(binding_id, store.get(binding_id).with_expired_access())
    provider.token_responses.append(_granted_token(access=SENTINEL_ACCESS_2, refresh=SENTINEL_REFRESH))
    tp = oauth.TokenProvider(
        binding_id=binding_id,
        token_store=store,
        oauth_client=_client(provider),
        binding_store=bindings,
        source_registry=registry,
    )
    tp.get_access_token()  # refreshes to SENTINEL_ACCESS_2

    store.put(binding_id, store.get(binding_id).with_expired_access())
    provider.token_responses.append(_invalid_grant())
    captured_exc = ""
    try:
        tp.get_access_token()
    except oauth.AuthDegradedError as exc:
        captured_exc = repr(exc) + str(exc)
    emitted.append(binder.status(binding_id))

    haystack = "\n".join([json.dumps(e) for e in emitted])
    haystack += "\n" + captured_exc
    haystack += "\n" + caplog.text
    # repr of the stored token must not leak either.
    haystack += "\n" + repr(store.get.__self__)

    for sentinel in _ALL_SENTINELS:
        assert sentinel not in haystack, f"secret leaked: {sentinel[:24]}..."


# --- AC6 --------------------------------------------------------------------


def test_disconnect_revokes_without_deleting_artifacts(store, bindings, registry, monkeypatch, tmp_path):
    provider = _Provider()
    binder = _binder(provider, store, bindings, registry)
    result = _connect_device(binder)
    binding_id = result["account"]["binding_id"]

    source = registry.register(
        collection_kind="owned_playlist",
        collection_ref=SYNTH_PLAYLIST_REF,
        title="Owned",
        account_binding_id=binding_id,
    )

    # A pre-existing acquired raw record must survive disconnect untouched.
    monkeypatch.setenv("HEIMDAL_RAW_STORE_KEY", secrets.token_hex(32))
    from app.heimdal import raw_store

    raw_store.reset_memory_raw_store()
    key = raw_store.resolve_raw_store_key()
    ciphertext, nonce = raw_store.encrypt_raw_bytes(b"acquired-evidence", key=key)
    raw_row, _created = raw_store.insert_raw_record(
        content_identity="cid-artifact-1",
        capture_chain=["youtube"],
        sensor={"id": "yt"},
        consent={"grant_ref": "g1"},
        ciphertext=ciphertext,
        nonce=nonce,
        key_ref="k1",
        source_path="mem://x",
    )

    disc = binder.disconnect(binding_id)
    assert disc["status"] == "disconnected"

    # Provider revoke was actually called.
    assert provider.revoked, "revoke endpoint was not called"
    # Token record deleted; binding marked disconnected.
    assert store.has_record(binding_id) is False
    assert bindings.get(binding_id).reason_code == "auth_disconnected"
    # Dependent source disabled with auth_disconnected — but the row/cursor kept.
    disabled = registry.get(source.binding_id)
    assert disabled.enabled is False
    assert disabled.last_error["reason_code"] == "auth_disconnected"
    assert disabled.collection_ref == SYNTH_PLAYLIST_REF
    # Acquired artifacts are never deleted by a disconnect.
    assert raw_store.get_raw_record_by_content_identity("cid-artifact-1") is not None
    assert raw_store.all_raw_records()[0].id == raw_row.id


def test_disconnect_preserves_token_when_provider_revoke_fails(store, bindings, registry):
    provider = _Provider()
    binder = _binder(provider, store, bindings, registry)
    result = _connect_device(binder)
    binding_id = result["account"]["binding_id"]
    source = registry.register(
        collection_kind="owned_playlist",
        collection_ref=SYNTH_PLAYLIST_REF,
        title="Owned",
        account_binding_id=binding_id,
    )
    provider.revoke_responses.append(
        httpx.Response(503, json={"error": "temporarily_unavailable"})
    )

    disc = binder.disconnect(binding_id)

    assert disc == {
        "status": "disconnect_failed",
        "revoked": False,
        "retryable": True,
        "sources_disabled": 0,
    }
    assert store.has_record(binding_id) is True
    assert store.get(binding_id).refresh_token == SENTINEL_REFRESH
    assert bindings.get(binding_id).state == "connected"
    assert bindings.get(binding_id).reason_code is None
    unchanged_source = registry.get(source.binding_id)
    assert unchanged_source.enabled is True
    assert unchanged_source.last_error is None

    retried = binder.disconnect(binding_id)
    assert retried["status"] == "disconnected"
    assert retried["revoked"] is True
    assert store.has_record(binding_id) is False
    assert registry.get(source.binding_id).enabled is False


@pytest.mark.parametrize(
    "status",
    [0, 100, 199, 300, 302, 399, 400, 401, 403, 404, 407, 408, 409, 429, 499, 500, 599, 600],
)
def test_disconnect_indeterminate_revoke_status_preserves_retry_authority(
    store, bindings, registry, monkeypatch, status
):
    binder = _binder(_Provider(), store, bindings, registry)
    connected = _connect_device(binder)
    binding_id = connected["account"]["binding_id"]
    source = registry.register(
        collection_kind="owned_playlist",
        collection_ref=SYNTH_PLAYLIST_REF,
        title="Owned",
        account_binding_id=binding_id,
    )

    def fail_revoke(_token):
        raise oauth.OAuthProviderError(status=status, error_code="synthetic_revoke_failure")

    monkeypatch.setattr(binder._client, "revoke", fail_revoke)

    disc = binder.disconnect(binding_id)

    assert disc == {
        "status": "disconnect_failed",
        "revoked": False,
        "retryable": True,
        "sources_disabled": 0,
    }
    assert store.get(binding_id).refresh_token == SENTINEL_REFRESH
    assert bindings.get(binding_id).state == "connected"
    assert bindings.get(binding_id).reason_code is None
    assert registry.get(source.binding_id).enabled is True


def test_disconnect_and_reconnect_are_serialized_across_service_instances(
    store, bindings, registry
):
    provider = _Provider()
    disconnect_binder = _binder(provider, store, bindings, registry)
    connected = _connect_device(disconnect_binder)
    binding_id = connected["account"]["binding_id"]

    # A second production-style service instance shares only durable stores,
    # not the first binder/token-store object's in-process lock.
    reconnect_store = tokstore.YouTubeTokenStore(path=store.path)
    reconnect_binder = _binder(provider, reconnect_store, bindings, registry)
    reconnect_connection = reconnect_binder.start_reconnect(binding_id)
    provider.token_responses.append(
        _granted_token(access=SENTINEL_ACCESS_2, refresh=SENTINEL_REFRESH_2)
    )
    provider.revoke_release = threading.Event()

    results: dict[str, dict] = {}
    errors: list[BaseException] = []
    reconnect_done = threading.Event()

    def run_disconnect() -> None:
        try:
            results["disconnect"] = disconnect_binder.disconnect(binding_id)
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    def run_reconnect() -> None:
        try:
            results["reconnect"] = reconnect_binder.finish_device_connection(
                reconnect_connection
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)
        finally:
            reconnect_done.set()

    disconnect_thread = threading.Thread(target=run_disconnect)
    reconnect_thread = threading.Thread(target=run_reconnect)
    disconnect_thread.start()
    assert provider.revoke_started.wait(timeout=2), "disconnect never reached provider revoke"

    # Exact P1 interleaving: disconnect has read the old token and is paused in
    # provider revoke while another binder attempts to persist a new grant.
    reconnect_thread.start()
    reconnect_was_serialized = not reconnect_done.wait(timeout=0.2)
    provider.revoke_release.set()
    disconnect_thread.join(timeout=2)
    reconnect_thread.join(timeout=2)

    assert reconnect_was_serialized, "reconnect wrote while disconnect held lifecycle authority"
    assert not disconnect_thread.is_alive()
    assert not reconnect_thread.is_alive()
    assert errors == []
    assert results["disconnect"]["status"] == "disconnected"
    assert results["reconnect"]["status"] == "connected"
    surviving = store.get(binding_id)
    assert surviving is not None
    assert surviving.refresh_token == SENTINEL_REFRESH_2
    assert bindings.get(binding_id).state == "connected"
    assert disconnect_binder.status(binding_id)["status"] == "connected"
    lock_root = store.path.parent / f".{store.path.name}.locks"
    lock_files = tuple(lock_root.iterdir())
    assert len(lock_files) >= 2
    assert all(binding_id not in path.name for path in lock_files)
    assert all(secret not in str(path) for path in lock_files for secret in _ALL_SENTINELS)
    assert all(path.read_bytes() == b"\0" for path in lock_files)


def test_distinct_binding_writes_serialize_across_store_instances(store, monkeypatch):
    second = tokstore.YouTubeTokenStore(path=store.path)
    first_inside_write = threading.Event()
    release_first = threading.Event()
    original_write = store._write_file

    def paused_write(data):
        first_inside_write.set()
        assert release_first.wait(timeout=2)
        original_write(data)

    monkeypatch.setattr(store, "_write_file", paused_write)
    token = tokstore.StoredToken(
        refresh_token=SENTINEL_REFRESH,
        access_token=SENTINEL_ACCESS,
        expires_at=None,
        scopes=(oauth.SCOPE,),
        obtained_at="2026-01-01T00:00:00+00:00",
        provider_channel_id=SYNTH_CHANNEL_ID,
    )
    first = threading.Thread(target=store.put, args=("binding-a", token))
    second_done = threading.Event()
    other = threading.Thread(
        target=lambda: (second.put("binding-b", token), second_done.set())
    )
    first.start()
    assert first_inside_write.wait(timeout=2)
    other.start()
    assert not second_done.wait(timeout=0.2)
    release_first.set()
    first.join(timeout=2)
    other.join(timeout=2)
    assert set(store.binding_ids()) == {"binding-a", "binding-b"}


def test_concurrent_first_connects_re_resolve_identity_under_shared_authority(
    store, bindings, registry, monkeypatch
):
    first_provider = _Provider()
    second_provider = _Provider()
    first_binder = _binder(first_provider, store, bindings, registry)
    second_store = tokstore.YouTubeTokenStore(path=store.path)
    second_binder = _binder(second_provider, second_store, bindings, registry)
    first_connection = first_binder.start_device_connection()
    second_connection = second_binder.start_device_connection()
    first_inside = threading.Event()
    release_first = threading.Event()
    original_commit = first_binder._commit_binding

    def paused_commit(*args, **kwargs):
        first_inside.set()
        assert release_first.wait(timeout=2)
        return original_commit(*args, **kwargs)

    monkeypatch.setattr(first_binder, "_commit_binding", paused_commit)
    results: list[dict] = []
    first = threading.Thread(
        target=lambda: results.append(first_binder.finish_device_connection(first_connection))
    )
    second_done = threading.Event()

    def connect_second():
        results.append(second_binder.finish_device_connection(second_connection))
        second_done.set()

    second = threading.Thread(target=connect_second)
    first.start()
    assert first_inside.wait(timeout=2)
    second.start()
    assert not second_done.wait(timeout=0.2)
    release_first.set()
    first.join(timeout=2)
    second.join(timeout=2)
    binding_ids = {result["account"]["binding_id"] for result in results}
    assert len(binding_ids) == 1
    binding_id = binding_ids.pop()
    assert store.has_record(binding_id)
    assert bindings.get(binding_id).state == "connected"


def test_distinct_binding_writes_serialize_across_processes(store, tmp_path):
    release = tmp_path / "release"
    script = """
import os, sys, time
from app.knowledge_acquisition.youtube_token_store import StoredToken, YouTubeTokenStore
os.environ['YOUTUBE_TOKEN_STORE_KEY'] = sys.argv[3]
while not os.path.exists(sys.argv[4]): time.sleep(0.01)
YouTubeTokenStore(sys.argv[1]).put(sys.argv[2], StoredToken('refresh', 'access', None, ('scope',), '2026-01-01T00:00:00+00:00', 'channel'))
"""
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", script, str(store.path), binding, TEST_STORE_KEY, str(release)],
            cwd=Path.cwd(),
        )
        for binding in ("process-a", "process-b")
    ]
    release.touch()
    for process in processes:
        assert process.wait(timeout=10) == 0
    assert set(store.binding_ids()) == {"process-a", "process-b"}


def test_portable_lock_uses_windows_backend_when_fcntl_unavailable(store, monkeypatch):
    calls: list[tuple[int, int]] = []

    class FakeMsvcrt:
        LK_LOCK = 1
        LK_UNLCK = 2

        @staticmethod
        def locking(_descriptor, mode, size):
            calls.append((mode, size))

    monkeypatch.setattr(tokstore, "_fcntl", None)
    monkeypatch.setattr(tokstore, "_msvcrt", FakeMsvcrt)
    assert store.has_record("missing") is False
    assert calls == [(FakeMsvcrt.LK_LOCK, 1), (FakeMsvcrt.LK_UNLCK, 1)]


def test_disconnect_documented_invalid_token_tears_down_local_state(
    store, bindings, registry
):
    provider = _Provider()
    binder = _binder(provider, store, bindings, registry)
    connected = _connect_device(binder)
    binding_id = connected["account"]["binding_id"]
    source = registry.register(
        collection_kind="owned_playlist",
        collection_ref=SYNTH_PLAYLIST_REF,
        title="Owned",
        account_binding_id=binding_id,
    )
    provider.revoke_responses.append(
        httpx.Response(
            400,
            json={"error": "invalid_token", "error_description": SENTINEL_REFRESH},
        )
    )

    disc = binder.disconnect(binding_id)

    assert disc["status"] == "disconnected"
    assert disc["revoked"] is False
    assert store.has_record(binding_id) is False
    assert bindings.get(binding_id).reason_code == "auth_disconnected"
    assert registry.get(source.binding_id).enabled is False
    assert SENTINEL_REFRESH not in json.dumps(disc)


@pytest.mark.parametrize(
    ("status", "error_code"),
    [
        (400, "invalid_request"),
        (400, "unsupported_token_type"),
        (400, SENTINEL_REFRESH),
        (407, "invalid_token"),
        (409, "invalid_token"),
        (499, "invalid_token"),
    ],
)
def test_disconnect_unproven_4xx_outcome_preserves_retry_authority(
    store, bindings, registry, status, error_code
):
    provider = _Provider()
    binder = _binder(provider, store, bindings, registry)
    connected = _connect_device(binder)
    binding_id = connected["account"]["binding_id"]
    provider.revoke_responses.append(
        httpx.Response(
            status,
            json={"error": error_code, "error_description": SENTINEL_ACCESS},
        )
    )

    disc = binder.disconnect(binding_id)

    assert disc == {
        "status": "disconnect_failed",
        "revoked": False,
        "retryable": True,
        "sources_disabled": 0,
    }
    assert store.get(binding_id).refresh_token == SENTINEL_REFRESH
    assert bindings.get(binding_id).state == "connected"
    assert SENTINEL_REFRESH not in json.dumps(disc)
    assert SENTINEL_ACCESS not in json.dumps(disc)


# --- AC7 --------------------------------------------------------------------


def test_minimal_scope_requested_at_call_site(store, bindings, registry):
    provider = _Provider()
    binder = _binder(provider, store, bindings, registry)

    # Device flow: the scope on the real outgoing device-code request.
    binder.start_device_connection()
    device_req = next(r for r in provider.requests if urlsplit(str(r.url)).path.endswith("/device/code"))
    device_body = {k: v[0] for k, v in parse_qs(device_req.content.decode()).items()}
    assert device_body["scope"] == oauth.SCOPE
    assert device_body["scope"].split() == [oauth.SCOPE]  # exactly one scope, nothing extra

    # Loopback flow: the scope on the built authorization URL.
    flow = oauth.start_loopback_flow(_client(provider), redirect_uri="http://127.0.0.1:8765/callback")
    params = {k: v[0] for k, v in parse_qs(urlsplit(flow.authorization_url).query).items()}
    assert params["scope"] == oauth.SCOPE
    assert params["scope"].split() == [oauth.SCOPE]


# --- Supporting unit tests --------------------------------------------------


def test_token_store_roundtrip_and_delete(store):
    token = tokstore.StoredToken(
        refresh_token=SENTINEL_REFRESH,
        access_token=SENTINEL_ACCESS,
        expires_at="2999-01-01T00:00:00+00:00",
        scopes=(oauth.SCOPE,),
        obtained_at="2026-07-18T00:00:00+00:00",
        provider_channel_id=SYNTH_CHANNEL_ID,
    )
    store.put("b-1", token)
    assert store.has_record("b-1") is True
    assert store.get("b-1").refresh_token == SENTINEL_REFRESH
    assert store.delete("b-1") is True
    assert store.has_record("b-1") is False
    assert store.get("b-1") is None


def test_token_store_syncs_staged_file_before_replace_and_parent_after(
    store, monkeypatch
):
    token = tokstore.StoredToken(
        refresh_token=SENTINEL_REFRESH,
        access_token=SENTINEL_ACCESS,
        expires_at="2999-01-01T00:00:00+00:00",
        scopes=(oauth.SCOPE,),
        obtained_at="2026-07-18T00:00:00+00:00",
        provider_channel_id=SYNTH_CHANNEL_ID,
    )
    events: list[str] = []
    original_replace = tokstore.os.replace

    def record_fsync(descriptor):
        mode = tokstore.os.fstat(descriptor).st_mode
        events.append("fsync:directory" if stat.S_ISDIR(mode) else "fsync:file")

    def record_replace(source, target):
        events.append("replace")
        original_replace(source, target)

    monkeypatch.setattr(tokstore.os, "fsync", record_fsync)
    monkeypatch.setattr(tokstore.os, "replace", record_replace)

    store.put("b-durable", token)

    assert events == ["fsync:file", "replace", "fsync:directory"]
    assert store.get("b-durable") == token


def test_oauth_client_refuses_off_allowlist_host():
    http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})))
    client = oauth.OAuthClient(client_id=TEST_CLIENT_ID, client_secret=SENTINEL_CLIENT_SECRET, http=http)
    with pytest.raises(oauth.DisallowedOAuthHostError):
        client._post("https://evil.example.com/token", {"grant_type": "refresh_token"})


@pytest.mark.parametrize("status", [302, 307])
def test_disconnect_redirect_never_replays_token_and_preserves_retry_authority(
    store, bindings, registry, status
):
    provider = _Provider()
    # The injected client is deliberately redirect-enabled. The OAuth call
    # site must override that ambient policy for every credential-bearing POST.
    binder = _binder(
        provider,
        store,
        bindings,
        registry,
        follow_redirects=True,
    )
    connected = _connect_device(binder)
    binding_id = connected["account"]["binding_id"]
    request_count_before_revoke = len(provider.requests)
    provider.revoke_responses.append(
        httpx.Response(
            status,
            headers={"Location": "https://off-allowlist.example/collect"},
        )
    )

    disc = binder.disconnect(binding_id)

    revoke_requests = provider.requests[request_count_before_revoke:]
    assert len(revoke_requests) == 1
    assert urlsplit(str(revoke_requests[0].url)).hostname == "oauth2.googleapis.com"
    assert disc["status"] == "disconnect_failed"
    assert disc["retryable"] is True
    assert store.get(binding_id).refresh_token == SENTINEL_REFRESH


def test_provider_error_enum_is_allowlisted_before_exception_rendering():
    provider = _Provider()
    provider.token_responses.append(
        httpx.Response(
            400,
            json={"error": SENTINEL_REFRESH, "error_description": SENTINEL_ACCESS},
        )
    )

    with pytest.raises(oauth.OAuthProviderError) as excinfo:
        _client(provider).refresh(SENTINEL_REFRESH_2)

    assert excinfo.value.error_code is None
    rendered = repr(excinfo.value) + str(excinfo.value)
    assert SENTINEL_REFRESH not in rendered
    assert SENTINEL_ACCESS not in rendered
    assert SENTINEL_REFRESH_2 not in rendered


def test_missing_client_credentials_fail_loud(monkeypatch):
    monkeypatch.delenv(oauth.CLIENT_ID_ENV, raising=False)
    monkeypatch.delenv(oauth.CLIENT_SECRET_ENV, raising=False)
    with pytest.raises(oauth.OAuthClientCredentialsMissingError):
        oauth.resolve_oauth_client_credentials()
