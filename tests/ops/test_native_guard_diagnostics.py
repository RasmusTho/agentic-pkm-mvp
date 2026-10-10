from __future__ import annotations

import errno
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


def _run_guard_child(socket_path: Path) -> subprocess.CompletedProcess[str]:
    child = """
import sys
from app.ops import postgres_deploy_linux as linux

linux._DEPLOY_JOURNAL_SOCKET = sys.argv[1]

def fail(_channel):
    raise RuntimeError('argv-secret-canary env-secret-canary')

linux.LinuxConfig.load = fail
raise SystemExit(linux.main(['guard', 'test']))
"""
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT)}
    return subprocess.run(
        [sys.executable, "-c", child, str(socket_path)],
        cwd=REPO_ROOT,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
        timeout=5,
    )


def test_guard_checkpoint_reaches_journal_with_raw_streams_null() -> None:
    with tempfile.TemporaryDirectory(prefix="g5930-", dir="/tmp") as directory:
        socket_path = Path(directory) / "journal.sock"
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as receiver:
            receiver.bind(str(socket_path))
            result = _run_guard_child(socket_path)
            assert result.returncode == 78
            receiver.settimeout(2)
            assert receiver.recv(4096) == (
                "PRIORITY=3\nSYSLOG_IDENTIFIER=yggdrasil-bws-deploy\n"
                "MESSAGE=native deployment failure: "
                "checkpoint=config_runtime_file_binding class=guard_refused\n"
            ).encode("ascii")
            receiver.settimeout(0.05)
            with pytest.raises(socket.timeout):
                receiver.recv(4096)


def test_guard_diagnostic_preserves_success_and_original_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from app.ops import postgres_deploy_linux as linux
    from app.ops.postgres_deploy import PostgresDeployError

    directory = tmp_path / "config" / "deploy"
    directory.mkdir(parents=True)
    (directory / "test.env").write_text("APP_IMAGE_TAG=" + "a" * 40 + "\n")
    lock = directory / "test.env.lock"
    lock.mkdir()
    owner = lock / "bws-owner"
    owner.touch()
    password = tmp_path / "password"
    password.write_text("fixture-password")
    runtime = tmp_path / "runtime.env"
    runtime.write_text("LLM_PROVIDER=mock\n")
    cfg = SimpleNamespace(
        root=tmp_path,
        channel="test",
        password_file=password,
        runtime_env_file=runtime,
        reader=lambda: object(),
        journal=SimpleNamespace(
            read=lambda: SimpleNamespace(stage="activating", operation_id="operation"),
        ),
    )
    monkeypatch.setattr(linux.LinuxConfig, "load", lambda channel: cfg)
    monkeypatch.setattr(linux, "_capture_watch_configured", lambda config: False)
    monkeypatch.setattr(linux.PasswordSource, "verify", lambda self: None)
    monkeypatch.setattr(linux, "validate_database_inputs", lambda *args: None)
    monkeypatch.setattr(
        linux,
        "vm_selected_values",
        lambda *args: {"postgres-db": {"postgres.password": "fixture-password"}},
    )
    environment = {
        "BWS_DEPLOY_RUNTIME_ENV_FILE": str(runtime),
        "BWS_DEPLOY_LOCK_FD": "0",
        "BWS_DEPLOY_OPERATION_ID": "operation",
        "BWS_EXPECTED_CAPTURE_WATCH_CONFIGURED": "0",
        "BWS_EXPECTED_RAW_MIGRATION_PENDING": "0",
        "BWS_DEPLOY_TARGET_REVISION": "a" * 40,
        "DEPLOY_HEIMDAL_RAW_MIGRATION_PENDING": "0",
        "BWS_DATABASE_TARGET": "local",
    }
    with owner.open("r+") as handle:
        environment["BWS_DEPLOY_LOCK_FD"] = str(handle.fileno())
        monkeypatch.setattr(os, "environ", environment)
        with tempfile.TemporaryDirectory(prefix="g5930-", dir="/tmp") as socket_directory:
            socket_path = Path(socket_directory) / "journal.sock"
            with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as receiver:
                receiver.bind(str(socket_path))
                monkeypatch.setattr(linux, "_DEPLOY_JOURNAL_SOCKET", str(socket_path))
                linux.inherited_worker_guard("test")
                receiver.settimeout(0.05)
                with pytest.raises(socket.timeout):
                    receiver.recv(4096)

        expected = PostgresDeployError()
        monkeypatch.setattr(linux.LinuxConfig, "load", lambda channel: (_ for _ in ()).throw(expected))
        with pytest.raises(PostgresDeployError) as failure:
            linux.inherited_worker_guard("test")
        assert failure.value is expected


@pytest.mark.parametrize("sink", ["missing", "refused", "full"])
def test_guard_checkpoint_diagnostic_is_finite_and_nonblocking(sink: str) -> None:
    with tempfile.TemporaryDirectory(prefix="g5930-", dir="/tmp") as directory:
        socket_path = Path(directory) / "journal.sock"
        receiver: socket.socket | None = None
        fillers: list[socket.socket] = []
        try:
            if sink == "refused":
                socket_path.touch()
            elif sink == "full":
                receiver = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
                receiver.bind(str(socket_path))
                receiver.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024)
                for _ in range(64):
                    filler = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
                    filler.setblocking(False)
                    fillers.append(filler)
                    for sent in range(4096):
                        try:
                            filler.sendto(b"queue-prefill", str(socket_path))
                        except OSError as error:
                            assert error.errno in {errno.EAGAIN, errno.EWOULDBLOCK, errno.ENOBUFS}
                            break
                    if sent == 0:
                        break
                else:
                    pytest.fail("could not fill the private datagram queue")
            result = _run_guard_child(socket_path)
            assert result.returncode == 78
            if receiver is not None:
                receiver.setblocking(False)
                while True:
                    try:
                        receiver.recv(4096)
                    except BlockingIOError:
                        break
        finally:
            for filler in fillers:
                filler.close()
            if receiver is not None:
                receiver.close()
