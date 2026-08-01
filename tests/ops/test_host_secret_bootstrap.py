from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import ctypes
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import time

import pytest

import app.ops.host_secret_bootstrap as host_secret_bootstrap
from app.ops.host_secret_bootstrap import (
    HOST_SECRET_BOOTSTRAP_FAILURE_REF,
    HOST_SECRET_RUNTIME_ENV_FILE,
    HostSecretBootstrapError,
    HostSecretBootstrapTerminated,
    KeychainLookup,
    materialize_consumer_environment,
    load_runtime_secret_values,
    run_with_host_secrets,
)


_RAW_KEY = "a" * 64
_OPENAI_KEY = "openai-key-" + ("o" * 32)
_ANTHROPIC_KEY = "anthropic-key-" + ("a" * 32)
_GITHUB_TOKEN = "ghp_" + ("g" * 36)
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _lookup(value: str = _RAW_KEY) -> KeychainLookup:
    return lambda _service, _account: value


def test_consumer_gets_only_allowlisted_values(tmp_path: Path) -> None:
    requested: list[tuple[str, str]] = []

    def lookup(service: str, account: str) -> str:
        requested.append((service, account))
        return _RAW_KEY

    with materialize_consumer_environment(
        channel="dev",
        consumer="heimdal-capture-watch",
        keychain_lookup=lookup,
        directory=tmp_path,
    ) as env_file:
        assert env_file.read_text(encoding="utf-8") == f"HEIMDAL_RAW_STORE_KEY={_RAW_KEY}\n"

    assert requested == [
        (
            "yggdrasil.host-secrets",
            "dev:heimdal-capture-watch:heimdal.raw-store-key",
        )
    ]


@pytest.mark.parametrize(
    ("lookup", "secret_fragment"),
    [
        (
            lambda _service, _account: (_ for _ in ()).throw(
                OSError("denied leaked-value")
            ),
            "leaked-value",
        ),
        (lambda _service, _account: "malformed-secret-value", "malformed-secret-value"),
        (lambda _service, _account: "", ""),
    ],
)
def test_missing_or_malformed_secret_fails_closed(
    tmp_path: Path,
    lookup: KeychainLookup,
    secret_fragment: str,
) -> None:
    launched = False

    def runner(_command: list[str], _env: dict[str, str]) -> int:
        nonlocal launched
        launched = True
        return 0

    with pytest.raises(HostSecretBootstrapError) as error:
        run_with_host_secrets(
            channel="dev",
            consumer="heimdal-capture-watch",
            command=["never-start"],
            keychain_lookup=lookup,
            runner=runner,
            directory=tmp_path,
        )

    assert not launched
    assert str(error.value) == "host secret bootstrap failed for declared consumer"
    if secret_fragment:
        assert secret_fragment not in str(error.value)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "missing_or_malformed",
    [None, "", "short", "contains whitespace", "x" * 513, "x" * 20 + "\n"],
)
def test_missing_model_provider_secret_fails_consumer_closed(
    tmp_path: Path,
    missing_or_malformed: str | None,
) -> None:
    launched = False

    def lookup(_service: str, account: str) -> str:
        if account.endswith(":anthropic.api-key"):
            return _ANTHROPIC_KEY
        if missing_or_malformed is None:
            raise OSError("keychain item is absent")
        return missing_or_malformed

    def runner(_command: list[str], _env: dict[str, str]) -> int:
        nonlocal launched
        launched = True
        return 0

    with pytest.raises(HostSecretBootstrapError) as error:
        run_with_host_secrets(
            channel="dev",
            consumer="builderops-model-inquiry",
            command=["never-start"],
            keychain_lookup=lookup,
            runner=runner,
            directory=tmp_path,
        )

    assert not launched
    assert "openai.api-key" in str(error.value)
    if missing_or_malformed:
        assert missing_or_malformed not in str(error.value)
    assert list(tmp_path.iterdir()) == []


def test_model_provider_failure_can_reach_typed_receipt_consumer(
    tmp_path: Path,
) -> None:
    observed_env: dict[str, str] = {}

    def lookup(_service: str, account: str) -> str:
        if account.endswith(":anthropic.api-key"):
            return _ANTHROPIC_KEY
        raise OSError("keychain item is absent")

    def runner(_command: list[str], env: dict[str, str]) -> int:
        observed_env.update(env)
        return 19

    result = run_with_host_secrets(
        channel="dev",
        consumer="builderops-model-inquiry",
        command=["typed-receipt-consumer"],
        keychain_lookup=lookup,
        runner=runner,
        directory=tmp_path,
        run_on_credential_unavailable=True,
    )

    assert result == 19
    assert observed_env[HOST_SECRET_BOOTSTRAP_FAILURE_REF] == "openai.api-key"
    assert HOST_SECRET_RUNTIME_ENV_FILE not in observed_env
    assert set(observed_env).isdisjoint(
        {"OPENAI_API_KEY", "ANTHROPIC_API_KEY", "HEIMDAL_RAW_STORE_KEY"}
    )
    assert list(tmp_path.iterdir()) == []


def test_default_keychain_lookup_preserves_malformed_control_character(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    launched = False

    def runner(_command: list[str], _env: dict[str, str]) -> int:
        nonlocal launched
        launched = True
        return 0

    monkeypatch.setattr(
        host_secret_bootstrap,
        "_security_framework_keychain_lookup",
        lambda _service, _account: _OPENAI_KEY + "\r",
    )

    with pytest.raises(HostSecretBootstrapError):
        run_with_host_secrets(
            channel="dev",
            consumer="builderops-model-inquiry",
            command=["never-start"],
            runner=runner,
            directory=tmp_path,
        )

    assert not launched
    assert list(tmp_path.iterdir()) == []


def test_security_framework_lookup_returns_exact_keychain_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = (_OPENAI_KEY + "\r\n").encode()
    backing_buffer = ctypes.create_string_buffer(payload)

    class FakeFunction:
        def __init__(self, callback: object) -> None:
            self.callback = callback
            self.argtypes: object = None
            self.restype: object = None

        def __call__(self, *args: object) -> int:
            return self.callback(*args)  # type: ignore[operator, no-any-return]

    def find_password(
        _keychain: object,
        _service_length: object,
        _service: object,
        _account_length: object,
        _account: object,
        password_length: object,
        password_data: object,
        _item: object,
    ) -> int:
        password_length._obj.value = len(payload)  # type: ignore[attr-defined]
        password_data._obj.value = ctypes.addressof(backing_buffer)  # type: ignore[attr-defined]
        return 0

    class FakeFramework:
        SecKeychainFindGenericPassword = FakeFunction(find_password)
        SecKeychainItemFreeContent = FakeFunction(lambda _attrs, _data: 0)

    monkeypatch.setattr(
        host_secret_bootstrap.ctypes,
        "CDLL",
        lambda _path: FakeFramework(),
    )

    assert host_secret_bootstrap._security_framework_keychain_lookup(
        "service",
        "dev:builderops-model-inquiry:openai.api-key",
    ) == _OPENAI_KEY + "\r\n"


def test_unknown_secret_kind_still_fails_closed(tmp_path: Path) -> None:
    contract = host_secret_bootstrap.load_host_secret_contract()
    unknown_kind_contract = host_secret_bootstrap.HostSecretContract(
        keychain_service=contract.keychain_service,
        keychain_account_template=contract.keychain_account_template,
        allowed=contract.allowed,
        secret_definitions=tuple(
            (logical_id, binding, "unknown-kind" if logical_id == "openai.api-key" else kind)
            for logical_id, binding, kind in contract.secret_definitions
        ),
        role_requirements=contract.role_requirements,
    )

    with pytest.raises(
        HostSecretBootstrapError,
        match="host secret bootstrap failed for declared consumer",
    ):
        run_with_host_secrets(
            channel="dev",
            consumer="builderops-model-inquiry",
            command=["never-start"],
            keychain_lookup=lambda _service, account: (
                _OPENAI_KEY if account.endswith(":openai.api-key") else _ANTHROPIC_KEY
            ),
            runner=lambda _command, _env: 0,
            contract=unknown_kind_contract,
            directory=tmp_path,
        )


def test_model_consumer_gets_only_allowlisted_values(tmp_path: Path) -> None:
    requested_accounts: list[str] = []

    def lookup(_service: str, account: str) -> str:
        requested_accounts.append(account)
        if account.endswith(":openai.api-key"):
            return _OPENAI_KEY
        if account.endswith(":anthropic.api-key"):
            return _ANTHROPIC_KEY
        pytest.fail(f"unexpected account lookup: {account}")

    observed_path: Path | None = None

    def runner(_command: list[str], env: dict[str, str]) -> int:
        nonlocal observed_path
        observed_path = Path(env["HOST_SECRET_RUNTIME_ENV_FILE"])
        assert set(env).isdisjoint({"OPENAI_API_KEY", "ANTHROPIC_API_KEY", "HEIMDAL_RAW_STORE_KEY"})
        assert observed_path.read_text(encoding="utf-8") == (
            f"ANTHROPIC_API_KEY={_ANTHROPIC_KEY}\n"
            f"OPENAI_API_KEY={_OPENAI_KEY}\n"
        )
        return 0

    assert (
        run_with_host_secrets(
            channel="dev",
            consumer="builderops-model-inquiry",
            command=["consumer"],
            keychain_lookup=lookup,
            runner=runner,
            directory=tmp_path,
        )
        == 0
    )
    assert requested_accounts == [
        "dev:builderops-model-inquiry:anthropic.api-key",
        "dev:builderops-model-inquiry:openai.api-key",
    ]
    assert observed_path is not None and not observed_path.exists()


def test_model_provider_secret_is_never_disclosed(tmp_path: Path) -> None:
    leaked_value = "model-provider-secret-" + ("z" * 32)

    def lookup(_service: str, account: str) -> str:
        if account.endswith(":anthropic.api-key"):
            return _ANTHROPIC_KEY
        raise OSError(f"lookup denied for {leaked_value}")

    with pytest.raises(HostSecretBootstrapError) as error:
        run_with_host_secrets(
            channel="dev",
            consumer="builderops-model-inquiry",
            command=["never-start"],
            keychain_lookup=lookup,
            directory=tmp_path,
        )

    assert leaked_value not in str(error.value)
    assert "openai.api-key" in str(error.value)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("return_code", [0, 23])
def test_runtime_secret_file_is_mode_0600_and_cleaned_up(
    tmp_path: Path,
    return_code: int,
) -> None:
    observed_path: Path | None = None

    def runner(_command: list[str], env: dict[str, str]) -> int:
        nonlocal observed_path
        observed_path = Path(env["HOST_SECRET_RUNTIME_ENV_FILE"])
        assert observed_path.is_file()
        assert stat.S_IMODE(observed_path.stat().st_mode) == 0o600
        assert env.get("HEIMDAL_RAW_STORE_KEY") is None
        assert observed_path.read_text(encoding="utf-8") == (
            f"HEIMDAL_RAW_STORE_KEY={_RAW_KEY}\n"
        )
        return return_code

    result = run_with_host_secrets(
        channel="dev",
        consumer="heimdal-capture-watch",
        command=["consumer"],
        keychain_lookup=_lookup(),
        runner=runner,
        directory=tmp_path,
    )

    assert result == return_code
    assert observed_path is not None
    assert not observed_path.exists()


def test_runtime_secret_reader_rejects_unsafe_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secure = tmp_path / "secure.env"
    secure.write_text("OPENAI_API_KEY=" + _OPENAI_KEY + "\n", encoding="utf-8")
    secure.chmod(0o600)
    assert load_runtime_secret_values(
        {HOST_SECRET_RUNTIME_ENV_FILE: str(secure)}
    ) == {"OPENAI_API_KEY": _OPENAI_KEY}

    world_readable = tmp_path / "world-readable.env"
    world_readable.write_text(secure.read_text(encoding="utf-8"), encoding="utf-8")
    world_readable.chmod(0o644)
    assert load_runtime_secret_values(
        {HOST_SECRET_RUNTIME_ENV_FILE: str(world_readable)}
    ) == {}

    symlink = tmp_path / "symlink.env"
    symlink.symlink_to(secure)
    assert load_runtime_secret_values(
        {HOST_SECRET_RUNTIME_ENV_FILE: str(symlink)}
    ) == {}
    assert load_runtime_secret_values(
        {HOST_SECRET_RUNTIME_ENV_FILE: str(tmp_path)}
    ) == {}

    real_uid = os.geteuid()
    monkeypatch.setattr(
        host_secret_bootstrap.os,
        "geteuid",
        lambda: real_uid + 1,
    )
    assert load_runtime_secret_values(
        {HOST_SECRET_RUNTIME_ENV_FILE: str(secure)}
    ) == {}


def test_runtime_secret_reader_rejects_fifo_without_blocking(tmp_path: Path) -> None:
    fifo = tmp_path / "runtime-secret.fifo"
    os.mkfifo(fifo, mode=0o600)
    probe = (
        "import json,sys; "
        "from app.ops.host_secret_bootstrap import "
        "HOST_SECRET_RUNTIME_ENV_FILE,load_runtime_secret_values; "
        "print(json.dumps(load_runtime_secret_values("
        "{HOST_SECRET_RUNTIME_ENV_FILE: sys.argv[1]}), sort_keys=True))"
    )

    result = subprocess.run(
        [sys.executable, "-c", probe, str(fifo)],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=2,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "{}"


def test_sigterm_forwards_to_consumer_and_cleans_runtime_secret_file(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(
        bin_dir / "security",
        f"""#!/usr/bin/env bash
set -eu
printf '%s\\n' '{_RAW_KEY}'
""",
    )
    ready = tmp_path / "consumer-ready"
    observed_path = tmp_path / "observed-path"
    consumer = (
        "import os, pathlib, time; "
        f"pathlib.Path({str(observed_path)!r}).write_text("
        "os.environ['HOST_SECRET_RUNTIME_ENV_FILE'], encoding='utf-8'); "
        f"pathlib.Path({str(ready)!r}).touch(); "
        "time.sleep(60)"
    )
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "app.ops.host_secret_bootstrap",
            "--channel",
            "dev",
            "--consumer",
            "heimdal-capture-watch",
            "--",
            sys.executable,
            "-c",
            consumer,
        ],
        cwd=_REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = time.monotonic() + 10
    while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.05)
    assert ready.exists(), process.communicate(timeout=5)
    secret_file = Path(observed_path.read_text(encoding="utf-8"))
    assert secret_file.is_file()

    process.terminate()
    _stdout, stderr = process.communicate(timeout=10)

    assert process.returncode == 128 + signal.SIGTERM
    assert not secret_file.exists()
    assert _RAW_KEY not in stderr


def test_runtime_secret_is_removed_before_signal_handlers_are_restored(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_path: Path | None = None
    events: list[str] = []

    @contextmanager
    def tracing_handlers(
        handler: host_secret_bootstrap.SignalHandler,
    ) -> Iterator[None]:
        events.append("install-cleanup")
        try:
            yield
        finally:
            events.append("restore-original")
            assert observed_path is not None
            assert not observed_path.exists()
            handler(signal.SIGTERM, None)

    monkeypatch.setattr(
        host_secret_bootstrap,
        "_temporary_signal_handlers",
        tracing_handlers,
    )

    with pytest.raises(HostSecretBootstrapTerminated) as error:
        with materialize_consumer_environment(
            channel="dev",
            consumer="heimdal-capture-watch",
            keychain_lookup=_lookup(),
            directory=tmp_path,
        ) as env_file:
            observed_path = env_file
            assert observed_path.is_file()

    assert error.value.signum == signal.SIGTERM
    assert events == ["install-cleanup", "restore-original"]


def test_signal_during_child_spawn_is_forwarded_after_assignment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SpawnInterruptedProcess:
        def __init__(self) -> None:
            self.returncode: int | None = None
            self.forwarded: list[int] = []

        def poll(self) -> int | None:
            return self.returncode

        def send_signal(self, signum: int) -> None:
            self.forwarded.append(signum)
            self.returncode = -signum

        def wait(self, timeout: float | None = None) -> int:
            del timeout
            assert self.returncode is not None
            return self.returncode

        def kill(self) -> None:
            self.returncode = -signal.SIGKILL

    process = SpawnInterruptedProcess()

    def interrupted_popen(
        _command: list[str],
        *,
        env: dict[str, str],
    ) -> SpawnInterruptedProcess:
        del env
        signal.raise_signal(signal.SIGTERM)
        return process

    monkeypatch.setattr(host_secret_bootstrap.subprocess, "Popen", interrupted_popen)

    with pytest.raises(HostSecretBootstrapTerminated) as error:
        host_secret_bootstrap._subprocess_runner(["consumer"], {})

    assert error.value.signum == signal.SIGTERM
    assert process.forwarded == [signal.SIGTERM]
    assert process.poll() == -signal.SIGTERM


def test_post_kill_reap_timeout_still_returns_to_secret_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class UninterruptibleProcess:
        def __init__(self) -> None:
            self.forwarded: list[int] = []
            self.kills = 0
            self.wait_timeouts: list[float | None] = []

        def poll(self) -> None:
            return None

        def send_signal(self, signum: int) -> None:
            self.forwarded.append(signum)

        def wait(self, timeout: float | None = None) -> int:
            self.wait_timeouts.append(timeout)
            raise subprocess.TimeoutExpired("consumer", timeout)

        def kill(self) -> None:
            self.kills += 1

    process = UninterruptibleProcess()

    def interrupted_popen(
        _command: list[str],
        *,
        env: dict[str, str],
    ) -> UninterruptibleProcess:
        observed_path = Path(env["HOST_SECRET_RUNTIME_ENV_FILE"])
        assert observed_path.is_file()
        signal.raise_signal(signal.SIGTERM)
        return process

    monkeypatch.setattr(host_secret_bootstrap.subprocess, "Popen", interrupted_popen)
    monkeypatch.setattr(
        host_secret_bootstrap,
        "_CHILD_TERMINATION_GRACE_SECONDS",
        0.0,
    )

    with pytest.raises(HostSecretBootstrapTerminated) as error:
        run_with_host_secrets(
            channel="dev",
            consumer="heimdal-capture-watch",
            command=["consumer"],
            keychain_lookup=_lookup(),
            directory=tmp_path,
        )

    assert error.value.signum == signal.SIGTERM
    assert process.forwarded == [signal.SIGTERM]
    assert process.kills == 1
    assert process.wait_timeouts == [
        host_secret_bootstrap._CHILD_POST_KILL_REAP_SECONDS
    ]
    assert list(tmp_path.iterdir()) == []


def test_signal_during_tempfile_creation_defers_until_cleanup_state_is_safe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_mkstemp = host_secret_bootstrap.tempfile.mkstemp

    def interrupted_mkstemp(*args: object, **kwargs: object) -> tuple[int, str]:
        fd, path = real_mkstemp(*args, **kwargs)
        signal.raise_signal(signal.SIGTERM)
        return fd, path

    monkeypatch.setattr(
        host_secret_bootstrap.tempfile,
        "mkstemp",
        interrupted_mkstemp,
    )

    with pytest.raises(HostSecretBootstrapTerminated) as error:
        with materialize_consumer_environment(
            channel="dev",
            consumer="heimdal-capture-watch",
            keychain_lookup=_lookup(),
            directory=tmp_path,
        ):
            pytest.fail("consumer must not launch after deferred termination")

    assert error.value.signum == signal.SIGTERM
    assert list(tmp_path.iterdir()) == []


def test_signal_during_fdopen_transfer_unlinks_and_closes_material(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_fdopen = host_secret_bootstrap.os.fdopen

    def interrupted_fdopen(*args: object, **kwargs: object) -> object:
        handle = real_fdopen(*args, **kwargs)
        signal.raise_signal(signal.SIGTERM)
        return handle

    monkeypatch.setattr(host_secret_bootstrap.os, "fdopen", interrupted_fdopen)

    with pytest.raises(HostSecretBootstrapTerminated) as error:
        with materialize_consumer_environment(
            channel="dev",
            consumer="heimdal-capture-watch",
            keychain_lookup=_lookup(),
            directory=tmp_path,
        ):
            pytest.fail("consumer must not launch after deferred termination")

    assert error.value.signum == signal.SIGTERM
    assert list(tmp_path.iterdir()) == []


def test_fdopen_failure_after_descriptor_close_still_unlinks_material(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_close = host_secret_bootstrap.os.close

    def failed_fdopen_after_close(fd: int, *_args: object, **_kwargs: object) -> object:
        real_close(fd)
        raise OSError("fdopen ownership transfer failed with sensitive context")

    monkeypatch.setattr(
        host_secret_bootstrap.os,
        "fdopen",
        failed_fdopen_after_close,
    )

    with pytest.raises(HostSecretBootstrapError) as error:
        with materialize_consumer_environment(
            channel="dev",
            consumer="heimdal-capture-watch",
            keychain_lookup=_lookup(),
            directory=tmp_path,
        ):
            pytest.fail("consumer must not launch after fdopen failure")

    assert str(error.value) == "host secret bootstrap failed for declared consumer"
    assert "sensitive context" not in str(error.value)
    assert list(tmp_path.iterdir()) == []


def test_repeated_sigterm_kills_and_reaps_ignoring_consumer(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(
        bin_dir / "security",
        f"""#!/usr/bin/env bash
set -eu
printf '%s\\n' '{_RAW_KEY}'
""",
    )
    ready = tmp_path / "ignoring-consumer-ready"
    child_pid_path = tmp_path / "child-pid"
    observed_path = tmp_path / "ignoring-observed-path"
    consumer = (
        "import os, pathlib, signal, time; "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        f"pathlib.Path({str(child_pid_path)!r}).write_text(str(os.getpid()), encoding='utf-8'); "
        f"pathlib.Path({str(observed_path)!r}).write_text("
        "os.environ['HOST_SECRET_RUNTIME_ENV_FILE'], encoding='utf-8'); "
        f"pathlib.Path({str(ready)!r}).touch(); "
        "time.sleep(60)"
    )
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "app.ops.host_secret_bootstrap",
            "--channel",
            "dev",
            "--consumer",
            "heimdal-capture-watch",
            "--",
            sys.executable,
            "-c",
            consumer,
        ],
        cwd=_REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = time.monotonic() + 10
    while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.05)
    assert ready.exists(), process.communicate(timeout=5)
    child_pid = int(child_pid_path.read_text(encoding="utf-8"))
    secret_file = Path(observed_path.read_text(encoding="utf-8"))
    assert secret_file.is_file()

    process.terminate()
    time.sleep(0.1)
    process.terminate()
    _stdout, stderr = process.communicate(timeout=10)

    assert process.returncode == 128 + signal.SIGTERM
    assert not secret_file.exists()
    assert _RAW_KEY not in stderr
    with pytest.raises(ProcessLookupError):
        os.kill(child_pid, 0)


def _write_executable(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)


def test_capture_watch_uses_bootstrap_not_tracked_env(tmp_path: Path) -> None:
    dev_overlay = (_REPO_ROOT / "docker-compose.dev.yml").read_text(encoding="utf-8")
    assert "${HOST_SECRET_RUNTIME_ENV_FILE:-/dev/null}" in dev_overlay
    assert "HEIMDAL_RAW_STORE_KEY: !reset null" in dev_overlay

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    runtime_env = tmp_path / "runtime.env"
    runtime_env.write_text(
        "HEIMDAL_RAW_STORE_KEY=tracked-runtime-value-must-not-win\n",
        encoding="utf-8",
    )
    channel_env = tmp_path / "dev.env"
    channel_env.write_text(
        f"WATCHER_RUNTIME_ENV_FILE={runtime_env}\n",
        encoding="utf-8",
    )
    observed_path_file = tmp_path / "observed-path"
    observed_content_file = tmp_path / "observed-content"
    _write_executable(
        bin_dir / "security",
        f"""#!/usr/bin/env bash
set -eu
printf '%s\\n' '{_RAW_KEY}'
""",
    )
    _write_executable(
        bin_dir / "docker",
        f"""#!/usr/bin/env bash
set -eu
test -n "${{HOST_SECRET_RUNTIME_ENV_FILE:-}}"
test -f "$HOST_SECRET_RUNTIME_ENV_FILE"
python3 -c 'import stat, sys; from pathlib import Path; raise SystemExit(0 if stat.S_IMODE(Path(sys.argv[1]).stat().st_mode) == 0o600 else 1)' "$HOST_SECRET_RUNTIME_ENV_FILE"
printf '%s' "$HOST_SECRET_RUNTIME_ENV_FILE" > {observed_path_file!s}
cp "$HOST_SECRET_RUNTIME_ENV_FILE" {observed_content_file!s}
""",
    )

    command = f"""
set -euo pipefail
source {_REPO_ROOT / 'scripts/lib/deploy_channel_compose.sh'}
PYTHON={sys.executable!s}
deploy_channel_compose \\
  {_REPO_ROOT!s} dev docker-compose.dev.yml pkm-dev-bootstrap-test \\
  {channel_env!s} up -d heimdal-capture-watch
"""
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["HEIMDAL_RAW_STORE_KEY"] = "ambient-value-must-not-win"
    result = subprocess.run(
        ["bash", "-c", command],
        cwd=_REPO_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    secret_file = Path(observed_path_file.read_text(encoding="utf-8"))
    assert observed_content_file.read_text(encoding="utf-8") == (
        f"HEIMDAL_RAW_STORE_KEY={_RAW_KEY}\n"
    )
    assert not secret_file.exists()


# --- Optional declared secrets (#4489) -------------------------------------
#
# The host-secret layer is fail-closed over *every* secret declared for a
# consumer, which is why #4484 could not simply declare the cockpit's GitHub
# token: doing so would make a Keychain item mandatory on dev, test, and prod,
# and a host missing it would lose the Heimdal ingress lanes. `optional` makes
# the required/optional distinction — which
# `docs/LOCAL_SECRET_PROVISIONING/README.md :: Fixed constraints` #3 already
# relies on in prose — something the schema can express. Optionality covers
# *absence* only: a malformed value fails closed exactly as before.


def _absent(*absent_suffixes: str) -> KeychainLookup:
    """Keychain lookup where the named accounts are missing, others resolve."""

    def lookup(_service: str, account: str) -> str:
        for suffix in absent_suffixes:
            if account.endswith(suffix):
                # Mirrors _security_keychain_lookup's non-zero-exit path: the
                # bootstrap cannot tell "no such item" from any other lookup
                # failure, so absence surfaces as this exception.
                raise HostSecretBootstrapError(
                    "host secret bootstrap failed for declared consumer"
                )
        if account.endswith(":heimdal.raw-store-key"):
            return _RAW_KEY
        if account.endswith(":github.token"):
            return _GITHUB_TOKEN
        pytest.fail(f"unexpected account lookup: {account}")

    return lookup


def test_absent_optional_secret_does_not_fail_the_consumer(tmp_path: Path) -> None:
    contract = host_secret_bootstrap.load_host_secret_contract()
    # Guard the *pairing*, not just the code path: without this declaration the
    # assertions below would hold vacuously (nothing would ever look the secret
    # up), so the test would keep passing against a revert of the mechanism.
    contract.require_declared(
        channel="dev", consumer="heimdal-api-ingress", secret="github.token"
    )
    assert contract.is_optional("github.token") is True

    consulted: list[str] = []
    absent = _absent(":github.token")

    def lookup(service: str, account: str) -> str:
        consulted.append(account)
        return absent(service, account)

    with materialize_consumer_environment(
        channel="dev",
        consumer="heimdal-api-ingress",
        keychain_lookup=lookup,
        directory=tmp_path,
    ) as env_file:
        assert env_file.read_text(encoding="utf-8") == f"HEIMDAL_RAW_STORE_KEY={_RAW_KEY}\n"

    assert "dev:heimdal-api-ingress:github.token" in consulted, (
        "the optional secret must actually be attempted and skipped, not simply "
        "absent from the consumer's declared set"
    )


def test_malformed_optional_secret_fails_closed(tmp_path: Path) -> None:
    """Optionality covers absence, never a value that is present and wrong."""

    def lookup(_service: str, account: str) -> str:
        if account.endswith(":github.token"):
            return "short"  # present, but not a valid token value
        return _RAW_KEY

    with pytest.raises(HostSecretBootstrapError):
        with materialize_consumer_environment(
            channel="dev",
            consumer="heimdal-api-ingress",
            keychain_lookup=lookup,
            directory=tmp_path,
        ):
            pytest.fail("a malformed optional secret must not materialize a layer")

    # Nothing was written: the whole consumer fails, so a partially-populated
    # layer can never be handed to the child.
    assert list(tmp_path.iterdir()) == []


def test_optional_secret_failure_never_unlocks_the_run_anyway_handoff(
    tmp_path: Path,
) -> None:
    """An optional secret must not be able to drop a *required* one.

    `run_on_credential_unavailable` launches the command with no layer at all.
    If an optional secret could trigger it, a malformed `github.token` would
    silently de-provision `heimdal.raw-store-key` for the same consumer — a
    fail-*open*. No in-repo caller passes the flag for this consumer today;
    this guards the CLI surface that allows it.
    """
    launched: list[list[str]] = []

    def lookup(_service: str, account: str) -> str:
        if account.endswith(":github.token"):
            return "short"  # present and malformed
        return _RAW_KEY

    with pytest.raises(HostSecretBootstrapError):
        run_with_host_secrets(
            channel="dev",
            consumer="heimdal-api-ingress",
            command=["must-not-start"],
            keychain_lookup=lookup,
            runner=lambda command, _env: launched.append(command) or 0,
            directory=tmp_path,
            run_on_credential_unavailable=True,
        )

    assert launched == [], (
        "a malformed optional secret must not launch the command without the "
        "layer that also carries the consumer's required secret"
    )


def test_absent_required_secret_still_fails_closed(tmp_path: Path) -> None:
    """#4489 must not weaken the guarantee protecting the ingress lanes."""
    with pytest.raises(HostSecretBootstrapError):
        with materialize_consumer_environment(
            channel="dev",
            consumer="heimdal-api-ingress",
            keychain_lookup=_absent(":heimdal.raw-store-key"),
            directory=tmp_path,
        ):
            pytest.fail("an absent required secret must not materialize a layer")


def test_every_committed_secret_declares_its_optionality_explicitly() -> None:
    """No implicit default: the closed schema stays closed.

    Asserting `isinstance(..., bool)` would be vacuous — `is_optional` returns a
    membership test. The real guarantee is that the *loader* refuses a
    declaration that omits `optional` or states it as anything but a JSON
    boolean, so silence can never be read as "required" by accident.
    """
    contract = host_secret_bootstrap.load_host_secret_contract()
    # Everything that existed before #4489 stays required.
    for logical_id in ("heimdal.raw-store-key", "openai.api-key", "anthropic.api-key"):
        assert contract.is_optional(logical_id) is False
    assert contract.is_optional("github.token") is True


@pytest.mark.parametrize(
    ("optional_value", "expected"),
    [
        # An omitted key is caught by the closed field set; a present non-bool
        # by the explicit type check. `match=` pins WHICH rule fires, so a
        # revert cannot make these pass for the wrong reason (on a tree without
        # `optional` in _SECRET_FIELDS the non-bool cases would otherwise be
        # rejected as an unknown extra key).
        pytest.param(..., "invalid host secret declaration", id="omitted"),
        pytest.param(1, "invalid host secret identifier", id="truthy-int"),
        pytest.param(0, "invalid host secret identifier", id="falsy-int"),
        pytest.param("true", "invalid host secret identifier", id="string"),
        pytest.param(None, "invalid host secret identifier", id="null"),
        pytest.param([], "invalid host secret identifier", id="list"),
    ],
)
def test_loader_rejects_a_declaration_without_an_explicit_boolean_optional(
    tmp_path: Path, optional_value: object, expected: str
) -> None:
    payload = json.loads(
        (_REPO_ROOT / "config/secrets/host_secret_contract.json").read_text(
            encoding="utf-8"
        )
    )
    if optional_value is ...:
        del payload["secrets"][0]["optional"]
    else:
        payload["secrets"][0]["optional"] = optional_value
    path = tmp_path / "host_secret_contract.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match=expected):
        host_secret_bootstrap.load_host_secret_contract(path)
