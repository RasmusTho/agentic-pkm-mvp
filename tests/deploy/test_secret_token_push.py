from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import subprocess
import threading
from uuid import uuid4

import pytest

from app.ops.bws_token_push import (
    SshTokenPushRemote,
    TokenPushAdmin,
    TokenPushError,
    TokenPushReceipt,
    TokenPushStore,
    load_token_push_targets,
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


def _remote_state(tmp_path: Path, *, stage: str = "prepared"):
    state_root = tmp_path / "state"
    store = TokenPushStore(state_root, "dev")
    operation_id = str(uuid4())
    attempt_id = str(uuid4())
    prior_operation_id = str(uuid4())
    prior_generation = str(uuid4())
    prior_pointer = None
    with store.locked():
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
            return subprocess.CompletedProcess(argv, 0, encrypted_values[input], b"")
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


def test_invalid_vm_mapping_fails_before_remote_mutation(tmp_path):
    called = False

    def remote_factory():
        nonlocal called
        called = True
        raise AssertionError("remote must not be constructed for an unknown VM")

    admin = TokenPushAdmin(
        controller=HostSecretController(tmp_path / "controller"),
        token_source=_StaticTokenSource(),
        remote_factory=remote_factory,
    )
    with pytest.raises(TokenPushError):
        admin.push("ygg-staging")
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
        state_root=store.state_root,
        channel="dev",
        operation_id=operation_id,
        runner=unavailable_systemd,
    ) == committed


def test_prepared_remote_receipt_aborts_only_after_inactive_unit_and_unchanged_pointer(tmp_path):
    store, _app_root, operation_id, _attempt_id, prior_generation, _prior_pointer = _remote_state(tmp_path)

    def inactive_systemd(argv, *, input, capture_output, check):
        assert argv[0:2] == ["systemctl", "show"]
        return subprocess.CompletedProcess(argv, 0, b"inactive\n", b"")

    receipt = vm_token_push_status(
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
