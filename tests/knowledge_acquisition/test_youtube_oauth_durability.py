"""Issue #4830: channel-bound, crash-convergent YouTube OAuth writer."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import threading

import pytest

from app.knowledge_acquisition import source_registry as sr
from app.knowledge_acquisition import youtube_account_binding as yab
from app.knowledge_acquisition import youtube_oauth as oauth
from app.knowledge_acquisition import youtube_token_store as tokstore


STORE_KEY = "8b" * 32
CHANNEL_A = "UC__test__oauth_durability_a"
CHANNEL_B = "UC__test__oauth_durability_b"


class _OAuthClient:
    """Provider seam whose counters prove admission happens before egress."""

    def __init__(self, *, channel_id: str = CHANNEL_A) -> None:
        self.channel_id = channel_id
        self.starts = 0
        self.polls = 0

    def start_device_flow(self) -> oauth.DeviceFlowHandle:
        self.starts += 1
        return oauth.DeviceFlowHandle(
            device_code="synthetic-device-code",
            user_code="TEST-CODE",
            verification_url="https://example.invalid/device",
            verification_url_complete="https://example.invalid/device?synthetic",
            interval=1,
            expires_in=60,
        )

    def poll_device_flow(self, _device_code: str) -> oauth.TokenBundle:
        self.polls += 1
        return oauth.TokenBundle(
            access_token=f"synthetic-access-{self.channel_id}",
            refresh_token=f"synthetic-refresh-{self.channel_id}",
            expires_in=3600,
            scope=oauth.SCOPE,
            token_type="Bearer",
        )


@pytest.fixture(autouse=True)
def _isolated_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv(tokstore.KEY_ENV_VAR, STORE_KEY)
    monkeypatch.setenv("PKM_ENVIRONMENT", "dev")
    monkeypatch.delenv(tokstore.PATH_ENV_VAR, raising=False)
    yab.reset_memory_account_bindings()
    sr.reset_memory_source_registry()
    yield
    yab.reset_memory_account_bindings()
    sr.reset_memory_source_registry()


def _binder(
    client: _OAuthClient,
    store: tokstore.YouTubeTokenStore,
    bindings: yab.AccountBindingStore,
) -> oauth.YouTubeAccountBinder:
    return oauth.YouTubeAccountBinder(
        oauth_client=client,  # type: ignore[arg-type]
        token_store=store,
        binding_store=bindings,
        identity_probe=lambda _token: oauth.ChannelIdentity(
            channel_id=client.channel_id,
            channel_title=f"Channel {client.channel_id[-1]}",
        ),
    )


def _token(channel_id: str = CHANNEL_A) -> tokstore.StoredToken:
    return tokstore.StoredToken(
        refresh_token=f"synthetic-refresh-{channel_id}",
        access_token=f"synthetic-access-{channel_id}",
        expires_at="2999-01-01T00:00:00+00:00",
        scopes=(oauth.SCOPE,),
        obtained_at="2026-08-12T00:00:00+00:00",
        provider_channel_id=channel_id,
    )


def test_default_oauth_state_is_channel_bound_and_hardened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # With no explicit runtime path, a linked worktree resolves through its
    # normalized Git common directory to the same checkout-independent root.
    primary_checkout = tmp_path / "primary-checkout"
    common_git = primary_checkout / ".git"
    common_git.mkdir(parents=True)
    linked_checkout = tmp_path / "linked-checkout"
    linked_checkout.mkdir()
    linked_git = common_git / "worktrees" / "linked-checkout"
    linked_git.mkdir(parents=True)
    (linked_git / "commondir").write_text("../..\n", encoding="utf-8")
    (linked_checkout / ".git").write_text(
        f"gitdir: {linked_git}\n", encoding="utf-8"
    )
    monkeypatch.delenv("INDEX_OUTBOX_PATH", raising=False)
    monkeypatch.setattr(tokstore, "_REPO_ROOT", primary_checkout)
    primary_path = tokstore.default_token_store_path()
    monkeypatch.setattr(tokstore, "_REPO_ROOT", linked_checkout)
    linked_path = tokstore.default_token_store_path()
    assert primary_path == linked_path
    assert primary_path == (
        primary_checkout
        / "tmp-dev"
        / "knowledge_acquisition"
        / "youtube_token_store.enc"
    )

    # Docker/Compose deliberately provides /app/tmp as a sticky 1777 scratch
    # volume for host-UID-remapped processes. The private current-UID child is
    # the credential boundary under that shipped producer.
    runtime_root = tmp_path / "channel-runtime"
    runtime_root.mkdir(mode=0o700)
    runtime_root.chmod(0o1777)
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(runtime_root / "index-outbox.jsonl"))

    cwd_a = tmp_path / "checkout-a"
    cwd_b = tmp_path / "checkout-b"
    cwd_a.mkdir()
    cwd_b.mkdir()
    monkeypatch.chdir(cwd_a)
    first = tokstore.default_token_store_path()
    monkeypatch.chdir(cwd_b)
    second = tokstore.default_token_store_path()

    assert first == second
    assert first.is_absolute()
    assert first.is_relative_to(runtime_root)
    store = tokstore.YouTubeTokenStore()
    store.put("binding-a", _token())
    assert store.path.parent.stat().st_mode & 0o777 == 0o700
    assert store.path.parent.stat().st_uid == os.geteuid()
    assert store.path.stat().st_mode & 0o777 == 0o600
    assert store.path.stat().st_uid == os.geteuid()

    # A symlinked writer parent is rejected before either the credential or
    # admission file can escape the channel root.
    hostile_root = tmp_path / "hostile-runtime"
    hostile_root.mkdir(mode=0o700)
    outside = tmp_path / "outside"
    outside.mkdir(mode=0o700)
    (hostile_root / "knowledge_acquisition").symlink_to(outside, target_is_directory=True)
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(hostile_root / "index-outbox.jsonl"))
    with pytest.raises(tokstore.OAuthStateBoundaryError):
        tokstore.YouTubeTokenStore().put("binding-b", _token())
    assert list(outside.iterdir()) == []

    # Existing state parents are never silently accepted or chmod-repaired
    # when another principal can access them.
    unsafe_root = tmp_path / "unsafe-runtime"
    unsafe_root.mkdir(mode=0o700)
    unsafe_parent = unsafe_root / "knowledge_acquisition"
    unsafe_parent.mkdir(mode=0o755)
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(unsafe_root / "index-outbox.jsonl"))
    with pytest.raises(tokstore.OAuthStateBoundaryError):
        tokstore.YouTubeTokenStore().put("binding-c", _token())
    assert list(unsafe_parent.iterdir()) == []

    # The outer runtime authority must itself be a non-symlink safe directory;
    # neither failure may create the private state parent or its lock file.
    unsafe_runtime = tmp_path / "group-writable-runtime"
    unsafe_runtime.mkdir(mode=0o770)
    unsafe_runtime.chmod(0o770)
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(unsafe_runtime / "index-outbox.jsonl"))
    with pytest.raises(tokstore.OAuthStateBoundaryError):
        tokstore.YouTubeTokenStore().acquire_writer_admission()
    assert list(unsafe_runtime.iterdir()) == []

    real_runtime = tmp_path / "real-runtime"
    real_runtime.mkdir(mode=0o700)
    linked_runtime = tmp_path / "linked-runtime"
    linked_runtime.symlink_to(real_runtime, target_is_directory=True)
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(linked_runtime / "index-outbox.jsonl"))
    with pytest.raises(tokstore.OAuthStateBoundaryError):
        tokstore.YouTubeTokenStore().acquire_writer_admission()
    assert list(real_runtime.iterdir()) == []

    monkeypatch.setenv(tokstore.PATH_ENV_VAR, str(runtime_root / ".." / "escaped.enc"))
    with pytest.raises(tokstore.OAuthStateBoundaryError):
        tokstore.default_token_store_path()
    assert not (tmp_path / "escaped.enc").exists()


def test_concurrent_connect_converges_to_one_binding_and_credential(tmp_path: Path) -> None:
    store_path = tmp_path / "oauth-state" / "tokens.enc"
    store_path.parent.mkdir(mode=0o700)
    bindings = yab.AccountBindingStore.for_runtime()
    first_client = _OAuthClient()
    second_client = _OAuthClient()
    first = _binder(first_client, tokstore.YouTubeTokenStore(store_path), bindings)
    second = _binder(second_client, tokstore.YouTubeTokenStore(store_path), bindings)

    connection = first.start_device_connection()
    with pytest.raises(tokstore.OAuthWriterAdmissionError):
        second.start_device_connection()
    assert second_client.starts == 0
    assert second_client.polls == 0

    cross_process = subprocess.run(
        [
            sys.executable,
            "-c",
            "import os, sys\n"
            "from app.knowledge_acquisition.youtube_account_binding import AccountBindingStore\n"
            "from app.knowledge_acquisition.youtube_oauth import YouTubeAccountBinder\n"
            "from app.knowledge_acquisition.youtube_token_store import (\n"
            "    OAuthWriterAdmissionError, YouTubeTokenStore\n"
            ")\n"
            "os.environ['STORE_BACKEND'] = 'memory'\n"
            "class Provider:\n"
            "    def start_device_flow(self):\n"
            "        raise RuntimeError('provider egress reached')\n"
            "binder = YouTubeAccountBinder(\n"
            "    oauth_client=Provider(), token_store=YouTubeTokenStore(sys.argv[1]),\n"
            "    binding_store=AccountBindingStore.for_runtime(),\n"
            "    identity_probe=lambda _token: None,\n"
            ")\n"
            "try:\n"
            "    binder.start_device_connection()\n"
            "except OAuthWriterAdmissionError:\n"
            "    raise SystemExit(0)\n"
            "raise SystemExit(1)\n",
            str(store_path),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert cross_process.returncode == 0

    receipt = first.finish_device_connection(connection)
    rows = bindings.list_all()
    encrypted = tokstore.YouTubeTokenStore(store_path)
    assert receipt["status"] == "connected"
    assert len(rows) == 1
    assert encrypted.binding_ids() == (rows[0].account_binding_id,)
    assert first_client.starts == 1


def test_token_first_failure_and_recovery_reconcile_orphan_credential(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store_path = tmp_path / "oauth-state" / "tokens.enc"
    store_path.parent.mkdir(mode=0o700)
    store = tokstore.YouTubeTokenStore(store_path)
    bindings = yab.AccountBindingStore.for_runtime()
    binder = _binder(_OAuthClient(), store, bindings)
    original_create = bindings.create

    def fail_binding(**_kwargs: object) -> yab.AccountBinding:
        raise OSError("synthetic binding persistence failure")

    monkeypatch.setattr(bindings, "create", fail_binding)
    connection = binder.start_device_connection()
    with pytest.raises(OSError, match="synthetic binding persistence failure"):
        binder.finish_device_connection(connection)
    assert bindings.list_all() == ()
    failed_binding_id = store.binding_ids()[0]
    assert binder.status(failed_binding_id)["status"] == "absent"
    with pytest.raises(oauth.AuthDegradedError):
        oauth.TokenProvider(
            binding_id=failed_binding_id,
            token_store=store,
            oauth_client=_OAuthClient(),  # type: ignore[arg-type]
            binding_store=bindings,
        ).get_access_token()

    # Model a process death after token-first persistence: no cleanup handler
    # ran, so the next admitted start must reconcile the unbound ciphertext
    # before provider egress. Low-level storage may retain bytes, but runtime
    # authority surfaces must not accept them.
    orphan_id = "orphan-from-crash-window"
    store.put(orphan_id, _token())
    assert binder.status(orphan_id)["status"] == "absent"
    provider = oauth.TokenProvider(
        binding_id=orphan_id,
        token_store=store,
        oauth_client=_OAuthClient(),  # type: ignore[arg-type]
        binding_store=bindings,
    )
    with pytest.raises(oauth.AuthDegradedError):
        provider.get_access_token()
    with pytest.raises(KeyError):
        binder.start_reconnect(orphan_id)

    monkeypatch.setattr(bindings, "create", original_create)
    retry_client = _OAuthClient()
    retry = _binder(retry_client, store, bindings)
    retry_connection = retry.start_device_connection()
    assert failed_binding_id not in store.binding_ids()
    assert orphan_id not in store.binding_ids()
    receipt = retry.finish_device_connection(retry_connection)
    bound_id = receipt["account"]["binding_id"]
    assert store.binding_ids() == (bound_id,)
    assert bindings.get(bound_id) is not None

    # Reconciliation must never delete a credential that already has a valid
    # durable binding row.
    next_client = _OAuthClient()
    next_binder = _binder(next_client, store, bindings)
    with pytest.raises(yab.AccountBindingAdmissionError):
        next_binder.start_device_connection()
    assert store.has_record(bound_id) is True


def test_reconnect_preserves_identity_under_concurrent_admission(tmp_path: Path) -> None:
    store_path = tmp_path / "oauth-state" / "tokens.enc"
    store_path.parent.mkdir(mode=0o700)
    store = tokstore.YouTubeTokenStore(store_path)
    bindings = yab.AccountBindingStore.for_runtime()
    initial = _binder(_OAuthClient(channel_id=CHANNEL_A), store, bindings)
    connected = initial.finish_device_connection(initial.start_device_connection())
    binding_id = connected["account"]["binding_id"]

    reconnect_client = _OAuthClient(channel_id=CHANNEL_A)
    reconnect = _binder(reconnect_client, tokstore.YouTubeTokenStore(store_path), bindings)
    competing_client = _OAuthClient(channel_id=CHANNEL_B)
    competing = _binder(competing_client, tokstore.YouTubeTokenStore(store_path), bindings)

    reconnect_connection = reconnect.start_reconnect(binding_id)
    outcome: list[BaseException] = []

    def compete() -> None:
        try:
            competing.start_device_connection()
        except BaseException as exc:  # noqa: BLE001 - assertion captures the loser outcome
            outcome.append(exc)

    thread = threading.Thread(target=compete)
    thread.start()
    thread.join(timeout=3)
    assert thread.is_alive() is False
    assert outcome
    assert competing_client.starts == 0

    receipt = reconnect.finish_device_connection(reconnect_connection)
    rows = bindings.list_all()
    assert receipt["account"]["binding_id"] == binding_id
    assert len(rows) == 1
    assert rows[0].provider_channel_id == CHANNEL_A
    assert store.binding_ids() == (binding_id,)
    assert store.get(binding_id).provider_channel_id == CHANNEL_A
