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
        self.refreshes = 0

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

    def refresh(self, _refresh_token: str) -> oauth.TokenBundle:
        self.refreshes += 1
        return oauth.TokenBundle(
            access_token=f"synthetic-refreshed-access-{self.channel_id}",
            refresh_token=f"synthetic-refreshed-refresh-{self.channel_id}",
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


def _bind_repository_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, name: str = "primary-checkout"
) -> Path:
    repository_root = tmp_path / name
    (repository_root / ".git").mkdir(parents=True)
    (repository_root / "tmp-dev").mkdir(mode=0o700)
    monkeypatch.setattr(tokstore, "_REPO_ROOT", repository_root)
    monkeypatch.chdir(repository_root)
    monkeypatch.delenv("INDEX_OUTBOX_PATH", raising=False)
    return repository_root


def _legacy_store_path(repository_root: Path) -> Path:
    return (
        repository_root
        / "runtime"
        / "knowledge_acquisition"
        / "youtube_token_store.enc"
    )


def _write_store(path: Path, binding_id: str, token: tokstore.StoredToken) -> bytes:
    path.parent.mkdir(parents=True, mode=0o700)
    path.parent.chmod(0o700)
    tokstore.YouTubeTokenStore(path).put(binding_id, token)
    return path.read_bytes()


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


def test_legacy_default_token_store_migrates_before_new_path_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository_root = _bind_repository_root(tmp_path, monkeypatch)
    binding_id = "legacy-binding"
    legacy_checkout = tmp_path / "legacy-linked-checkout"
    legacy_checkout.mkdir()
    legacy_worktree_metadata = repository_root / ".git" / "worktrees" / "legacy-linked"
    legacy_worktree_metadata.mkdir(parents=True)
    (legacy_worktree_metadata / "gitdir").write_text(
        f"{legacy_checkout / '.git'}\n", encoding="utf-8"
    )
    legacy_path = _legacy_store_path(legacy_checkout)
    legacy_payload = _write_store(
        legacy_path, binding_id, _token().with_expired_access()
    )
    legacy_path.chmod(0o644)  # the old Path.write_text producer honored the host umask
    restart_working_root = tmp_path / "upgraded-process-cwd"
    restart_working_root.mkdir()
    monkeypatch.chdir(restart_working_root)
    explicit_path = (
        repository_root
        / "tmp-dev"
        / "knowledge_acquisition"
        / "explicit-token-store.enc"
    )
    monkeypatch.setenv(tokstore.PATH_ENV_VAR, str(explicit_path))
    overridden = tokstore.YouTubeTokenStore()
    assert overridden.path == explicit_path
    assert legacy_path.read_bytes() == legacy_payload
    assert explicit_path.exists() is False
    monkeypatch.delenv(tokstore.PATH_ENV_VAR)

    bindings = yab.AccountBindingStore.for_runtime()
    bindings.create(
        provider_channel_id=CHANNEL_A,
        display_label="Legacy channel",
        scopes=[oauth.SCOPE],
        account_binding_id=binding_id,
    )

    migrated = tokstore.YouTubeTokenStore()
    assert migrated.path.read_bytes() == legacy_payload
    binder = _binder(_OAuthClient(), migrated, bindings)
    assert binder.status(binding_id) == {
        "status": "connected",
        "reason_code": None,
        "scopes": [oauth.SCOPE],
        "token_store": "encrypted",
    }

    client = _OAuthClient()
    access_token = oauth.TokenProvider(
        binding_id=binding_id,
        token_store=migrated,
        oauth_client=client,  # type: ignore[arg-type]
        binding_store=bindings,
    ).get_access_token()
    assert access_token == f"synthetic-refreshed-access-{CHANNEL_A}"
    assert client.refreshes == 1
    assert migrated.get(binding_id).refresh_token == (
        f"synthetic-refreshed-refresh-{CHANNEL_A}"
    )
    assert legacy_path.exists() is False
    assert migrated.path == (
        repository_root
        / "tmp-dev"
        / "knowledge_acquisition"
        / "youtube_token_store.enc"
    )
    assert migrated.path.parent.stat().st_mode & 0o777 == 0o700
    assert migrated.path.stat().st_mode & 0o777 == 0o600
    assert legacy_payload != migrated.path.read_bytes()
    assert b"synthetic-refresh" not in migrated.path.read_bytes()


def test_token_store_migration_is_crash_convergent_and_channel_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository_root = _bind_repository_root(tmp_path, monkeypatch)
    binding_id = "crash-window-binding"
    legacy_path = _legacy_store_path(repository_root)
    legacy_payload = _write_store(legacy_path, binding_id, _token())
    target_path = tokstore.default_token_store_path()

    # The historical producer was dev-only.  A test/prod process that starts
    # first must neither capture nor delete its unscoped legacy credential.
    for environment, runtime_name in (("test", "tmp-test"), ("prod", "tmp")):
        monkeypatch.setenv("PKM_ENVIRONMENT", environment)
        (repository_root / runtime_name).mkdir(mode=0o700)
        isolated = tokstore.YouTubeTokenStore()
        assert isolated.binding_ids() == ()
        assert legacy_path.read_bytes() == legacy_payload
    monkeypatch.setenv("PKM_ENVIRONMENT", "dev")

    # Refuse before legacy deletion when the target directory's link cannot be
    # durably committed in the channel runtime root.
    real_fsync = os.fsync
    runtime_metadata = (repository_root / "tmp-dev").stat()

    def fail_runtime_directory_fsync(descriptor: int) -> None:
        metadata = os.fstat(descriptor)
        if (metadata.st_dev, metadata.st_ino) == (
            runtime_metadata.st_dev,
            runtime_metadata.st_ino,
        ):
            raise OSError("synthetic runtime-directory fsync failure")
        real_fsync(descriptor)

    monkeypatch.setattr(tokstore.os, "fsync", fail_runtime_directory_fsync)
    with pytest.raises(tokstore.OAuthStateBoundaryError):
        tokstore.YouTubeTokenStore()
    assert legacy_path.read_bytes() == legacy_payload
    assert target_path.exists() is False
    monkeypatch.setattr(tokstore.os, "fsync", real_fsync)

    real_link = os.link

    def fail_publication(*_args: object, **_kwargs: object) -> None:
        raise OSError("synthetic target publication failure")

    monkeypatch.setattr(tokstore.os, "link", fail_publication)
    with pytest.raises(
        tokstore.OAuthStateMigrationError,
        match="target publication failed",
    ):
        tokstore.YouTubeTokenStore()
    assert legacy_path.read_bytes() == legacy_payload
    assert target_path.exists() is False

    monkeypatch.setattr(tokstore.os, "link", real_link)
    real_unlink = os.unlink

    def fail_legacy_finalize(
        path: str,
        *,
        dir_fd: int | None = None,
    ) -> None:
        if path == legacy_path.name:
            raise OSError("synthetic legacy finalization failure")
        real_unlink(path, dir_fd=dir_fd)

    monkeypatch.setattr(tokstore.os, "unlink", fail_legacy_finalize)
    with pytest.raises(
        tokstore.OAuthStateMigrationError,
        match="legacy finalization failed",
    ):
        tokstore.YouTubeTokenStore()
    assert legacy_path.read_bytes() == legacy_payload
    assert target_path.read_bytes() == legacy_payload

    target_directory_metadata = target_path.parent.stat()

    def fail_target_directory_fsync(descriptor: int) -> None:
        metadata = os.fstat(descriptor)
        if (metadata.st_dev, metadata.st_ino) == (
            target_directory_metadata.st_dev,
            target_directory_metadata.st_ino,
        ):
            raise OSError("synthetic target-directory fsync failure")
        real_fsync(descriptor)

    monkeypatch.setattr(tokstore.os, "fsync", fail_target_directory_fsync)
    with pytest.raises(
        tokstore.OAuthStateMigrationError,
        match="durability verification failed",
    ):
        tokstore.YouTubeTokenStore()
    assert legacy_path.read_bytes() == legacy_payload
    assert target_path.read_bytes() == legacy_payload

    monkeypatch.setattr(tokstore.os, "fsync", real_fsync)
    monkeypatch.setattr(tokstore.os, "unlink", real_unlink)
    migrated = tokstore.YouTubeTokenStore()
    assert migrated.get(binding_id) == _token()
    assert legacy_path.exists() is False
    assert target_path.stat().st_mode & 0o777 == 0o600
    assert b"synthetic-refresh" not in target_path.read_bytes()

    monkeypatch.setenv("PKM_ENVIRONMENT", "test")
    isolated_test_store = tokstore.YouTubeTokenStore()
    assert isolated_test_store.path == (
        repository_root
        / "tmp-test"
        / "knowledge_acquisition"
        / "youtube_token_store.enc"
    )
    assert isolated_test_store.binding_ids() == ()
    assert migrated.get(binding_id) == _token()


def test_token_store_migration_preflight_fails_loud_on_ambiguity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository_root = _bind_repository_root(tmp_path, monkeypatch)
    legacy_path = _legacy_store_path(repository_root)
    legacy_payload = _write_store(legacy_path, "legacy-binding", _token(CHANNEL_A))
    target_path = tokstore.default_token_store_path()
    target_payload = _write_store(target_path, "new-binding", _token(CHANNEL_B))

    with pytest.raises(tokstore.OAuthStateMigrationError, match="ambiguous"):
        tokstore.YouTubeTokenStore()

    assert legacy_path.read_bytes() == legacy_payload
    assert target_path.read_bytes() == target_payload
    assert legacy_path.exists() is True
    assert target_path.exists() is True

    multiple_root = _bind_repository_root(
        tmp_path, monkeypatch, name="multiple-legacy-checkout"
    )
    canonical_legacy_path = _legacy_store_path(multiple_root)
    canonical_legacy_payload = _write_store(
        canonical_legacy_path, "canonical-legacy-binding", _token(CHANNEL_A)
    )
    alternate_launch_root = tmp_path / "alternate-legacy-cwd"
    alternate_launch_root.mkdir()
    alternate_legacy_path = _legacy_store_path(alternate_launch_root)
    alternate_legacy_payload = _write_store(
        alternate_legacy_path, "alternate-legacy-binding", _token(CHANNEL_B)
    )
    monkeypatch.chdir(alternate_launch_root)
    with pytest.raises(tokstore.OAuthStateMigrationError, match="multiple legacy"):
        tokstore.YouTubeTokenStore()
    assert canonical_legacy_path.read_bytes() == canonical_legacy_payload
    assert alternate_legacy_path.read_bytes() == alternate_legacy_payload

    stage_root = _bind_repository_root(
        tmp_path, monkeypatch, name="divergent-stage-checkout"
    )
    stage_legacy_path = _legacy_store_path(stage_root)
    stage_legacy_payload = _write_store(
        stage_legacy_path, "stage-legacy-binding", _token(CHANNEL_A)
    )
    stage_path = (
        stage_root
        / "tmp-dev"
        / "knowledge_acquisition"
        / tokstore._MIGRATION_STAGE_FILENAME
    )
    stage_payload = _write_store(
        stage_path, "stage-newer-binding", _token(CHANNEL_B)
    )
    with pytest.raises(tokstore.OAuthStateMigrationError, match="ambiguous"):
        tokstore.YouTubeTokenStore()
    assert stage_legacy_path.read_bytes() == stage_legacy_payload
    assert stage_path.read_bytes() == stage_payload
    assert tokstore.default_token_store_path().exists() is False

    alias_root = _bind_repository_root(
        tmp_path, monkeypatch, name="legacy-alias-checkout"
    )
    alias_legacy_path = _legacy_store_path(alias_root)
    alias_legacy_payload = _write_store(
        alias_legacy_path, "alias-binding", _token(CHANNEL_A)
    )
    alias_legacy_path.chmod(0o644)
    monkeypatch.setenv(
        "INDEX_OUTBOX_PATH", str(alias_root / "runtime" / "index-outbox.jsonl")
    )
    for environment in ("test", "prod", "dev"):
        monkeypatch.setenv("PKM_ENVIRONMENT", environment)
        with pytest.raises(tokstore.OAuthStateBoundaryError, match="aliases"):
            tokstore.YouTubeTokenStore()
        assert alias_legacy_path.read_bytes() == alias_legacy_payload

    normalized_alias_root = _bind_repository_root(
        tmp_path, monkeypatch, name="normalized-alias-checkout"
    )
    normalized_legacy_path = _legacy_store_path(normalized_alias_root)
    normalized_legacy_payload = _write_store(
        normalized_legacy_path, "normalized-alias-binding", _token(CHANNEL_A)
    )
    monkeypatch.setenv(
        "INDEX_OUTBOX_PATH",
        str(normalized_alias_root / "RUNTIME" / "index-outbox.jsonl"),
    )
    with pytest.raises(tokstore.OAuthStateBoundaryError, match="aliases"):
        tokstore.YouTubeTokenStore()
    assert normalized_legacy_path.read_bytes() == normalized_legacy_payload

    realpath_alias_root = _bind_repository_root(
        tmp_path, monkeypatch, name="realpath-alias-checkout"
    )
    realpath_legacy_path = _legacy_store_path(realpath_alias_root)
    realpath_legacy_payload = _write_store(
        realpath_legacy_path, "realpath-alias-binding", _token(CHANNEL_A)
    )
    runtime_link = realpath_alias_root / "runtime-link"
    runtime_link.symlink_to(realpath_alias_root / "runtime", target_is_directory=True)
    monkeypatch.setenv(
        "INDEX_OUTBOX_PATH", str(runtime_link / "index-outbox.jsonl")
    )
    with pytest.raises(tokstore.OAuthStateBoundaryError, match="aliases"):
        tokstore.YouTubeTokenStore()
    assert realpath_legacy_path.read_bytes() == realpath_legacy_payload

    physical_alias_root = _bind_repository_root(
        tmp_path, monkeypatch, name="physical-alias-checkout"
    )
    physical_legacy_path = _legacy_store_path(physical_alias_root)
    physical_legacy_payload = _write_store(
        physical_legacy_path, "physical-alias-binding", _token(CHANNEL_A)
    )
    physical_legacy_path.chmod(0o600)
    physical_target_path = (
        physical_alias_root
        / "runtime-bind"
        / "knowledge_acquisition"
        / "youtube_token_store.enc"
    )
    real_samefile = os.path.samefile

    def same_physical_parent(first: object, second: object) -> bool:
        pair = {Path(first), Path(second)}
        if pair == {physical_legacy_path.parent, physical_target_path.parent}:
            return True
        return real_samefile(first, second)

    monkeypatch.setattr(tokstore.os.path, "samefile", same_physical_parent)
    monkeypatch.setenv(
        "INDEX_OUTBOX_PATH",
        str(physical_alias_root / "runtime-bind" / "index-outbox.jsonl"),
    )
    with pytest.raises(tokstore.OAuthStateBoundaryError, match="aliases"):
        tokstore.YouTubeTokenStore()
    assert physical_legacy_path.read_bytes() == physical_legacy_payload
    monkeypatch.setattr(tokstore.os.path, "samefile", real_samefile)

    for state_kind in ("legacy", "stage", "target", "target-only"):
        fifo_root = _bind_repository_root(
            tmp_path, monkeypatch, name=f"fifo-{state_kind}-checkout"
        )
        fifo_legacy_path = _legacy_store_path(fifo_root)
        fifo_target_path = tokstore.default_token_store_path()
        if state_kind == "legacy":
            fifo_path = fifo_legacy_path
        else:
            if state_kind != "target-only":
                _write_store(
                    fifo_legacy_path,
                    f"fifo-{state_kind}-binding",
                    _token(CHANNEL_A),
                )
            fifo_path = (
                fifo_target_path.with_name(tokstore._MIGRATION_STAGE_FILENAME)
                if state_kind == "stage"
                else fifo_target_path
            )
        fifo_path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        fifo_path.parent.chmod(0o700)
        os.mkfifo(fifo_path, mode=0o600)
        with pytest.raises(tokstore.OAuthStateBoundaryError):
            tokstore.YouTubeTokenStore()
        assert fifo_path.exists() is True
        if state_kind in {"stage", "target"}:
            assert fifo_legacy_path.exists() is True

    direct_fifo_root = tmp_path / "direct-consumer-fifo"
    direct_fifo_root.mkdir(mode=0o700)
    direct_fifo_path = direct_fifo_root / "tokens.enc"
    direct_store = tokstore.YouTubeTokenStore(direct_fifo_path)
    os.mkfifo(direct_fifo_path, mode=0o600)
    with pytest.raises(tokstore.OAuthStateBoundaryError):
        direct_store.binding_ids()

    unsafe_root = _bind_repository_root(
        tmp_path, monkeypatch, name="unsafe-primary-checkout"
    )
    unsafe_legacy_path = _legacy_store_path(unsafe_root)
    _write_store(unsafe_legacy_path, "unsafe-binding", _token())
    unsafe_legacy_path.chmod(0o622)
    with pytest.raises(
        tokstore.OAuthStateMigrationError,
        match="not a safe current-user-owned regular file",
    ):
        tokstore.YouTubeTokenStore()
    assert unsafe_legacy_path.exists() is True


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
