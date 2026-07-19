"""Fail-closed host-secret bootstrap for declared local runtime consumers."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
from types import FrameType

from app.ops.host_secret_contract import HostSecretContract, load_host_secret_contract


HOST_SECRET_RUNTIME_ENV_FILE = "HOST_SECRET_RUNTIME_ENV_FILE"
_SECRET_ENV_NAMES = {
    "heimdal.raw-store-key": "HEIMDAL_RAW_STORE_KEY",
}
_RAW_STORE_KEY_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
_CHILD_WAIT_POLL_SECONDS = 0.1
_CHILD_TERMINATION_GRACE_SECONDS = 5.0

KeychainLookup = Callable[[str, str], str]
CommandRunner = Callable[[list[str], dict[str, str]], int]


class HostSecretBootstrapError(RuntimeError):
    """Redacted bootstrap failure that never carries resolved secret material."""


class HostSecretBootstrapTerminated(HostSecretBootstrapError):
    """Signal termination after the bootstrap has begun controlled cleanup."""

    def __init__(self, signum: int) -> None:
        super().__init__("host secret bootstrap terminated for declared consumer")
        self.signum = signum


SignalHandler = Callable[[int, FrameType | None], None]


@contextmanager
def _temporary_signal_handlers(handler: SignalHandler) -> Iterator[None]:
    """Install cleanup-aware handlers when running on the main thread."""
    if threading.current_thread() is not threading.main_thread():
        yield
        return

    handled = tuple(
        selected
        for selected in (signal.SIGTERM, signal.SIGINT, getattr(signal, "SIGHUP", None))
        if selected is not None
    )
    previous = {selected: signal.getsignal(selected) for selected in handled}
    try:
        for selected in handled:
            signal.signal(selected, handler)
        yield
    finally:
        for selected, prior in previous.items():
            signal.signal(selected, prior)


def _security_keychain_lookup(service: str, account: str) -> str:
    try:
        result = subprocess.run(
            [
                "security",
                "find-generic-password",
                "-s",
                service,
                "-a",
                account,
                "-w",
            ],
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except OSError as exc:
        raise HostSecretBootstrapError(
            "host secret bootstrap failed for declared consumer"
        ) from exc
    if result.returncode != 0:
        raise HostSecretBootstrapError(
            "host secret bootstrap failed for declared consumer"
        )
    return result.stdout.rstrip("\r\n")


def _declared_secrets(
    contract: HostSecretContract,
    *,
    channel: str,
    consumer: str,
) -> list[str]:
    secrets = sorted(
        secret
        for declared_channel, declared_consumer, secret in contract.allowed
        if declared_channel == channel and declared_consumer == consumer
    )
    if not secrets:
        raise HostSecretBootstrapError(
            "host secret bootstrap failed for declared consumer"
        )
    return secrets


def _validate_secret(secret: str, value: str) -> bool:
    if secret == "heimdal.raw-store-key":
        return _RAW_STORE_KEY_PATTERN.fullmatch(value) is not None
    return False


def _resolve_consumer_environment(
    *,
    channel: str,
    consumer: str,
    contract: HostSecretContract,
    keychain_lookup: KeychainLookup,
) -> dict[str, str]:
    resolved: dict[str, str] = {}
    try:
        for secret in _declared_secrets(
            contract,
            channel=channel,
            consumer=consumer,
        ):
            env_name = _SECRET_ENV_NAMES.get(secret)
            if env_name is None:
                raise HostSecretBootstrapError(
                    "host secret bootstrap failed for declared consumer"
                )
            account = contract.keychain_account(
                channel=channel,
                consumer=consumer,
                secret=secret,
            )
            value = keychain_lookup(contract.keychain_service, account)
            if not _validate_secret(secret, value):
                raise HostSecretBootstrapError(
                    "host secret bootstrap failed for declared consumer"
                )
            resolved[env_name] = value
    except HostSecretBootstrapError:
        raise
    except Exception as exc:
        raise HostSecretBootstrapError(
            "host secret bootstrap failed for declared consumer"
        ) from exc
    return resolved


@contextmanager
def materialize_consumer_environment(
    *,
    channel: str,
    consumer: str,
    keychain_lookup: KeychainLookup = _security_keychain_lookup,
    contract: HostSecretContract | None = None,
    directory: Path | None = None,
) -> Iterator[Path]:
    """Yield one mode-0600 env file containing only the declared values."""
    try:
        selected_contract = contract or load_host_secret_contract()
        values = _resolve_consumer_environment(
            channel=channel,
            consumer=consumer,
            contract=selected_contract,
            keychain_lookup=keychain_lookup,
        )
    except HostSecretBootstrapError:
        raise
    except Exception as exc:
        raise HostSecretBootstrapError(
            "host secret bootstrap failed for declared consumer"
        ) from exc

    file_path: Path | None = None
    fd: int | None = None
    termination_signal: int | None = None
    cleanup_in_progress = False

    def cleanup_then_terminate(signum: int, _frame: FrameType | None) -> None:
        nonlocal termination_signal
        if termination_signal is None:
            termination_signal = signum
        if cleanup_in_progress:
            return
        raise HostSecretBootstrapTerminated(termination_signal)

    def cleanup_materialized_file() -> None:
        nonlocal cleanup_in_progress, fd
        cleanup_in_progress = True
        try:
            if fd is not None:
                os.close(fd)
                fd = None
            if file_path is None:
                return
            try:
                file_path.unlink(missing_ok=True)
            except OSError as exc:
                raise HostSecretBootstrapError(
                    "host secret bootstrap failed for declared consumer"
                ) from exc
        finally:
            cleanup_in_progress = False

    try:
        with _temporary_signal_handlers(cleanup_then_terminate):
            try:
                fd, raw_path = tempfile.mkstemp(
                    prefix="yggdrasil-host-secret-",
                    suffix=".env",
                    dir=directory,
                )
                file_path = Path(raw_path)
                os.fchmod(fd, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8", closefd=True) as handle:
                    fd = None
                    for name in sorted(values):
                        handle.write(f"{name}={values[name]}\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                yield file_path
            finally:
                cleanup_materialized_file()
                if termination_signal is not None:
                    raise HostSecretBootstrapTerminated(termination_signal)
    except HostSecretBootstrapError:
        raise
    except Exception as exc:
        raise HostSecretBootstrapError(
            "host secret bootstrap failed for declared consumer"
        ) from exc


def _subprocess_runner(command: list[str], env: dict[str, str]) -> int:
    process: subprocess.Popen[bytes] | None = None
    termination_signal: int | None = None

    def forward_then_terminate(signum: int, _frame: FrameType | None) -> None:
        nonlocal termination_signal
        if termination_signal is None:
            termination_signal = signum
        active_process = process
        if active_process is not None and active_process.poll() is None:
            try:
                active_process.send_signal(signum)
            except ProcessLookupError:
                pass

    def terminate_and_reap(active_process: subprocess.Popen[bytes], signum: int) -> None:
        if active_process.poll() is None:
            try:
                active_process.send_signal(signum)
            except ProcessLookupError:
                pass
        deadline = time.monotonic() + _CHILD_TERMINATION_GRACE_SECONDS
        while active_process.poll() is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                active_process.kill()
                break
            try:
                active_process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                active_process.kill()
                break
        active_process.wait()

    with _temporary_signal_handlers(forward_then_terminate):
        process = subprocess.Popen(command, env=env)
        while True:
            if termination_signal is not None:
                terminate_and_reap(process, termination_signal)
                raise HostSecretBootstrapTerminated(termination_signal)
            try:
                returncode = process.wait(timeout=_CHILD_WAIT_POLL_SECONDS)
            except subprocess.TimeoutExpired:
                continue
            if termination_signal is not None:
                raise HostSecretBootstrapTerminated(termination_signal)
            return returncode


def run_with_host_secrets(
    *,
    channel: str,
    consumer: str,
    command: Sequence[str],
    keychain_lookup: KeychainLookup = _security_keychain_lookup,
    runner: CommandRunner = _subprocess_runner,
    contract: HostSecretContract | None = None,
    directory: Path | None = None,
) -> int:
    """Launch *command* with a temporary secret env-file pointer, then clean it."""
    selected_command = list(command)
    if not selected_command:
        raise HostSecretBootstrapError(
            "host secret bootstrap failed for declared consumer"
        )
    with materialize_consumer_environment(
        channel=channel,
        consumer=consumer,
        keychain_lookup=keychain_lookup,
        contract=contract,
        directory=directory,
    ) as env_file:
        child_env = dict(os.environ)
        for env_name in _SECRET_ENV_NAMES.values():
            child_env.pop(env_name, None)
        child_env[HOST_SECRET_RUNTIME_ENV_FILE] = str(env_file)
        return runner(selected_command, child_env)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Launch a declared consumer with redacted host-secret bootstrap",
    )
    parser.add_argument("--channel", required=True)
    parser.add_argument("--consumer", required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    command = list(args.command)
    if command[:1] == ["--"]:
        command = command[1:]
    try:
        return run_with_host_secrets(
            channel=args.channel,
            consumer=args.consumer,
            command=command,
        )
    except HostSecretBootstrapTerminated as exc:
        print(
            "host secret bootstrap terminated; temporary material removed",
            file=sys.stderr,
        )
        return 128 + exc.signum
    except HostSecretBootstrapError:
        print(
            "host secret bootstrap failed for declared consumer; "
            "verify the declared Keychain item and non-interactive access",
            file=sys.stderr,
        )
        return 78


if __name__ == "__main__":
    raise SystemExit(main())
