from __future__ import annotations

from dataclasses import asdict
import json
import os
from io import StringIO
from pathlib import Path
import stat
import subprocess
import sys
import threading
from uuid import uuid4

import pytest

import app.ops.bws_token_push as bws_token_push
import app.ops.postgres_deploy_linux as postgres_deploy_linux
from app.ops.bws_token_push import (
    SshTokenPushRemote,
    TokenPushAdmin,
    TokenPushError,
    TokenPushReceipt,
    TokenPushStore,
    VmChannelMutationLock,
    load_token_push_targets,
    vm_token_push_inspect,
    vm_token_push_start,
    vm_token_push_worker,
    vm_token_push_status,
)
from app.ops.host_secret_controller import HostSecretController
from app.ops.secret_admin import main as secret_admin_main


_CANARY = "reader-token-canary-never-print"


class _StaticTokenSource:
    def __init__(self, token: str = _CANARY) -> None:
        self.token = token

    def read(self, _target) -> str:
        return self.token


class _MemoryRemote:
    def __init__(self) -> None:
        self.generation_id = None
        self.receipt = None
        self.push_calls = []
        self.mode = "commit"

    def inspect(self, _channel: str) -> str | None:
        return self.generation_id

    def push(self, target, operation_id, attempt_id, prior_generation, token):
        self.push_calls.append((target, operation_id, attempt_id, prior_generation, token))
        if self.mode == "aborted":
            self.receipt = TokenPushReceipt(
                operation_id, target.channel, "token-push", "aborted", "aborted",
                attempt_id, prior_generation, None,
            )
            return self.receipt
        generation = str(uuid4())
        if self.mode == "applying":
            self.receipt = TokenPushReceipt(
                operation_id, target.channel, "token-push", "applying", None,
                attempt_id, prior_generation, generation,
            )
            raise TokenPushError()
        self.generation_id = generation
        self.receipt = TokenPushReceipt(
            operation_id, target.channel, "token-push", "committed", "committed",
            attempt_id, prior_generation, generation,
        )
        if self.mode == "lost-ack":
            raise TokenPushError()
        return self.receipt

    def reconcile(self, _target, operation_id, prior_generation):
        if (
            self.receipt is None
            or self.receipt.operation_id != operation_id
            or self.receipt.prior_generation != prior_generation
        ):
            raise TokenPushError()
        return self.receipt


def _host_admin(tmp_path: Path, remote, *, token_source=None) -> TokenPushAdmin:
    return TokenPushAdmin(
        controller=HostSecretController(tmp_path / "controller"),
        token_source=token_source or _StaticTokenSource(),
        remote_factory=lambda: remote,
    )


def _remote_state(
    tmp_path: Path,
    *,
    stage: str = "prepared",
    with_prior_generation: bool = True,
):
    state_root = tmp_path / "state"
    store = TokenPushStore(state_root, "dev")
    operation_id = str(uuid4())
    attempt_id = str(uuid4())
    prior_operation_id = str(uuid4())
    prior_generation = str(uuid4()) if with_prior_generation else None
    prior_pointer = None
    with store.locked():
        if prior_generation is not None:
            prior_pointer = store.install_generation(
                prior_operation_id, prior_generation, b"encrypted-old-reader-token"
            )
            store.activate(prior_pointer)
        store.write(TokenPushReceipt(
            operation_id,
            "dev",
            "token-push",
            stage,
            None,
            attempt_id,
            prior_generation,
            None,
        ))
    app_root = tmp_path / "app"
    (app_root / "config" / "deploy").mkdir(parents=True)
    return store, app_root, operation_id, attempt_id, prior_generation, prior_pointer


def _creds_runner(calls: list[tuple[list[str], bytes | None]], *, fail_encrypt=False):
    encrypted_values = {}

    def run(argv, *, input=None, capture_output, check):
        calls.append((list(argv), input))
        if argv[1] == "encrypt":
            if fail_encrypt:
                return subprocess.CompletedProcess(argv, 1, b"", b"redacted")
            encrypted = b"encrypted-fixture"
            encrypted_values[encrypted] = input
            return subprocess.CompletedProcess(argv, 0, encrypted, b"")
        if argv[1] == "decrypt":
            assert argv[-1] == "/dev/null"
            assert input in encrypted_values
            return subprocess.CompletedProcess(argv, 0, b"", b"")
        raise AssertionError(argv)

    return run


def test_vm_mapping_selects_channel_reader_and_project():
    targets = load_token_push_targets()
    assert (targets["ygg-dev"].channel, targets["ygg-dev"].project,
            targets["ygg-dev"].reader_account) == ("dev", "non-prod", "non-prod-reader")
    assert (targets["ygg-test"].channel, targets["ygg-test"].project,
            targets["ygg-test"].reader_account) == ("test", "non-prod", "non-prod-reader")
    assert (targets["ygg-prod"].channel, targets["ygg-prod"].project,
            targets["ygg-prod"].reader_account) == ("prod", "prod", "prod-reader")
    assert targets["ygg-prod"].keychain_account == "prod-reader.token"


def test_receipt_rejects_stage_generation_mismatch():
    malformed = TokenPushReceipt(
        str(uuid4()),
        "dev",
        "token-push",
        "committed",
        "committed",
        str(uuid4()),
        None,
        None,
    )
    with pytest.raises(TokenPushError):
        malformed.validate()


def test_push_token_encrypts_stdin_and_redacts_token(tmp_path, capsys):
    observed = []

    def ssh_runner(argv, *, input, capture_output, check):
        observed.append((list(argv), input))
        action = argv[8]
        if action == "token-push-inspect":
            return subprocess.CompletedProcess(argv, 0, b'{"generation_id":null}', b"")
        if action == "token-push":
            operation_id, attempt_id = argv[10], argv[11]
            receipt = TokenPushReceipt(
                operation_id, "prod", "token-push", "committed", "committed",
                attempt_id, None, str(uuid4()),
            )
            return subprocess.CompletedProcess(
                argv, 0, json.dumps(asdict(receipt)).encode(), b""
            )
        raise AssertionError(action)

    remote = SshTokenPushRemote(runner=ssh_runner)
    admin = TokenPushAdmin(
        controller=HostSecretController(tmp_path / "controller"),
        token_source=_StaticTokenSource(),
        remote_factory=lambda: remote,
    )
    assert secret_admin_main(["push-token", "ygg-prod"], token_push_admin=admin) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {
        "target": "ygg-prod", "project": "prod", "status": "pushed"
    }
    assert _CANARY not in captured.out + captured.err
    assert len(observed) == 2
    assert observed[0][1] is None
    assert observed[1][1] == _CANARY.encode()
    for argv, _input in observed:
        assert _CANARY not in " ".join(argv)


def test_failed_push_preserves_prior_encrypted_credential(tmp_path):
    store, app_root, operation_id, attempt_id, prior_generation, prior_pointer = _remote_state(tmp_path)
    calls = []
    receipt = vm_token_push_worker(
        app_root=app_root,
        state_root=store.state_root,
        channel="dev",
        operation_id=operation_id,
        attempt_id=attempt_id,
        source=_CANARY,
        runner=_creds_runner(calls, fail_encrypt=True),
    )
    assert receipt.stage == "aborted"
    assert receipt.terminal_result == "aborted"
    assert receipt.prior_generation == prior_generation
    assert store.current() == prior_pointer
    assert len(calls) == 1
    assert not (app_root / "config" / "deploy" / "dev.env.lock").exists()
    assert _CANARY.encode() not in store.journal_path.read_bytes()


def test_token_push_lost_ack_is_reconciled_by_generation_id(tmp_path):
    remote = _MemoryRemote()
    remote.mode = "lost-ack"
    admin = _host_admin(tmp_path, remote)
    with pytest.raises(TokenPushError):
        admin.push("ygg-test")
    first_operation = remote.push_calls[0][1]
    committed_generation = remote.generation_id
    result = admin.push("ygg-test")
    assert result.stage == "committed"
    assert result.operation_id == first_operation
    assert result.generation_id == committed_generation
    assert len(remote.push_calls) == 1


def test_token_push_retry_reuses_pending_operation_id(tmp_path):
    remote = _MemoryRemote()
    remote.mode = "aborted"
    admin = _host_admin(tmp_path, remote)
    with pytest.raises(TokenPushError):
        admin.push("ygg-dev")
    first_operation, first_attempt = remote.push_calls[0][1:3]
    remote.mode = "commit"
    result = admin.push("ygg-dev")
    second_operation, second_attempt = remote.push_calls[1][1:3]
    assert result.stage == "committed"
    assert second_operation == first_operation
    assert second_attempt != first_attempt


def test_token_push_unknown_remote_stage_blocks_retry_until_terminal_receipt(tmp_path):
    remote = _MemoryRemote()
    remote.mode = "applying"
    admin = _host_admin(tmp_path, remote)
    with pytest.raises(TokenPushError):
        admin.push("ygg-prod")
    remote.mode = "commit"
    with pytest.raises(TokenPushError):
        admin.push("ygg-prod")
    assert len(remote.push_calls) == 1


@pytest.mark.parametrize(
    ("vm", "field", "value"),
    [
        ("ygg-staging", None, None),
        ("ygg-test", "project", "prod"),
        ("ygg-test", "reader_account", "prod-reader"),
    ],
)
def test_invalid_vm_mapping_fails_before_remote_mutation(tmp_path, vm, field, value):
    called = False

    def remote_factory():
        nonlocal called
        called = True
        raise AssertionError("remote must not be constructed for an unknown VM")

    targets_path = Path("config/secrets/bws_reader_token_targets.json")
    if field is not None:
        payload = json.loads(targets_path.read_text())
        row = next(item for item in payload["targets"] if item["vm"] == vm)
        row[field] = value
        targets_path = tmp_path / "targets.json"
        targets_path.write_text(json.dumps(payload))

    admin = TokenPushAdmin(
        controller=HostSecretController(tmp_path / "controller"),
        token_source=_StaticTokenSource(),
        remote_factory=remote_factory,
        targets_path=targets_path,
    )
    with pytest.raises(TokenPushError):
        admin.push(vm)
    assert not called


def test_token_push_serializes_with_deploy_operation_lock(tmp_path):
    controller = HostSecretController(tmp_path / "controller")
    remote = _MemoryRemote()
    admin = _host_admin(tmp_path, remote)
    started = threading.Event()
    finished = threading.Event()

    with controller.deploy_operation("dev"):
        thread = threading.Thread(
            target=lambda: (started.set(), admin.push("ygg-dev"), finished.set()),
            daemon=True,
        )
        thread.start()
        assert started.wait(2)
        assert not finished.wait(0.1)
        assert remote.push_calls == []
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert finished.is_set()
    assert len(remote.push_calls) == 1


def test_repository_managed_reader_unit_binds_encrypted_credential():
    unit = Path("config/systemd/yggdrasil-bws-deploy@.service").read_text()
    assert (
        "LoadCredentialEncrypted=bws-machine-account-token:"
        "/var/lib/yggdrasil/bws-tokens/%i/current"
    ) in unit
    assert "Environment=BWS_ACCESS_TOKEN_FILE=%d/bws-machine-account-token" in unit
    assert "BWS_ACCESS_TOKEN=" not in unit


def test_remote_worker_installs_encrypted_generation_and_value_free_receipt(tmp_path):
    store, app_root, operation_id, attempt_id, prior_generation, prior_pointer = _remote_state(tmp_path)
    calls = []
    receipt = vm_token_push_worker(
        app_root=app_root,
        state_root=store.state_root,
        channel="dev",
        operation_id=operation_id,
        attempt_id=attempt_id,
        source=_CANARY,
        runner=_creds_runner(calls),
    )
    assert receipt.stage == "committed"
    assert receipt.prior_generation == prior_generation
    assert receipt.generation_id != prior_generation
    current = store.current()
    assert current is not None
    assert current.generation_id == receipt.generation_id
    assert current.operation_id == operation_id
    assert prior_pointer.generation_id == prior_generation
    assert prior_pointer.relative_path != current.relative_path
    assert calls[0][0][1] == "encrypt"
    assert calls[0][1] == _CANARY.encode()
    assert all(_CANARY not in " ".join(argv) for argv, _ in calls)
    persisted = b"".join(path.read_bytes() for path in store.state_root.rglob("*") if path.is_file())
    assert _CANARY.encode() not in persisted
    assert not (app_root / "config" / "deploy" / "dev.env.lock").exists()


def test_first_install_orders_durable_applying_and_terminal_before_unlock(
    tmp_path, monkeypatch
):
    store, app_root, operation_id, attempt_id, _prior_generation, _prior_pointer = (
        _remote_state(tmp_path, with_prior_generation=False)
    )
    assert store.current() is None
    events = []
    original_write = TokenPushStore.write
    original_activate = TokenPushStore.activate
    original_confirm = TokenPushStore.confirm_durable
    original_release = VmChannelMutationLock.release

    def record_durable_write(self, receipt):
        original_write(self, receipt)
        if receipt.stage == "applying":
            events.append(("durable-applying", receipt))

    def require_applying_before_activation(self, pointer):
        assert events and events[-1][0] == "durable-applying"
        assert self.read().stage == "applying"
        assert self.current() is None
        events.append(("activate", pointer))
        original_activate(self, pointer)

    def record_terminal_confirmation(self, receipt):
        confirmed = original_confirm(self, receipt)
        events.append(("confirmed", confirmed))
        return confirmed

    def require_confirmation_before_release(self, receipt):
        assert receipt.stage == "committed"
        assert events and events[-1] == ("confirmed", receipt)
        pointer = store.current()
        assert pointer is not None
        assert pointer.generation_id == receipt.generation_id
        assert pointer.operation_id == receipt.operation_id
        events.append(("released", receipt))
        original_release(self, receipt)

    monkeypatch.setattr(TokenPushStore, "write", record_durable_write)
    monkeypatch.setattr(
        TokenPushStore, "activate", require_applying_before_activation
    )
    monkeypatch.setattr(
        TokenPushStore, "confirm_durable", record_terminal_confirmation
    )
    monkeypatch.setattr(
        VmChannelMutationLock, "release", require_confirmation_before_release
    )

    committed = vm_token_push_worker(
        app_root=app_root,
        state_root=store.state_root,
        channel="dev",
        operation_id=operation_id,
        attempt_id=attempt_id,
        source=_CANARY,
        runner=_creds_runner([]),
    )

    assert committed.stage == "committed"
    assert [event[0] for event in events] == [
        "durable-applying",
        "activate",
        "confirmed",
        "released",
    ]
    assert store.current() is not None
    assert store.current().generation_id == committed.generation_id
    assert not (app_root / "config" / "deploy" / "dev.env.lock").exists()


def test_terminal_remote_receipt_reconciles_without_transient_unit(tmp_path):
    store, app_root, operation_id, attempt_id, _prior_generation, _prior_pointer = _remote_state(tmp_path)
    committed = vm_token_push_worker(
        app_root=app_root,
        state_root=store.state_root,
        channel="dev",
        operation_id=operation_id,
        attempt_id=attempt_id,
        source=_CANARY,
        runner=_creds_runner([]),
    )

    def unavailable_systemd(*_args, **_kwargs):
        raise AssertionError("a durable terminal receipt must not require a transient unit")

    assert vm_token_push_status(
        app_root=app_root,
        state_root=store.state_root,
        channel="dev",
        operation_id=operation_id,
        runner=unavailable_systemd,
    ) == committed


def test_prepared_remote_receipt_aborts_only_after_inactive_unit_and_unchanged_pointer(tmp_path):
    store, app_root, operation_id, _attempt_id, prior_generation, _prior_pointer = _remote_state(tmp_path)

    def inactive_systemd(argv, *, input, capture_output, check):
        assert argv[0:2] == ["systemctl", "show"]
        return subprocess.CompletedProcess(argv, 0, b"inactive\n", b"")

    receipt = vm_token_push_status(
        app_root=app_root,
        state_root=store.state_root,
        channel="dev",
        operation_id=operation_id,
        runner=inactive_systemd,
    )
    assert receipt.stage == "aborted"
    assert receipt.prior_generation == prior_generation
    assert store.current() is not None
    assert store.current().generation_id == prior_generation


def test_token_push_start_uses_supervised_worker_and_sends_token_only_on_stdin(tmp_path):
    store, app_root, operation_id, attempt_id, prior_generation, _prior_pointer = _remote_state(tmp_path)
    store.journal_path.unlink()
    systemd_calls = []
    credential_calls = []

    def supervised_runner(argv, *, input, capture_output, check):
        systemd_calls.append((list(argv), input))
        assert argv[0:5] == ["systemd-run", "--quiet", "--pipe", "--wait", "--collect"]
        assert argv[-4:] == ["token-push-worker", "dev", operation_id, attempt_id]
        vm_token_push_worker(
            app_root=app_root,
            state_root=store.state_root,
            channel="dev",
            operation_id=operation_id,
            attempt_id=attempt_id,
            source=input.decode("utf-8"),
            runner=_creds_runner(credential_calls),
        )
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    receipt = vm_token_push_start(
        app_root=app_root,
        state_root=store.state_root,
        channel="dev",
        operation_id=operation_id,
        attempt_id=attempt_id,
        prior_generation=prior_generation,
        source=_CANARY,
        runner=supervised_runner,
    )
    assert receipt.stage == "committed"
    assert len(systemd_calls) == 1
    argv, token_input = systemd_calls[0]
    assert token_input == _CANARY.encode()
    assert _CANARY not in " ".join(argv)
    assert credential_calls[0][1] == _CANARY.encode()


@pytest.mark.parametrize(
    "with_prior_generation", [True, False], ids=["retained", "first-install"]
)
def test_failed_terminal_commit_restores_prior_state_before_durable_abort_and_unlock(
    tmp_path, monkeypatch, with_prior_generation
):
    store, app_root, operation_id, attempt_id, _prior_generation, prior_pointer = _remote_state(
        tmp_path, with_prior_generation=with_prior_generation
    )
    original_write = TokenPushStore.write
    original_restore = TokenPushStore.restore
    original_confirm = TokenPushStore.confirm_durable
    original_release = VmChannelMutationLock.release
    events = []

    def restore_prior_state(self, pointer):
        original_restore(self, pointer)
        assert self.current() == pointer
        events.append(("restored", pointer))

    def fail_committed(self, receipt):
        if receipt.stage == "committed":
            raise TokenPushError()
        if receipt.stage == "aborted":
            assert events and events[-1] == ("restored", prior_pointer)
            assert self.current() == prior_pointer
            events.append(("abort-write", receipt))
        original_write(self, receipt)

    def record_terminal_confirmation(self, receipt):
        confirmed = original_confirm(self, receipt)
        events.append(("confirmed", confirmed))
        return confirmed

    def require_abort_confirmation_before_release(self, receipt):
        assert receipt.stage == "aborted"
        assert events and events[-1] == ("confirmed", receipt)
        assert store.current() == prior_pointer
        events.append(("released", receipt))
        original_release(self, receipt)

    monkeypatch.setattr(TokenPushStore, "write", fail_committed)
    monkeypatch.setattr(TokenPushStore, "restore", restore_prior_state)
    monkeypatch.setattr(
        TokenPushStore, "confirm_durable", record_terminal_confirmation
    )
    monkeypatch.setattr(
        VmChannelMutationLock, "release", require_abort_confirmation_before_release
    )
    receipt = vm_token_push_worker(
        app_root=app_root,
        state_root=store.state_root,
        channel="dev",
        operation_id=operation_id,
        attempt_id=attempt_id,
        source=_CANARY,
        runner=_creds_runner([]),
    )
    assert receipt.stage == "aborted"
    assert receipt.terminal_result == "aborted"
    assert store.current() == prior_pointer
    assert [event[0] for event in events] == [
        "restored",
        "abort-write",
        "confirmed",
        "released",
    ]
    assert not (app_root / "config" / "deploy" / "dev.env.lock").exists()


def test_unresolved_compensation_retains_owned_lock_and_applying_receipt(
    tmp_path, monkeypatch
):
    store, app_root, operation_id, attempt_id, _prior_generation, prior_pointer = _remote_state(
        tmp_path
    )
    original_write = TokenPushStore.write

    def fail_terminal(self, receipt):
        if receipt.stage in {"committed", "aborted"}:
            raise TokenPushError()
        original_write(self, receipt)

    monkeypatch.setattr(TokenPushStore, "write", fail_terminal)
    with pytest.raises(TokenPushError):
        vm_token_push_worker(
            app_root=app_root,
            state_root=store.state_root,
            channel="dev",
            operation_id=operation_id,
            attempt_id=attempt_id,
            source=_CANARY,
            runner=_creds_runner([]),
        )

    lock_path = app_root / "config" / "deploy" / "dev.env.lock"
    assert lock_path.is_dir()
    assert json.loads((lock_path / "bws-owner").read_text()) == {
        "kind": "token-push",
        "operation_id": operation_id,
        "attempt_id": attempt_id,
    }
    assert store.read() is not None
    assert store.read().stage == "applying"
    assert store.current() == prior_pointer

    def inactive_systemd(argv, *, input, capture_output, check):
        return subprocess.CompletedProcess(argv, 0, b"inactive\n", b"")

    with pytest.raises(TokenPushError):
        vm_token_push_status(
            app_root=app_root,
            state_root=store.state_root,
            channel="dev",
            operation_id=operation_id,
            runner=inactive_systemd,
        )
    assert lock_path.is_dir()


def test_prepared_attempt_reclaims_own_stale_lock_and_retries_same_id(tmp_path):
    store, app_root, operation_id, attempt_id, prior_generation, _prior_pointer = _remote_state(
        tmp_path
    )
    stale = VmChannelMutationLock(app_root, "dev", operation_id, attempt_id)
    stale.__enter__()
    assert stale.acquired
    stale.__exit__()  # Simulate a dead worker: release flock but retain its marker.
    lock_path = app_root / "config" / "deploy" / "dev.env.lock"
    assert lock_path.is_dir()

    def inactive_systemd(argv, *, input, capture_output, check):
        assert argv[0:2] == ["systemctl", "show"]
        return subprocess.CompletedProcess(argv, 0, b"inactive\n", b"")

    aborted = vm_token_push_status(
        app_root=app_root,
        state_root=store.state_root,
        channel="dev",
        operation_id=operation_id,
        runner=inactive_systemd,
    )
    assert aborted.stage == "aborted"
    assert not lock_path.exists()

    next_attempt = str(uuid4())
    credential_calls = []

    def supervised_runner(argv, *, input, capture_output, check):
        vm_token_push_worker(
            app_root=app_root,
            state_root=store.state_root,
            channel="dev",
            operation_id=argv[-2],
            attempt_id=argv[-1],
            source=input.decode(),
            runner=_creds_runner(credential_calls),
        )
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    committed = vm_token_push_start(
        app_root=app_root,
        state_root=store.state_root,
        channel="dev",
        operation_id=operation_id,
        attempt_id=next_attempt,
        prior_generation=prior_generation,
        source=_CANARY,
        runner=supervised_runner,
    )
    assert committed.stage == "committed"
    assert committed.operation_id == operation_id
    assert committed.attempt_id == next_attempt


def test_prepared_status_will_not_reclaim_a_matching_lock_while_flock_is_held(tmp_path):
    store, app_root, operation_id, attempt_id, _prior_generation, _prior_pointer = _remote_state(
        tmp_path
    )
    held = VmChannelMutationLock(app_root, "dev", operation_id, attempt_id)
    held.__enter__()
    assert held.acquired

    def inactive_systemd(argv, *, input, capture_output, check):
        return subprocess.CompletedProcess(argv, 0, b"inactive\n", b"")

    with pytest.raises(TokenPushError):
        vm_token_push_status(
            app_root=app_root,
            state_root=store.state_root,
            channel="dev",
            operation_id=operation_id,
            runner=inactive_systemd,
        )
    assert store.read().stage == "prepared"
    lock_path = app_root / "config" / "deploy" / "dev.env.lock"
    assert lock_path.is_dir()

    held.__exit__()  # Simulate worker death only after proving the live lock was retained.
    aborted = vm_token_push_status(
        app_root=app_root,
        state_root=store.state_root,
        channel="dev",
        operation_id=operation_id,
        runner=inactive_systemd,
    )
    assert aborted.stage == "aborted"
    assert not lock_path.exists()


@pytest.mark.parametrize("owner_state", ["missing", "deploy-empty", "foreign"])
def test_prepared_status_refuses_unknown_or_foreign_channel_lock(tmp_path, owner_state):
    store, app_root, operation_id, _attempt_id, _prior_generation, _prior_pointer = _remote_state(
        tmp_path
    )
    lock_path = app_root / "config" / "deploy" / "dev.env.lock"
    lock_path.mkdir(mode=0o700)
    owner_path = lock_path / "bws-owner"
    if owner_state == "deploy-empty":
        owner_path.write_bytes(b"")
        owner_path.chmod(0o600)
    elif owner_state == "foreign":
        owner_path.write_text(
            json.dumps(
                {
                    "kind": "token-push",
                    "operation_id": str(uuid4()),
                    "attempt_id": str(uuid4()),
                }
            )
        )
        owner_path.chmod(0o600)

    def inactive_systemd(argv, *, input, capture_output, check):
        return subprocess.CompletedProcess(argv, 0, b"inactive\n", b"")

    with pytest.raises(TokenPushError):
        vm_token_push_status(
            app_root=app_root,
            state_root=store.state_root,
            channel="dev",
            operation_id=operation_id,
            runner=inactive_systemd,
        )
    assert store.read() is not None
    assert store.read().stage == "prepared"
    assert lock_path.is_dir()
    assert owner_path.exists() is (owner_state != "missing")
    if owner_state == "deploy-empty":
        assert owner_path.read_bytes() == b""


def test_worker_contention_preserves_foreign_deploy_lock_until_it_can_abort(tmp_path):
    store, app_root, operation_id, attempt_id, _prior_generation, _prior_pointer = _remote_state(
        tmp_path
    )
    lock_path = app_root / "config" / "deploy" / "dev.env.lock"
    lock_path.mkdir(mode=0o700)
    owner_path = lock_path / "bws-owner"
    owner_path.write_bytes(b"")
    owner_path.chmod(0o600)

    with pytest.raises(TokenPushError):
        vm_token_push_worker(
            app_root=app_root,
            state_root=store.state_root,
            channel="dev",
            operation_id=operation_id,
            attempt_id=attempt_id,
            source=_CANARY,
            runner=_creds_runner([]),
        )
    assert store.read() is not None
    assert store.read().stage == "prepared"
    assert owner_path.read_bytes() == b""

    def inactive_systemd(argv, *, input, capture_output, check):
        return subprocess.CompletedProcess(argv, 0, b"inactive\n", b"")

    with pytest.raises(TokenPushError):
        vm_token_push_status(
            app_root=app_root,
            state_root=store.state_root,
            channel="dev",
            operation_id=operation_id,
            runner=inactive_systemd,
        )
    assert store.read().stage == "prepared"
    owner_path.unlink()
    lock_path.rmdir()  # Simulate the deploy releasing its own terminal lock.
    aborted = vm_token_push_status(
        app_root=app_root,
        state_root=store.state_root,
        channel="dev",
        operation_id=operation_id,
        runner=inactive_systemd,
    )
    assert aborted.stage == "aborted"
    assert not lock_path.exists()


def test_terminal_receipt_read_requires_directory_sync_and_can_retry(tmp_path, monkeypatch):
    store, app_root, operation_id, attempt_id, _prior_generation, _prior_pointer = _remote_state(
        tmp_path
    )
    committed = vm_token_push_worker(
        app_root=app_root,
        state_root=store.state_root,
        channel="dev",
        operation_id=operation_id,
        attempt_id=attempt_id,
        source=_CANARY,
        runner=_creds_runner([]),
    )
    directory_info = store.journal_directory.stat()
    real_fsync = os.fsync

    def fail_journal_directory_sync(descriptor):
        info = os.fstat(descriptor)
        if stat.S_ISDIR(info.st_mode) and (info.st_dev, info.st_ino) == (
            directory_info.st_dev,
            directory_info.st_ino,
        ):
            raise OSError("injected directory sync failure")
        real_fsync(descriptor)

    monkeypatch.setattr(bws_token_push.os, "fsync", fail_journal_directory_sync)
    with pytest.raises(TokenPushError):
        vm_token_push_status(
            app_root=app_root,
            state_root=store.state_root,
            channel="dev",
            operation_id=operation_id,
        )

    monkeypatch.setattr(bws_token_push.os, "fsync", real_fsync)
    assert vm_token_push_status(
        app_root=app_root,
        state_root=store.state_root,
        channel="dev",
        operation_id=operation_id,
    ) == committed


def test_terminal_replace_sync_failure_retains_lock_until_status_confirms(
    tmp_path, monkeypatch
):
    store, app_root, operation_id, attempt_id, _prior_generation, _prior_pointer = (
        _remote_state(tmp_path)
    )
    journal_info = store.journal_directory.stat()
    real_fsync = os.fsync
    failed_syncs = []

    def fail_visible_terminal_sync(descriptor):
        info = os.fstat(descriptor)
        if stat.S_ISDIR(info.st_mode) and (info.st_dev, info.st_ino) == (
            journal_info.st_dev,
            journal_info.st_ino,
        ):
            visible = store.read()
            if visible is not None and visible.terminal_result == "committed":
                failed_syncs.append(visible)
                raise OSError("injected terminal journal-directory sync failure")
        real_fsync(descriptor)

    monkeypatch.setattr(bws_token_push.os, "fsync", fail_visible_terminal_sync)
    with pytest.raises(TokenPushError):
        vm_token_push_worker(
            app_root=app_root,
            state_root=store.state_root,
            channel="dev",
            operation_id=operation_id,
            attempt_id=attempt_id,
            source=_CANARY,
            runner=_creds_runner([]),
        )

    lock_path = app_root / "config" / "deploy" / "dev.env.lock"
    visible_terminal = store.read()
    assert visible_terminal is not None
    assert visible_terminal.stage == "committed"
    assert len(failed_syncs) >= 2
    assert lock_path.is_dir()

    with pytest.raises(TokenPushError):
        vm_token_push_status(
            app_root=app_root,
            state_root=store.state_root,
            channel="dev",
            operation_id=operation_id,
        )
    assert lock_path.is_dir()

    monkeypatch.setattr(bws_token_push.os, "fsync", real_fsync)
    assert vm_token_push_status(
        app_root=app_root,
        state_root=store.state_root,
        channel="dev",
        operation_id=operation_id,
    ) == visible_terminal
    assert not lock_path.exists()


def test_terminal_receipt_reclaims_its_stale_lock_after_durable_confirmation(
    tmp_path, monkeypatch
):
    store, app_root, operation_id, attempt_id, _prior_generation, _prior_pointer = _remote_state(
        tmp_path
    )
    original_release = VmChannelMutationLock.release

    def leave_lock(self, _receipt):
        raise TokenPushError()

    monkeypatch.setattr(VmChannelMutationLock, "release", leave_lock)
    with pytest.raises(TokenPushError):
        vm_token_push_worker(
            app_root=app_root,
            state_root=store.state_root,
            channel="dev",
            operation_id=operation_id,
            attempt_id=attempt_id,
            source=_CANARY,
            runner=_creds_runner([]),
        )
    lock_path = app_root / "config" / "deploy" / "dev.env.lock"
    assert lock_path.is_dir()
    assert store.read().stage == "committed"

    monkeypatch.setattr(VmChannelMutationLock, "release", original_release)
    committed = vm_token_push_status(
        app_root=app_root,
        state_root=store.state_root,
        channel="dev",
        operation_id=operation_id,
    )
    assert committed.stage == "committed"
    assert not lock_path.exists()


def test_inspect_requires_terminal_receipt_durability(tmp_path, monkeypatch):
    store, app_root, operation_id, attempt_id, _prior_generation, _prior_pointer = _remote_state(
        tmp_path
    )
    vm_token_push_worker(
        app_root=app_root,
        state_root=store.state_root,
        channel="dev",
        operation_id=operation_id,
        attempt_id=attempt_id,
        source=_CANARY,
        runner=_creds_runner([]),
    )
    original_confirm = TokenPushStore.confirm_durable

    def refuse_confirmation(self, _receipt):
        raise TokenPushError()

    monkeypatch.setattr(TokenPushStore, "confirm_durable", refuse_confirmation)
    with pytest.raises(TokenPushError):
        vm_token_push_inspect(
            app_root=app_root,
            state_root=store.state_root,
            channel="dev",
        )
    monkeypatch.setattr(TokenPushStore, "confirm_durable", original_confirm)
    pointer = store.current()
    assert pointer is not None
    assert vm_token_push_inspect(
        app_root=app_root,
        state_root=store.state_root,
        channel="dev",
    )["generation_id"] == pointer.generation_id


def test_start_refuses_terminal_receipt_until_durability_is_confirmed(tmp_path, monkeypatch):
    store, app_root, operation_id, attempt_id, _prior_generation, _prior_pointer = _remote_state(
        tmp_path
    )
    committed = vm_token_push_worker(
        app_root=app_root,
        state_root=store.state_root,
        channel="dev",
        operation_id=operation_id,
        attempt_id=attempt_id,
        source=_CANARY,
        runner=_creds_runner([]),
    )
    original_confirm = TokenPushStore.confirm_durable

    def refuse_confirmation(self, _receipt):
        raise TokenPushError()

    monkeypatch.setattr(TokenPushStore, "confirm_durable", refuse_confirmation)
    with pytest.raises(TokenPushError):
        vm_token_push_start(
            app_root=app_root,
            state_root=store.state_root,
            channel="dev",
            operation_id=operation_id,
            attempt_id=str(uuid4()),
            prior_generation=committed.generation_id,
            source=_CANARY,
            runner=lambda *_args, **_kwargs: pytest.fail(
                "an unconfirmed terminal receipt must not dispatch a worker"
            ),
        )
    monkeypatch.setattr(TokenPushStore, "confirm_durable", original_confirm)
    assert store.read() == committed


@pytest.mark.parametrize("receipt_state", ["missing", "unknown-stage", "other-operation"])
def test_status_refuses_missing_malformed_or_mismatched_receipt(tmp_path, receipt_state):
    store, app_root, operation_id, _attempt_id, _prior_generation, _prior_pointer = _remote_state(
        tmp_path
    )
    if receipt_state == "missing":
        store.journal_path.unlink()
    else:
        payload = json.loads(store.journal_path.read_text())
        if receipt_state == "unknown-stage":
            payload["stage"] = "unexpected"
        else:
            payload["operation_id"] = str(uuid4())
        store.journal_path.write_text(json.dumps(payload))

    def systemd_must_not_run(*_args, **_kwargs):
        pytest.fail("invalid remote state must fail before unit lookup")

    with pytest.raises(TokenPushError):
        vm_token_push_status(
            app_root=app_root,
            state_root=store.state_root,
            channel="dev",
            operation_id=operation_id,
            runner=systemd_must_not_run,
        )
    assert not (app_root / "config" / "deploy" / "dev.env.lock").exists()


def test_deploy_launcher_parses_and_forwards_token_push_worker_arguments(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace

    app_root = tmp_path / "app"
    app_root.mkdir()
    operation_id = str(uuid4())
    attempt_id = str(uuid4())
    observed = {}

    def fake_worker(**kwargs):
        observed.update(kwargs)

    monkeypatch.setattr(bws_token_push, "vm_token_push_worker", fake_worker)
    monkeypatch.setattr(
        postgres_deploy_linux.LinuxConfig,
        "load",
        classmethod(lambda _cls, _channel: SimpleNamespace(root=app_root)),
    )
    monkeypatch.setattr(sys, "stdin", StringIO(_CANARY))

    assert (
        postgres_deploy_linux.main(
            ["token-push-worker", "dev", operation_id, attempt_id]
        )
        == 0
    )
    assert observed == {
        "app_root": app_root,
        "channel": "dev",
        "operation_id": operation_id,
        "attempt_id": attempt_id,
        "source": _CANARY,
    }
