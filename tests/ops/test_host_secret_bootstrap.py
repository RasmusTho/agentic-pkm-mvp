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
    HOST_SECRET_BOOTSTRAP_CHANNEL,
    HOST_SECRET_BOOTSTRAP_CONSUMER,
    HOST_SECRET_BOOTSTRAP_FAILURE_REF,
    HOST_SECRET_RUNTIME_ENV_FILE,
    HostSecretBootstrapError,
    HostSecretBootstrapTerminated,
    HostSecretSharedDomainDivergenceError,
    KeychainLookup,
    materialize_consumer_environment,
    load_runtime_secret_values,
    run_with_host_secrets,
)


_RAW_KEY = "a" * 64
_OPENAI_KEY = "openai-key-" + ("o" * 32)
_ANTHROPIC_KEY = "anthropic-key-" + ("a" * 32)
_GITHUB_TOKEN = "ghp_" + ("g" * 36)
_ARCHIVE_PASS = "fixture-archive-passphrase"
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _lookup(value: str = _RAW_KEY) -> KeychainLookup:
    return lambda _service, _account: value


@pytest.mark.parametrize("channel", ["dev", "test", "prod"])
def test_archive_consumer_gets_only_private_temporary_passphrase(
    tmp_path: Path,
    channel: str,
) -> None:
    observed_path: Path | None = None
    requested: list[str] = []

    def lookup(_service: str, account: str) -> str:
        requested.append(account)
        return _ARCHIVE_PASS

    def runner(command: list[str], env: dict[str, str]) -> int:
        nonlocal observed_path
        assert command == ["archive-operation"]
        assert "HEIMDAL_ARCHIVE_PASS" not in env
        assert env[HOST_SECRET_BOOTSTRAP_CHANNEL] == channel
        assert env[HOST_SECRET_BOOTSTRAP_CONSUMER] == "heimdal-cold-volume"
        observed_path = Path(env[HOST_SECRET_RUNTIME_ENV_FILE])
        assert stat.S_IMODE(observed_path.stat().st_mode) == 0o600
        assert observed_path.read_text(encoding="utf-8") == (
            f"HEIMDAL_ARCHIVE_PASS={_ARCHIVE_PASS}\n"
        )
        return 0

    result = run_with_host_secrets(
        channel=channel,
        consumer="heimdal-cold-volume",
        command=["archive-operation"],
        keychain_lookup=lookup,
        runner=runner,
        directory=tmp_path,
    )

    assert result == 0
    assert observed_path is not None and not observed_path.exists()
    assert requested == [f"{channel}:heimdal-cold-volume:heimdal.archive-pass"]


@pytest.mark.parametrize("value", ["short", "x" * 513, "contains\nnewline"])
def test_archive_passphrase_rejects_malformed_value_without_launch_or_disclosure(
    tmp_path: Path,
    value: str,
) -> None:
    launched = False

    def runner(_command: list[str], _env: dict[str, str]) -> int:
        nonlocal launched
        launched = True
        return 0

    with pytest.raises(HostSecretBootstrapError) as error:
        run_with_host_secrets(
            channel="prod",
            consumer="heimdal-cold-volume",
            command=["never-start"],
            keychain_lookup=_lookup(value),
            runner=runner,
            directory=tmp_path,
        )

    assert not launched
    assert value not in str(error.value)
    assert list(tmp_path.iterdir()) == []


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

    # heimdal.raw-store-key is shared-domain (#4512): resolving it for one
    # consumer also looks up the other declared consumers' accounts on the same
    # channel to compare digests, so all accounts are requested even though
    # only the requested consumer's value is materialized.
    assert requested == [
        (
            "yggdrasil.host-secrets",
            "dev:heimdal-capture-watch:heimdal.raw-store-key",
        ),
        (
            "yggdrasil.host-secrets",
            "dev:heimdal-api-ingress:heimdal.raw-store-key",
        ),
        (
            "yggdrasil.host-secrets",
            "dev:heimdal-raw-migrate:heimdal.raw-store-key",
        ),
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

    def lookup(_service: str, _account: str) -> str:
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

    def lookup(_service: str, _account: str) -> str:
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
        keychain_only_secrets=contract.keychain_only_secrets,
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
        pytest.fail(f"unexpected account lookup: {account}")

    observed_path: Path | None = None

    def runner(_command: list[str], env: dict[str, str]) -> int:
        nonlocal observed_path
        observed_path = Path(env["HOST_SECRET_RUNTIME_ENV_FILE"])
        assert set(env).isdisjoint({"OPENAI_API_KEY", "ANTHROPIC_API_KEY", "HEIMDAL_RAW_STORE_KEY"})
        assert observed_path.read_text(encoding="utf-8") == (
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
        "dev:builderops-model-inquiry:openai.api-key",
    ]
    assert observed_path is not None and not observed_path.exists()


def test_model_provider_secret_is_never_disclosed(tmp_path: Path) -> None:
    leaked_value = "model-provider-secret-" + ("z" * 32)

    def lookup(_service: str, _account: str) -> str:
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
            "--provider",
            "keychain",
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
            "--provider",
            "keychain",
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
    # #4362: the HOST_SECRET_RUNTIME_ENV_FILE env_file layer now lives in the
    # base compose file so every channel inherits it deterministically, not
    # only dev (see tests/deploy/test_deploy_channel_script.py ::
    # test_heimdal_capture_watch_host_secret_layer_lives_in_base_compose).
    # The dev overlay still guards against a stray HEIMDAL_RAW_STORE_KEY
    # reaching the service through any other channel.
    base_compose = (_REPO_ROOT / "docker-compose.yaml").read_text(encoding="utf-8")
    dev_overlay = (_REPO_ROOT / "docker-compose.dev.yml").read_text(encoding="utf-8")
    assert "${HOST_SECRET_RUNTIME_ENV_FILE:-/dev/null}" in base_compose
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
    env["HOST_SECRET_PROVIDER"] = "keychain"
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


# --- Shared-domain divergence check (#4512) ---------------------------------
#
# `heimdal.raw-store-key` feeds one AES-256-GCM cipher domain from three
# independently bootstrapped consumers (capture, API ingress, and one-shot
# migration). These tests prove the production bootstrap entrypoint
# (`run_with_host_secrets`, and `main` below it) refuses rather than
# proceeding into a split cipher domain, that matching material bootstraps
# byte-for-byte unchanged, and that the check never discloses either value.

_SIBLING_RAW_KEY = "b" * 64


def _divergent_raw_store_key_lookup(
    *,
    primary: str = _RAW_KEY,
    sibling: str = _SIBLING_RAW_KEY,
) -> KeychainLookup:
    def lookup(_service: str, account: str) -> str:
        if account.endswith(":heimdal-api-ingress:heimdal.raw-store-key"):
            return sibling
        if account.endswith(":heimdal-raw-migrate:heimdal.raw-store-key"):
            return primary
        if account.endswith(":heimdal-capture-watch:heimdal.raw-store-key"):
            return primary
        pytest.fail(f"unexpected account lookup: {account}")

    return lookup


@pytest.mark.parametrize("channel", ["dev", "test", "prod"])
def test_migration_consumer_bootstraps_shared_key_for_every_channel(
    tmp_path: Path,
    channel: str,
) -> None:
    """The production bootstrap grants the one-shot consumer on every lane."""
    requested_accounts: list[str] = []
    observed_path: Path | None = None

    def lookup(_service: str, account: str) -> str:
        requested_accounts.append(account)
        return _RAW_KEY

    def runner(command: list[str], env: dict[str, str]) -> int:
        nonlocal observed_path
        assert command == ["migration-one-shot"]
        assert "HEIMDAL_RAW_STORE_KEY" not in env
        observed_path = Path(env[HOST_SECRET_RUNTIME_ENV_FILE])
        assert observed_path.read_text(encoding="utf-8") == (
            f"HEIMDAL_RAW_STORE_KEY={_RAW_KEY}\n"
        )
        return 0

    result = run_with_host_secrets(
        channel=channel,
        consumer="heimdal-raw-migrate",
        command=["migration-one-shot"],
        keychain_lookup=lookup,
        runner=runner,
        directory=tmp_path,
    )

    assert result == 0
    assert observed_path is not None and not observed_path.exists()
    assert requested_accounts == [
        f"{channel}:heimdal-raw-migrate:heimdal.raw-store-key",
        f"{channel}:heimdal-api-ingress:heimdal.raw-store-key",
        f"{channel}:heimdal-capture-watch:heimdal.raw-store-key",
    ]


@pytest.mark.parametrize("channel", ["dev", "test", "prod"])
@pytest.mark.parametrize("failure", ["missing", "malformed", "divergent"])
def test_migration_consumer_refuses_secret_failure_without_launch_or_disclosure(
    tmp_path: Path,
    channel: str,
    failure: str,
) -> None:
    """Every governed lane fails before migration on unusable key authority."""
    launched = False
    unavailable_detail = "private-lookup-detail"
    malformed_value = "private-malformed-material"

    def lookup(_service: str, account: str) -> str:
        if account.endswith(":heimdal-raw-migrate:heimdal.raw-store-key"):
            if failure == "missing":
                raise OSError(unavailable_detail)
            if failure == "malformed":
                return malformed_value
            return _RAW_KEY
        if account.endswith(":heimdal-api-ingress:heimdal.raw-store-key"):
            return _SIBLING_RAW_KEY if failure == "divergent" else _RAW_KEY
        if account.endswith(":heimdal-capture-watch:heimdal.raw-store-key"):
            return _RAW_KEY
        pytest.fail("unexpected account class")

    def runner(_command: list[str], _env: dict[str, str]) -> int:
        nonlocal launched
        launched = True
        return 0

    with pytest.raises(HostSecretBootstrapError) as error:
        run_with_host_secrets(
            channel=channel,
            consumer="heimdal-raw-migrate",
            command=["migration-must-not-start"],
            keychain_lookup=lookup,
            runner=runner,
            directory=tmp_path,
        )

    message = str(error.value)
    assert not launched
    assert list(tmp_path.iterdir()) == []
    assert unavailable_detail not in message
    assert malformed_value not in message
    assert _RAW_KEY not in message
    assert _SIBLING_RAW_KEY not in message
    assert f"{channel}:heimdal-raw-migrate" not in message


def test_divergent_shared_domain_secret_fails_loud(tmp_path: Path) -> None:
    launched = False

    def runner(_command: list[str], _env: dict[str, str]) -> int:
        nonlocal launched
        launched = True
        return 0

    with pytest.raises(HostSecretSharedDomainDivergenceError) as error:
        run_with_host_secrets(
            channel="dev",
            consumer="heimdal-capture-watch",
            command=["never-start"],
            keychain_lookup=_divergent_raw_store_key_lookup(),
            runner=runner,
            directory=tmp_path,
        )

    assert not launched
    message = str(error.value)
    assert "heimdal.raw-store-key" in message
    assert _RAW_KEY not in message
    assert _SIBLING_RAW_KEY not in message
    assert list(tmp_path.iterdir()) == []


def test_matching_shared_domain_secret_bootstraps_unchanged(tmp_path: Path) -> None:
    """Identical material across all consumers bootstraps unchanged."""
    observed_path: Path | None = None

    def runner(_command: list[str], env: dict[str, str]) -> int:
        nonlocal observed_path
        observed_path = Path(env["HOST_SECRET_RUNTIME_ENV_FILE"])
        assert observed_path.read_text(encoding="utf-8") == f"HEIMDAL_RAW_STORE_KEY={_RAW_KEY}\n"
        return 0

    result = run_with_host_secrets(
        channel="dev",
        consumer="heimdal-capture-watch",
        command=["consumer"],
        keychain_lookup=_divergent_raw_store_key_lookup(sibling=_RAW_KEY),
        runner=runner,
        directory=tmp_path,
    )

    assert result == 0
    assert observed_path is not None and not observed_path.exists()


def test_shared_domain_agreement_is_hex_case_insensitive(tmp_path: Path) -> None:
    """Two hex-case spellings of the same raw-store key must not read as diverged.

    `raw-store-key` values are decoded with `bytes.fromhex` before use
    (`app/heimdal/raw_store.py`), so `"a" * 64` and `"A" * 64` are the same key
    material. Comparing the raw text would false-positive here and brick both
    consumers on an otherwise correctly provisioned host.
    """
    observed_path: Path | None = None

    def runner(_command: list[str], env: dict[str, str]) -> int:
        nonlocal observed_path
        observed_path = Path(env["HOST_SECRET_RUNTIME_ENV_FILE"])
        return 0

    result = run_with_host_secrets(
        channel="dev",
        consumer="heimdal-capture-watch",
        command=["consumer"],
        keychain_lookup=_divergent_raw_store_key_lookup(sibling=_RAW_KEY.upper()),
        runner=runner,
        directory=tmp_path,
    )

    assert result == 0
    assert observed_path is not None and not observed_path.exists()


def test_sibling_lookup_programming_error_still_fails_closed(tmp_path: Path) -> None:
    """The sibling-skip path only tolerates the typed bootstrap failure.

    An unexpected error from a `keychain_lookup` implementation (a signature
    mismatch, a decode bug) must not be swallowed as "sibling unresolvable" —
    that would silently disable the divergence check. Only
    `HostSecretBootstrapError`, the failure every in-repo `keychain_lookup`
    raises for a genuinely unresolvable item, is tolerated; anything else
    reaches the outer handler and fails this consumer closed.
    """
    launched = False

    def runner(_command: list[str], _env: dict[str, str]) -> int:
        nonlocal launched
        launched = True
        return 0

    def lookup(_service: str, account: str) -> str:
        if account.endswith(":heimdal-api-ingress:heimdal.raw-store-key"):
            raise TypeError("unexpected programming error, not a bootstrap failure")
        return _RAW_KEY

    with pytest.raises(HostSecretBootstrapError) as error:
        run_with_host_secrets(
            channel="dev",
            consumer="heimdal-capture-watch",
            command=["never-start"],
            keychain_lookup=lookup,
            runner=runner,
            directory=tmp_path,
        )

    assert not isinstance(error.value, HostSecretSharedDomainDivergenceError)
    assert not launched
    assert list(tmp_path.iterdir()) == []


def test_sibling_lookup_bootstrap_failure_is_tolerated_as_skip(tmp_path: Path) -> None:
    """A sibling's typed, unresolvable-item failure is skipped, not fatal."""
    observed_path: Path | None = None

    def runner(_command: list[str], env: dict[str, str]) -> int:
        nonlocal observed_path
        observed_path = Path(env["HOST_SECRET_RUNTIME_ENV_FILE"])
        return 0

    def lookup(_service: str, account: str) -> str:
        if account.endswith(":heimdal-api-ingress:heimdal.raw-store-key"):
            raise HostSecretBootstrapError(
                "host secret bootstrap failed for declared consumer"
            )
        return _RAW_KEY

    result = run_with_host_secrets(
        channel="dev",
        consumer="heimdal-capture-watch",
        command=["consumer"],
        keychain_lookup=lookup,
        runner=runner,
        directory=tmp_path,
    )

    assert result == 0
    assert observed_path is not None and not observed_path.exists()


def test_non_shared_domain_secret_with_two_consumers_skips_sibling_lookup(
    tmp_path: Path,
) -> None:
    """`openai.api-key` is declared by two consumers but is not shared-domain.

    `builderops-model-inquiry` and `builderops-ckm-semantic` both declare
    `openai.api-key`, proving the sibling-lookup machinery is gated on
    `shared_key_domain`, not merely on "more than one declared consumer".
    """
    requested_accounts: list[str] = []

    def lookup(_service: str, account: str) -> str:
        requested_accounts.append(account)
        if account == "dev:builderops-ckm-semantic:openai.api-key":
            return _OPENAI_KEY
        pytest.fail(f"unexpected account lookup: {account}")

    result = run_with_host_secrets(
        channel="dev",
        consumer="builderops-ckm-semantic",
        command=["consumer"],
        keychain_lookup=lookup,
        runner=lambda _command, _env: 0,
        directory=tmp_path,
    )

    assert result == 0
    assert requested_accounts == ["dev:builderops-ckm-semantic:openai.api-key"]


def test_shared_domain_check_never_logs_key_material(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # `main` resolves through the real default `_security_keychain_lookup`,
    # bound as a parameter default at function-definition time, so patching
    # the module attribute would not reach it. `raw-store-key` accounts take
    # the `security` CLI subprocess path (never the framework path), so patch
    # that call site instead — same technique already used by
    # `test_capture_watch_uses_bootstrap_not_tracked_env` via a fake `security`
    # binary, done here via `subprocess.run` directly to stay in-process.
    lookup = _divergent_raw_store_key_lookup()

    class _FakeCompletedProcess:
        def __init__(self, stdout: str) -> None:
            self.returncode = 0
            self.stdout = stdout

    def fake_run(command: list[str], **_kwargs: object) -> _FakeCompletedProcess:
        account = command[command.index("-a") + 1]
        return _FakeCompletedProcess(lookup("yggdrasil.host-secrets", account) + "\n")

    monkeypatch.setattr(host_secret_bootstrap.subprocess, "run", fake_run)

    exit_code = host_secret_bootstrap.main(
        ["--provider", "keychain", "--channel", "dev", "--consumer", "heimdal-capture-watch", "--", "never-start"]
    )

    assert exit_code == 78
    captured = capsys.readouterr()
    for stream in (captured.out, captured.err):
        assert _RAW_KEY not in stream
        assert _SIBLING_RAW_KEY not in stream
        assert "heimdal-capture-watch:heimdal.raw-store-key" not in stream
        assert "heimdal-api-ingress:heimdal.raw-store-key" not in stream
        assert "heimdal-raw-migrate:heimdal.raw-store-key" not in stream
    assert "heimdal.raw-store-key" in captured.err


# BWS fake transport reaches the real SDK-shaped reader and shared controller.
from types import SimpleNamespace
from app.ops.bws_secret_reader import BwsReaderConfig, BwsSecretReader
from app.ops.host_secret_controller import (
    HostSecretAdmissionError,
    HostSecretController,
    TerminalEvidence,
)
from app.ops.host_secret_bootstrap import resolve_host_secret_values

_BWS_NON_PROD_PROJECT = "00000000-0000-4000-8000-000000000001"
_BWS_ORG = "00000000-0000-4000-8000-000000000002"
_BWS_ITEM = "00000000-0000-4000-8000-000000000003"
_BWS_PROD_PROJECT = "00000000-0000-4000-8000-000000000004"
_BWS_PEER_ITEM = "00000000-0000-4000-8000-000000000005"
_BWS_NONCANONICAL_PROJECT_ID = "ABCDEFAB-CDEF-4ABC-8ABC-ABCDEFABCDEF"
_BWS_PROJECT_IDS = {
    "non-prod": _BWS_NON_PROD_PROJECT,
    "prod": _BWS_PROD_PROJECT,
}


class _BwsClient:
    def __init__(
        self,
        project: str = "non-prod",
        identity: str = "shared/openai.api-key",
        value: str = _OPENAI_KEY,
    ) -> None:
        self.project, self.identity, self.value = project, identity, value
        self.calls: list[tuple[str, str | None]] = []
        self.missing = False
        self.wrong_response_project = False
        self.failure = False
        self.wrong_project_organization = False
        self.wrong_project_id = False
        self.wrong_peer_project_organization = False
        self.missing_selected_project = False
        self.missing_peer_project = False
        self.unexpected_project = False
        self.duplicate_project_name = False
        self.duplicate_project_id = False
        self.peer_project_id_fault: str | None = None
        self.include_peer_project_item = False
        self.duplicate_item = False
        self.wrong_item_organization = False
        self.wrong_item_project_ids = False
        self.wrong_item_key = False
        self.wrong_response_id = False
        self.wrong_response_key = False

    def auth(self):
        return self

    def login_access_token(self, token, state_file):
        assert token == "fixture-machine-token"
        assert state_file is None
        self.calls.append(("login", None))
        if self.failure:
            raise RuntimeError(self.value)
        return SimpleNamespace(success=True, data=SimpleNamespace(authenticated=True))

    def projects(self):
        return SimpleNamespace(list=self.list_projects)

    def list_projects(self, organization_id):
        self.calls.append(("projects", organization_id))
        peer_project = "prod" if self.project == "non-prod" else "non-prod"
        selected_project_id = _BWS_PROJECT_IDS[self.project]
        if self.wrong_project_id:
            selected_project_id = "00000000-0000-4000-8000-000000000099"
        selected_organization = (
            "00000000-0000-4000-8000-000000000098"
            if self.wrong_project_organization else _BWS_ORG
        )
        peer_organization = (
            "00000000-0000-4000-8000-000000000098"
            if self.wrong_peer_project_organization else _BWS_ORG
        )
        peer_project_id = _BWS_PROJECT_IDS[peer_project]
        if self.peer_project_id_fault == "malformed":
            peer_project_id = "not-a-uuid"
        elif self.peer_project_id_fault == "noncanonical":
            peer_project_id = _BWS_NONCANONICAL_PROJECT_ID
        peer_name = self.project if self.duplicate_project_name else peer_project
        if self.duplicate_project_id:
            peer_project_id = selected_project_id
        records = [
            SimpleNamespace(
                id=selected_project_id,
                name=self.project,
                organization_id=selected_organization,
            ),
            SimpleNamespace(
                id=peer_project_id,
                name=peer_name,
                organization_id=peer_organization,
            ),
        ]
        if self.missing_selected_project:
            records = [records[1]]
        elif self.missing_peer_project:
            records = [records[0]]
        if self.unexpected_project:
            records.append(
                SimpleNamespace(
                    id="00000000-0000-4000-8000-000000000099",
                    name="unexpected",
                    organization_id=_BWS_ORG,
                )
            )
        self.listed_project_count = len(records)
        return SimpleNamespace(
            success=True,
            data=SimpleNamespace(data=records),
        )

    def secrets(self):
        return SimpleNamespace(list=self.list_secrets, get=self.get)

    def list_secrets(self, organization_id):
        self.calls.append(("list", organization_id))
        item = SimpleNamespace(
            id=_BWS_ITEM,
            key="wrong/key" if self.wrong_item_key else self.identity,
            organization_id=(
                "00000000-0000-4000-8000-000000000097"
                if self.wrong_item_organization else _BWS_ORG
            ),
            project_ids=(
                ["00000000-0000-4000-8000-000000000096"]
                if self.wrong_item_project_ids else [_BWS_PROJECT_IDS[self.project]]
            ),
        )
        items = [] if self.missing else [item]
        if self.include_peer_project_item:
            peer_project = "prod" if self.project == "non-prod" else "non-prod"
            peer_identity = (
                "prod/heimdal.raw-store-key"
                if peer_project == "prod" else "dev/postgres.password"
            )
            items.append(
                SimpleNamespace(
                    id=_BWS_PEER_ITEM,
                    key=peer_identity,
                    organization_id=_BWS_ORG,
                    project_ids=[_BWS_PROJECT_IDS[peer_project]],
                )
            )
        if self.duplicate_item:
            items.append(item)
        return SimpleNamespace(
            success=True,
            data=SimpleNamespace(data=items),
        )

    def get(self, identity):
        self.calls.append(("get", identity))
        return SimpleNamespace(
            success=True,
            data=SimpleNamespace(
                id=("00000000-0000-4000-8000-000000000095" if self.wrong_response_id else _BWS_ITEM),
                key=("wrong/key" if self.wrong_response_key else self.identity),
                organization_id=_BWS_ORG,
                project_id=(
                    "wrong" if self.wrong_response_project
                    else _BWS_PROJECT_IDS[self.project]
                ),
                value=self.value,
            ),
        )


def _bws_fixture(
    tmp_path, *, project="non-prod", identity="shared/openai.api-key", value=_OPENAI_KEY
):
    credentials = tmp_path / "credentials"
    credentials.mkdir()
    token = credentials / "bws-machine-account-token"
    token.write_text("fixture-machine-token")
    token.chmod(0o400)
    client = _BwsClient(project, identity, value)
    reader = BwsSecretReader(
        BwsReaderConfig(project, _BWS_PROJECT_IDS[project], _BWS_ORG, credentials, token),
        client_factory=lambda: client,
    )
    return reader, client, HostSecretController(tmp_path / "controller")


@pytest.mark.parametrize(
    "channel,consumer,project,identity,value",
    [
        ("dev", "builderops-model-inquiry", "non-prod", "shared/openai.api-key", _OPENAI_KEY),
        ("test", "builderops-model-inquiry", "non-prod", "shared/openai.api-key", _OPENAI_KEY),
        ("prod", "heimdal-capture-watch", "prod", "prod/heimdal.raw-store-key", _RAW_KEY),
        ("dev", "postgres-api", "non-prod", "dev/postgres.password", "fixture-postgres-password"),
    ],
)
def test_bws_lookup_uses_scoped_active_identity(
    tmp_path, capsys, caplog, channel, consumer, project, identity, value
):
    reader, client, controller = _bws_fixture(
        tmp_path, project=project, identity=identity, value=value
    )
    resolved = resolve_host_secret_values(
        channel=channel, consumer=consumer, provider="bws", bws_reader=reader, controller=controller
    )
    assert resolved == {identity.split("/", 1)[1]: value}
    assert client.calls == [
        ("login", None),
        ("projects", _BWS_ORG),
        ("list", _BWS_ORG),
        ("get", _BWS_ITEM),
    ]
    assert value not in capsys.readouterr().out + caplog.text
    assert value not in (controller.directory / "operations.jsonl").read_text()
    assert "fixture-machine-token" not in (controller.directory / "operations.jsonl").read_text()


def test_bws_lookup_accepts_both_projects_and_fetches_only_selected_item(
    tmp_path, capsys, caplog
):
    value = "fixture-selected-project-password"
    reader, client, controller = _bws_fixture(
        tmp_path,
        project="non-prod",
        identity="dev/postgres.password",
        value=value,
    )
    client.include_peer_project_item = True

    resolved = resolve_host_secret_values(
        channel="dev",
        consumer="postgres-api",
        provider="bws",
        bws_reader=reader,
        controller=controller,
    )

    assert resolved == {"postgres.password": value}
    assert client.listed_project_count == 2
    assert client.calls == [
        ("login", None),
        ("projects", _BWS_ORG),
        ("list", _BWS_ORG),
        ("get", _BWS_ITEM),
    ]
    assert not any(call == ("get", _BWS_PEER_ITEM) for call in client.calls)
    diagnostics = capsys.readouterr().out + caplog.text
    assert value not in diagnostics
    journal = (controller.directory / "operations.jsonl").read_text()
    assert value not in journal and "fixture-machine-token" not in journal


@pytest.mark.parametrize(
    "fault",
    [
        "missing-selected-project",
        "missing-peer-project",
        "wrong-selected-project-organization",
        "wrong-peer-project-organization",
        "wrong-selected-project-id",
        "malformed-peer-project-id",
        "noncanonical-peer-project-id",
        "unexpected-project",
        "duplicate-project-name",
        "duplicate-project-id",
    ],
)
def test_bws_lookup_rejects_invalid_multi_project_scope(
    tmp_path, capsys, caplog, fault
):
    reader, client, controller = _bws_fixture(tmp_path)
    client.missing_selected_project = fault == "missing-selected-project"
    client.missing_peer_project = fault == "missing-peer-project"
    client.wrong_project_organization = (
        fault == "wrong-selected-project-organization"
    )
    client.wrong_peer_project_organization = (
        fault == "wrong-peer-project-organization"
    )
    client.wrong_project_id = fault == "wrong-selected-project-id"
    if fault == "malformed-peer-project-id":
        client.peer_project_id_fault = "malformed"
    elif fault == "noncanonical-peer-project-id":
        client.peer_project_id_fault = "noncanonical"
    client.unexpected_project = fault == "unexpected-project"
    client.duplicate_project_name = fault == "duplicate-project-name"
    client.duplicate_project_id = fault == "duplicate-project-id"

    with pytest.raises(HostSecretBootstrapError):
        resolve_host_secret_values(
            channel="dev",
            consumer="builderops-model-inquiry",
            provider="bws",
            bws_reader=reader,
            controller=controller,
        )

    assert client.calls == [("login", None), ("projects", _BWS_ORG)]
    diagnostics = capsys.readouterr().out + caplog.text
    assert _OPENAI_KEY not in diagnostics
    assert "fixture-machine-token" not in diagnostics
    journal = (controller.directory / "operations.jsonl").read_text()
    assert _OPENAI_KEY not in journal and "fixture-machine-token" not in journal


def test_typesafe_bws_lookup_uses_non_prod_project_and_reader_token(
    tmp_path, monkeypatch, capsys, caplog
):
    monkeypatch.setattr(host_secret_bootstrap.sys, "platform", "darwin")
    provider_key = "fixture-typesafe-provider-key"
    client = _BwsClient("non-prod", "dev/typesafe.api-key", provider_key)
    token_calls = []

    def keychain_lookup(service, account):
        token_calls.append((service, account))
        return "fixture-machine-token"

    reader = host_secret_bootstrap.create_marr_typesafe_bws_reader(
        environment={
            "BWS_READER_PROJECT": "non-prod",
            "BWS_PROJECT_ID": _BWS_NON_PROD_PROJECT,
            "BWS_ORGANIZATION_ID": _BWS_ORG,
        },
        keychain_lookup=keychain_lookup,
        client_factory=lambda: client,
    )
    controller = HostSecretController(tmp_path / "controller")
    assert resolve_host_secret_values(
        channel="dev",
        consumer="marr-server-dev",
        provider="bws",
        bws_reader=reader,
        controller=controller,
    ) == {"typesafe.api-key": provider_key}

    assert token_calls == [
        ("yggdrasil.bws-reader", "non-prod-reader.token")
    ]
    assert client.calls == [
        ("login", None),
        ("projects", _BWS_ORG),
        ("list", _BWS_ORG),
        ("get", _BWS_ITEM),
    ]
    journal = (controller.directory / "operations.jsonl").read_text()
    assert provider_key not in journal and "fixture-machine-token" not in journal
    diagnostics = capsys.readouterr().out + caplog.text
    assert provider_key not in diagnostics and "fixture-machine-token" not in diagnostics


@pytest.mark.parametrize(
    "fault",
    [
        "malformed-token",
        "wrong-project-organization",
        "wrong-project-id",
        "missing-item",
        "duplicate-item",
        "wrong-item-organization",
        "wrong-item-project-ids",
        "wrong-item-key",
        "wrong-response-id",
        "wrong-response-key",
        "wrong-response-project",
    ],
)
def test_marr_typesafe_reader_rejects_exact_binding_adverse_cases_without_disclosure(
    tmp_path, monkeypatch, capsys, caplog, fault
):
    monkeypatch.setattr(host_secret_bootstrap.sys, "platform", "darwin")
    provider_key = "fixture-typesafe-provider-key"
    client = _BwsClient("non-prod", "dev/typesafe.api-key", provider_key)
    if fault == "wrong-project-organization":
        client.wrong_project_organization = True
    elif fault == "wrong-project-id":
        client.wrong_project_id = True
    elif fault == "missing-item":
        client.missing = True
    elif fault == "duplicate-item":
        client.duplicate_item = True
    elif fault == "wrong-item-organization":
        client.wrong_item_organization = True
    elif fault == "wrong-item-project-ids":
        client.wrong_item_project_ids = True
    elif fault == "wrong-item-key":
        client.wrong_item_key = True
    elif fault == "wrong-response-id":
        client.wrong_response_id = True
    elif fault == "wrong-response-key":
        client.wrong_response_key = True
    elif fault == "wrong-response-project":
        client.wrong_response_project = True
    token_calls = []
    client_factory_calls = []

    def keychain_lookup(service, account):
        token_calls.append((service, account))
        return "malformed token" if fault == "malformed-token" else "fixture-machine-token"

    def client_factory():
        client_factory_calls.append(True)
        return client

    with pytest.raises(host_secret_bootstrap.HostSecretBootstrapError):
        reader = host_secret_bootstrap.create_marr_typesafe_bws_reader(
            environment={
                "BWS_READER_PROJECT": "non-prod",
                "BWS_PROJECT_ID": _BWS_NON_PROD_PROJECT,
                "BWS_ORGANIZATION_ID": _BWS_ORG,
            },
            keychain_lookup=keychain_lookup,
            client_factory=client_factory,
        )
        resolve_host_secret_values(
            channel="dev",
            consumer="marr-server-dev",
            provider="bws",
            bws_reader=reader,
            controller=HostSecretController(tmp_path / "controller"),
        )
    assert token_calls == [("yggdrasil.bws-reader", "non-prod-reader.token")]
    assert bool(client_factory_calls) is (fault != "malformed-token")
    diagnostics = capsys.readouterr().out + caplog.text
    assert provider_key not in diagnostics and "malformed token" not in diagnostics


@pytest.mark.parametrize(
    "environment",
    [
        {},
        {
            "BWS_READER_PROJECT": "non-prod",
            "BWS_PROJECT_ID": _BWS_NON_PROD_PROJECT,
            "BWS_ORGANIZATION_ID": _BWS_ORG,
            "BWS_ACCESS_TOKEN_FILE": "/forbidden/token-file",
        },
        {
            "BWS_READER_PROJECT": "prod",
            "BWS_PROJECT_ID": _BWS_PROD_PROJECT,
            "BWS_ORGANIZATION_ID": _BWS_ORG,
        },
    ],
)
def test_typesafe_bws_lookup_fails_closed_before_provider_dispatch(
    tmp_path, monkeypatch, environment
):
    monkeypatch.setattr(host_secret_bootstrap.sys, "platform", "darwin")
    client_factory_calls = []
    token_calls = []

    def keychain_lookup(service, account):
        token_calls.append((service, account))
        return "fixture-machine-token"

    def client_factory():
        client_factory_calls.append(True)
        return _BwsClient("non-prod", "dev/typesafe.api-key", "fixture-provider-key")

    with pytest.raises(host_secret_bootstrap.HostSecretBootstrapError):
        reader = host_secret_bootstrap.create_marr_typesafe_bws_reader(
            environment=environment,
            keychain_lookup=keychain_lookup,
            client_factory=client_factory,
        )
        resolve_host_secret_values(
            channel="dev",
            consumer="marr-server-dev",
            provider="bws",
            bws_reader=reader,
            controller=HostSecretController(tmp_path / "controller"),
        )
    assert token_calls == []
    assert client_factory_calls == []


@pytest.mark.parametrize(
    "fault",
    [
        "provider",
        "scope",
        "missing",
        "malformed",
        "failure",
        "response-project",
        "undeclared",
        "bad-channel",
    ],
)
def test_bws_backend_failure_is_redacted_and_fail_closed(tmp_path, capsys, caplog, fault):
    canary = "canary-value-never-in-diagnostics"
    reader, client, controller = _bws_fixture(tmp_path, value=canary)
    client.missing = fault == "missing"
    client.failure = fault == "failure"
    client.wrong_response_project = fault == "response-project"
    if fault == "malformed":
        client.value = "malformed\n" + canary
    with pytest.raises(HostSecretBootstrapError) as error:
        resolve_host_secret_values(
            channel="prod" if fault == "scope" else "other" if fault == "bad-channel" else "dev",
            consumer="heimdal-capture-watch"
            if fault == "undeclared"
            else "builderops-model-inquiry",
            provider="wrong" if fault == "provider" else "bws",
            bws_reader=reader,
            controller=controller,
        )
    import traceback

    assert (
        canary
        not in "".join(traceback.format_exception(error.value))
        + capsys.readouterr().out
        + caplog.text
    )
    if fault in {"provider", "scope", "bad-channel"}:
        assert client.calls == []


def test_keychain_backend_remains_available_and_backend_failure_is_redacted():
    calls = []

    def lookup(service, account):
        calls.append((service, account))
        return _OPENAI_KEY

    assert resolve_host_secret_values(
        channel="dev",
        consumer="builderops-model-inquiry",
        provider="keychain",
        keychain_lookup=lookup,
    ) == {"openai.api-key": _OPENAI_KEY}
    assert calls == [("yggdrasil.host-secrets", "dev:builderops-model-inquiry:openai.api-key")]

    def failure(*args):
        raise RuntimeError("canary-provider-secret")

    with pytest.raises(HostSecretBootstrapError) as error:
        resolve_host_secret_values(
            channel="dev",
            consumer="builderops-model-inquiry",
            provider="keychain",
            keychain_lookup=failure,
        )
    import traceback

    assert "canary-provider-secret" not in "".join(traceback.format_exception(error.value))


@pytest.mark.parametrize("fault", ["missing", "unreadable", "symlink", "wrong-path", "directory"])
def test_missing_bws_access_token_file_fails_before_provider_request(tmp_path, monkeypatch, fault):
    reader, client, controller = _bws_fixture(tmp_path)
    token = reader.config.token_file
    if fault == "unreadable":
        token.chmod(0)
    else:
        token.unlink()
        if fault == "symlink":
            (tmp_path / "token").write_text("fixture-machine-token")
            token.symlink_to(tmp_path / "token")
        elif fault == "directory":
            token.mkdir()
        elif fault == "wrong-path":
            reader.config = BwsReaderConfig(
                "non-prod", _BWS_NON_PROD_PROJECT, _BWS_ORG, tmp_path, token
            )
    monkeypatch.setenv("BWS_ACCESS_TOKEN", "fixture-token-env-is-never-read")
    with pytest.raises(HostSecretBootstrapError):
        resolve_host_secret_values(
            channel="dev",
            consumer="builderops-model-inquiry",
            provider="bws",
            bws_reader=reader,
            controller=controller,
        )
    assert client.calls == []


def test_agent_host_operation_lock_serializes_bws_and_deploy_entrypoints(tmp_path):
    reader, client, controller = _bws_fixture(tmp_path)
    for kind in ("import", "deploy", "bootstrap"):
        with controller.admit(kind, "dev") as operation:
            with pytest.raises(HostSecretBootstrapError):
                resolve_host_secret_values(
                    channel="dev",
                    consumer="builderops-model-inquiry",
                    provider="bws",
                    bws_reader=reader,
                    controller=HostSecretController(controller.directory),
                )
            assert client.calls == []
            source = "provider-terminal" if kind in {"import", "bootstrap"} else "remote-terminal"
            operation.finish(
                TerminalEvidence(operation.operation_id, kind, "dev", "aborted", source)
            )
    with controller.token_push_operation("dev") as (operation, pending):
        assert pending is None
        operation.prepare_token_push(None)
        with pytest.raises(HostSecretBootstrapError):
            resolve_host_secret_values(
                channel="dev",
                consumer="builderops-model-inquiry",
                provider="bws",
                bws_reader=reader,
                controller=HostSecretController(controller.directory),
            )
        assert client.calls == []
        operation.finish(
            TerminalEvidence(
                operation.operation_id, "token-push", "dev", "aborted", "host-preflight"
            )
        )
    assert stat.S_IMODE(controller.directory.stat().st_mode) == 0o700
    assert all(
        stat.S_IMODE(path.stat().st_mode) == 0o600 for path in controller.directory.iterdir()
    )


def test_pending_operation_journal_blocks_after_process_interruption(tmp_path):
    directory = tmp_path / "controller"
    script = """from pathlib import Path
import os, sys
from app.ops.host_secret_controller import HostSecretController
with HostSecretController(Path(sys.argv[1])).admit("deploy", "dev") as operation:
    operation.prepare_mutation()
    os._exit(19)
"""
    result = subprocess.run([sys.executable, "-c", script, str(directory)], capture_output=True)
    assert result.returncode == 19
    journal = (directory / "operations.jsonl").read_text()
    assert '"stage": "sent"' in journal
    for kind in ("check", "import", "token-push", "deploy", "bootstrap"):
        with pytest.raises(HostSecretAdmissionError):
            with HostSecretController(directory).admit(kind, "dev"):
                pytest.fail("pending work must block admission")


def test_pending_operation_requires_matching_operation_id_readback(tmp_path):
    controller = HostSecretController(tmp_path / "controller")
    with controller.token_push_operation("dev") as (operation, pending):
        assert pending is None
        operation.prepare_token_push(None)
        operation.prepare_mutation()
    for evidence in [
        TerminalEvidence("wrong", "token-push", "dev", "committed", "remote-terminal"),
        TerminalEvidence(
            operation.operation_id, "token-push", "prod", "committed", "remote-terminal"
        ),
        TerminalEvidence(
            operation.operation_id, "token-push", "dev", "committed", "pointer-snapshot"
        ),
        TerminalEvidence(operation.operation_id, "token-push", "dev", "unknown", "remote-terminal"),
    ]:
        with pytest.raises(HostSecretAdmissionError):
            controller.reconcile(lambda *args: evidence)
    controller.reconcile(
        lambda operation_id, kind, target: TerminalEvidence(
            operation_id, kind, target, "committed", "remote-terminal"
        )
    )
    with controller.admit("check", "dev") as new:
        new.finish(TerminalEvidence(new.operation_id, "check", "dev", "committed", "read-complete"))


def test_linux_cli_requires_explicit_provider_and_never_falls_back(monkeypatch, capsys):
    monkeypatch.setattr(host_secret_bootstrap.sys, "platform", "linux")
    monkeypatch.delenv("HOST_SECRET_PROVIDER", raising=False)
    monkeypatch.setattr(
        host_secret_bootstrap,
        "run_with_host_secrets",
        lambda **kwargs: pytest.fail("implicit Keychain fallback"),
    )
    assert (
        host_secret_bootstrap.main(
            ["--channel", "dev", "--consumer", "heimdal-capture-watch", "--", "never-run"]
        )
        == 78
    )
    assert "explicit host secret provider required" in capsys.readouterr().err


def test_bws_cli_check_uses_file_token_and_memory_only_reader(tmp_path, monkeypatch, capsys):
    reader, client, controller = _bws_fixture(tmp_path)
    monkeypatch.setattr(
        host_secret_bootstrap.BwsReaderConfig, "from_environment", lambda env: reader.config
    )
    monkeypatch.setattr(host_secret_bootstrap, "BwsSecretReader", lambda config: reader)
    monkeypatch.setattr(host_secret_bootstrap, "HostSecretController", lambda: controller)
    assert (
        host_secret_bootstrap.main(
            [
                "--provider",
                "bws",
                "--check",
                "--channel",
                "dev",
                "--consumer",
                "builderops-model-inquiry",
            ]
        )
        == 0
    )
    assert client.calls[-1] == ("get", _BWS_ITEM)
    assert capsys.readouterr() == ("", "")
    assert set(tmp_path.iterdir()) == {reader.config.credentials_directory, controller.directory}


def test_bws_real_sdk_schema_is_used_without_live_network(tmp_path):
    """Exercise pinned SDK decoding through the real adapter; transport alone is fake."""
    from bitwarden_sdk import BitwardenClient

    reader, fixture, controller = _bws_fixture(tmp_path)
    client = BitwardenClient()

    class Transport:
        def run_command(self, command):
            request = json.loads(command)
            date = "2026-09-28T00:00:00Z"
            if request.get("loginAccessToken"):
                data = {
                    "authenticated": True,
                    "forcePasswordReset": False,
                    "resetMasterPassword": False,
                }
            elif request.get("projects", {}).get("list"):
                data = {
                    "data": [
                        {
                            "id": _BWS_NON_PROD_PROJECT,
                            "name": "non-prod",
                            "organizationId": _BWS_ORG,
                            "creationDate": date,
                            "revisionDate": date,
                        },
                        {
                            "id": _BWS_PROD_PROJECT,
                            "name": "prod",
                            "organizationId": _BWS_ORG,
                            "creationDate": date,
                            "revisionDate": date,
                        },
                    ]
                }
            elif request.get("secrets", {}).get("list"):
                data = {
                    "data": [
                        {
                            "id": _BWS_ITEM,
                            "key": "shared/openai.api-key",
                            "organizationId": _BWS_ORG,
                            "projectIds": [_BWS_NON_PROD_PROJECT],
                        }
                    ]
                }
            else:
                assert request["secrets"]["get"]["id"] == _BWS_ITEM
                data = {
                    "id": _BWS_ITEM,
                    "key": "shared/openai.api-key",
                    "organizationId": _BWS_ORG,
                    "projectId": _BWS_NON_PROD_PROJECT,
                    "value": _OPENAI_KEY,
                    "note": "",
                    "creationDate": date,
                    "revisionDate": date,
                }
            return json.dumps({"success": True, "data": data})

    client.inner = Transport()
    reader = BwsSecretReader(reader.config, client_factory=lambda: client)
    assert resolve_host_secret_values(
        channel="dev",
        consumer="builderops-model-inquiry",
        provider="bws",
        bws_reader=reader,
        controller=controller,
    ) == {"openai.api-key": _OPENAI_KEY}


def test_legacy_child_does_not_inherit_bws_credentials(monkeypatch):
    for name in ("BWS_ACCESS_TOKEN", "BWS_ACCESS_TOKEN_FILE", "CREDENTIALS_DIRECTORY", "TYPESAFE_API_KEY"):
        monkeypatch.setenv(name, "fixture-sensitive-surface")
    env = host_secret_bootstrap._clean_child_environment(host_secret_bootstrap.load_host_secret_contract())
    assert all(name not in env for name in ("BWS_ACCESS_TOKEN", "BWS_ACCESS_TOKEN_FILE", "CREDENTIALS_DIRECTORY", "TYPESAFE_API_KEY"))


def test_typesafe_server_bootstrap_attests_identity_without_materializing_provider_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(host_secret_bootstrap.sys, "platform", "darwin")
    monkeypatch.setenv("TYPESAFE_API_KEY", "fixture-ambient-key-must-not-be-inherited")
    environment = {
        "BWS_READER_PROJECT": "non-prod",
        "BWS_PROJECT_ID": _BWS_NON_PROD_PROJECT,
        "BWS_ORGANIZATION_ID": _BWS_ORG,
    }
    observed = []

    def runner(command: list[str], env: dict[str, str]) -> int:
        assert command == ["fixture-marr-server"]
        assert env[HOST_SECRET_BOOTSTRAP_CHANNEL] == "dev"
        assert env[HOST_SECRET_BOOTSTRAP_CONSUMER] == "marr-server-dev"
        assert HOST_SECRET_RUNTIME_ENV_FILE not in env
        assert "TYPESAFE_API_KEY" not in env
        assert "BWS_ACCESS_TOKEN" not in env
        assert "BWS_ACCESS_TOKEN_FILE" not in env
        assert "CREDENTIALS_DIRECTORY" not in env
        observed.append(env)
        return 0

    assert host_secret_bootstrap.run_marr_server_without_provider_key(
        command=["fixture-marr-server"], runner=runner, environment=environment
    ) == 0
    assert len(observed) == 1


@pytest.mark.parametrize(
    ("platform", "channel"), [("linux", "dev"), ("darwin", "test"), ("darwin", "prod")]
)
@pytest.mark.parametrize("run_on_credential_unavailable", [False, True])
def test_typesafe_server_bootstrap_refuses_before_lookup_or_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, platform: str, channel: str,
    run_on_credential_unavailable: bool,
) -> None:
    monkeypatch.setattr(host_secret_bootstrap.sys, "platform", platform)

    def lookup(_service: str, _account: str) -> str:
        pytest.fail("unauthorized bootstrap must not read a secret")

    def runner(_command: list[str], _env: dict[str, str]) -> int:
        pytest.fail("unauthorized bootstrap must not launch a consumer")

    with pytest.raises(HostSecretBootstrapError):
        run_with_host_secrets(
            channel=channel, consumer="marr-server-dev", command=["fixture-marr-server"],
            keychain_lookup=lookup, runner=runner, directory=tmp_path,
            run_on_credential_unavailable=run_on_credential_unavailable,
        )
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "environment",
    [
        {},
        {
            "BWS_READER_PROJECT": "prod",
            "BWS_PROJECT_ID": _BWS_PROD_PROJECT,
            "BWS_ORGANIZATION_ID": _BWS_ORG,
        },
        {
            "BWS_READER_PROJECT": "non-prod",
            "BWS_PROJECT_ID": _BWS_NON_PROD_PROJECT,
            "BWS_ORGANIZATION_ID": _BWS_ORG,
            "BWS_ACCESS_TOKEN": "forbidden-token-source",
        },
    ],
)
def test_typesafe_server_launch_refuses_ambient_or_wrong_bws_scope(environment, monkeypatch):
    monkeypatch.setattr(host_secret_bootstrap.sys, "platform", "darwin")
    launched = []
    with pytest.raises(HostSecretBootstrapError):
        host_secret_bootstrap.run_marr_server_without_provider_key(
            command=["fixture-marr-server"],
            environment=environment,
            runner=lambda command, _env: launched.append(command) or 0,
        )
    assert launched == []


def test_malformed_journal_never_reopens_admission(tmp_path):
    controller = HostSecretController(tmp_path / "controller")
    with controller.admit("deploy", "dev"):
        pass
    journal = controller.directory / "operations.jsonl"
    with journal.open("a") as stream:
        stream.write('{"operation_id":')
    with pytest.raises(HostSecretAdmissionError):
        with controller.admit("check", "dev"):
            pytest.fail("partial journal cannot mean no pending operation")


def test_deployment_read_retains_host_admission_through_activation(tmp_path):
    reader, client, controller = _bws_fixture(tmp_path)
    with controller.admit("deploy", "dev") as operation:
        result = resolve_host_secret_values(channel="dev", consumer="builderops-model-inquiry", provider="bws", bws_reader=reader, operation=operation)
        assert result == {"openai.api-key": _OPENAI_KEY}
        with pytest.raises(HostSecretAdmissionError):
            with HostSecretController(controller.directory).admit("import", "shared"):
                pytest.fail("writer must not enter between deployment preflight and activation")
        operation.prepare_mutation()
        operation.finish(TerminalEvidence(operation.operation_id, "deploy", "dev", "committed", "remote-terminal"))
    calls = list(client.calls)
    with pytest.raises(HostSecretBootstrapError):
        resolve_host_secret_values(channel="dev", consumer="builderops-model-inquiry", provider="bws", bws_reader=reader, operation=operation)
    assert client.calls == calls


@pytest.mark.parametrize("password", ["app", "a b", " existing ", "ö", "x" * 2048, "ö" * 1024])
def test_bws_existing_postgres_password_does_not_require_rotation(tmp_path, password):
    reader, client, controller = _bws_fixture(tmp_path, identity="dev/postgres.password", value=password)
    assert resolve_host_secret_values(channel="dev", consumer="postgres-api", provider="bws", bws_reader=reader, controller=controller) == {"postgres.password": password}


@pytest.mark.parametrize("password", ["", "a\nb", "a\rb", "a\x00b", "a\tb", "\ud800"])
def test_bws_malformed_postgres_password_is_refused(tmp_path, password):
    reader, client, controller = _bws_fixture(tmp_path, identity="dev/postgres.password", value=password)
    with pytest.raises(HostSecretBootstrapError):
        resolve_host_secret_values(channel="dev", consumer="postgres-api", provider="bws", bws_reader=reader, controller=controller)


def test_first_use_controller_directory_chain_is_durable_before_admission(tmp_path, monkeypatch):
    path = tmp_path / "new-state" / "yggdrasil" / "secret-controller"
    observed = set()
    real_fsync = os.fsync
    def record_fsync(descriptor):
        details = os.fstat(descriptor)
        observed.add((details.st_dev, details.st_ino))
        real_fsync(descriptor)
    monkeypatch.setattr(os, "fsync", record_fsync)
    with HostSecretController(path).admit("deploy", "dev") as operation:
        # Every new directory AND the existing parent of the new subtree is
        # fsynced before a callback can perform any remote effect.
        for directory in (tmp_path, tmp_path / "new-state", path.parent, path):
            details = directory.stat()
            assert (details.st_dev, details.st_ino) in observed
        operation.finish(TerminalEvidence(operation.operation_id, "deploy", "dev", "aborted", "remote-terminal"))


def test_first_use_parent_fsync_failure_prevents_admission(tmp_path, monkeypatch):
    details = tmp_path.stat()
    parent_identity = (details.st_dev, details.st_ino)
    real_fsync = os.fsync
    def fail_parent_fsync(descriptor):
        item = os.fstat(descriptor)
        if (item.st_dev, item.st_ino) == parent_identity:
            raise OSError("fixture durability failure")
        real_fsync(descriptor)
    monkeypatch.setattr(os, "fsync", fail_parent_fsync)
    with pytest.raises(HostSecretAdmissionError):
        with HostSecretController(tmp_path / "new-state" / "controller").admit("deploy", "dev"):
            pytest.fail("no effect may precede durable directory creation")
