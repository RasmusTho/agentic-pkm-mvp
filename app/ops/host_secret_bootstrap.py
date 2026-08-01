"""Fail-closed host-secret bootstrap for declared local runtime consumers."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
import ctypes
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
from types import FrameType

from app.ops.host_secret_contract import HostSecretContract, load_host_secret_contract


HOST_SECRET_RUNTIME_ENV_FILE = "HOST_SECRET_RUNTIME_ENV_FILE"
HOST_SECRET_BOOTSTRAP_FAILURE_REF = "HOST_SECRET_BOOTSTRAP_FAILURE_REF"
_RAW_STORE_KEY_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
_CHILD_WAIT_POLL_SECONDS = 0.1
_CHILD_TERMINATION_GRACE_SECONDS = 5.0
_CHILD_POST_KILL_REAP_SECONDS = 1.0

KeychainLookup = Callable[[str, str], str]
CommandRunner = Callable[[list[str], dict[str, str]], int]


class HostSecretBootstrapError(RuntimeError):
    """Redacted bootstrap failure that never carries resolved secret material."""


class HostSecretCredentialUnavailableError(HostSecretBootstrapError):
    """One declared API credential is absent or unusable."""

    def __init__(self, credential_identity_ref: str) -> None:
        super().__init__(
            f"host secret bootstrap failed for declared secret: {credential_identity_ref}"
        )
        self.credential_identity_ref = credential_identity_ref


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
    # The framework path returns exact Keychain bytes; the `security` CLI below
    # strips one trailing newline, which would let a stray-newline value pass a
    # `value == value.strip()` grammar that was written to reject it (#4289).
    # Every kind validated by that grammar must take the exact-bytes path — so
    # `token` joins `api-key` here rather than inheriting the CLI's trimming
    # (#4489).
    if account.endswith(".api-key") or account.endswith(".token"):
        return _security_framework_keychain_lookup(service, account)
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
    value = result.stdout
    if value.endswith("\n"):
        value = value[:-1]
        if value.endswith("\r"):
            value = value[:-1]
    return value


def _security_framework_keychain_lookup(service: str, account: str) -> str:
    """Read exact Keychain bytes so validation sees control characters."""
    try:
        framework = ctypes.CDLL(
            "/System/Library/Frameworks/Security.framework/Security"
        )
        find_password = framework.SecKeychainFindGenericPassword
        find_password.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_char_p,
            ctypes.c_uint32,
            ctypes.c_char_p,
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.c_void_p,
        ]
        find_password.restype = ctypes.c_int32
        free_content = framework.SecKeychainItemFreeContent
        free_content.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        free_content.restype = ctypes.c_int32

        service_bytes = service.encode("utf-8")
        account_bytes = account.encode("utf-8")
        password_length = ctypes.c_uint32()
        password_data = ctypes.c_void_p()
        status = find_password(
            None,
            len(service_bytes),
            service_bytes,
            len(account_bytes),
            account_bytes,
            ctypes.byref(password_length),
            ctypes.byref(password_data),
            None,
        )
        if status != 0 or password_data.value is None:
            raise HostSecretBootstrapError(
                "host secret bootstrap failed for declared consumer"
            )
        try:
            raw_value = ctypes.string_at(password_data, password_length.value)
        finally:
            free_status = free_content(None, password_data)
            if free_status != 0:
                raise HostSecretBootstrapError(
                    "host secret bootstrap failed for declared consumer"
                )
        return raw_value.decode("utf-8", errors="strict")
    except HostSecretBootstrapError:
        raise
    except Exception as exc:
        raise HostSecretBootstrapError(
            "host secret bootstrap failed for declared consumer"
        ) from exc


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


def _validate_secret(kind: str, value: str) -> bool:
    if kind == "raw-store-key":
        return _RAW_STORE_KEY_PATTERN.fullmatch(value) is not None
    # `token` shares the api-key grammar deliberately (#4489): both are opaque
    # provider-issued bearer strings, and a second near-identical grammar would
    # be a place for the two to drift apart rather than a real distinction. The
    # kind exists at all because the contract derives it from the logical id's
    # suffix, and `GITHUB_TOKEN` requires the logical id `github.token`.
    if kind in {"api-key", "token"}:
        return (
            value == value.strip()
            and 20 <= len(value) <= 512
            and all(char.isprintable() and not char.isspace() for char in value)
        )
    return False


def validate_secret_value(kind: str, value: str) -> bool:
    """Return whether *value* satisfies the declared validation kind.

    Public so a declared consumer can fail closed on a malformed value using the
    same rule the bootstrap applies, without duplicating the grammar.
    """
    return _validate_secret(kind, value)


def load_runtime_secret_values(
    env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Read the declared bindings this process received from the bootstrap.

    The bootstrap never copies declared bindings into the ambient environment;
    it materializes one mode-0600 file and names it in
    ``HOST_SECRET_RUNTIME_ENV_FILE``. This reader is therefore the contract
    path for a consumer, and it never falls back to ambient environment. An
    absent or unreadable surface returns no values so the caller fails closed
    while naming only its logical identifier.
    """
    source = os.environ if env is None else env
    raw_path = str(source.get(HOST_SECRET_RUNTIME_ENV_FILE, "")).strip()
    if not raw_path:
        return {}
    content = _read_runtime_secret_file(Path(raw_path))
    if content is None:
        return {}
    values: dict[str, str] = {}
    for line in content.splitlines():
        name, separator, value = line.partition("=")
        if not separator or not name.strip():
            continue
        values[name.strip()] = value
    return values


def _read_runtime_secret_file(path: Path) -> str | None:
    """Read one bootstrap-owned surface without following its final component."""
    if not path.is_absolute():
        return None
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_NONBLOCK"):
        # A hostile FIFO must reach the descriptor-bound regular-file check
        # instead of blocking forever while waiting for a writer.
        flags |= os.O_NONBLOCK
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return None
    try:
        details = os.fstat(descriptor)
        if (
            not stat.S_ISREG(details.st_mode)
            or details.st_uid != os.geteuid()
            or stat.S_IMODE(details.st_mode) != 0o600
            or details.st_nlink != 1
        ):
            return None
        chunks: list[bytes] = []
        total = 0
        while chunk := os.read(descriptor, 65536):
            total += len(chunk)
            if total > 65536:
                return None
            chunks.append(chunk)
        try:
            return b"".join(chunks).decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            return None
    finally:
        os.close(descriptor)


def _secret_failure(*, secret: str, kind: str) -> HostSecretBootstrapError:
    # The identifier-bearing variant names the logical id (never a value), which
    # is what an operator needs to find the right Keychain item. `token` shares
    # it for that reason; the only behavioral difference is the
    # `run_on_credential_unavailable` opt-in, which no consumer granted a
    # `token` secret uses (#4489).
    if kind in {"api-key", "token"}:
        return HostSecretCredentialUnavailableError(secret)
    return HostSecretBootstrapError(
        "host secret bootstrap failed for declared consumer"
    )


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
            env_name = contract.binding_for(secret)
            kind = contract.kind_for(secret)
            account = contract.keychain_account(
                channel=channel,
                consumer=consumer,
                secret=secret,
            )
            try:
                value = keychain_lookup(contract.keychain_service, account)
            except Exception as exc:
                # An optional declaration tolerates *absence* only, and the
                # lookup cannot distinguish "no such item" from any other
                # failure, so an unresolvable optional secret simply does not
                # bind. Its consumer runs without it; a required one still
                # fails the whole bootstrap (#4489).
                if contract.is_optional(secret):
                    continue
                raise _secret_failure(secret=secret, kind=kind) from exc
            # Validation is deliberately outside that tolerance: a value that
            # is present and wrong is a misconfiguration, never an opt-out.
            if not _validate_secret(kind, value):
                raise _secret_failure(secret=secret, kind=kind)
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
    materialization_ready = False

    def cleanup_then_terminate(signum: int, _frame: FrameType | None) -> None:
        nonlocal termination_signal
        if termination_signal is None:
            termination_signal = signum
        if file_path is not None:
            try:
                file_path.unlink(missing_ok=True)
            except OSError as exc:
                raise HostSecretBootstrapError(
                    "host secret bootstrap failed for declared consumer"
                ) from exc
        if cleanup_in_progress or not materialization_ready:
            return
        raise HostSecretBootstrapTerminated(termination_signal)

    def cleanup_materialized_file() -> None:
        nonlocal cleanup_in_progress, fd
        cleanup_in_progress = True
        cleanup_error: OSError | None = None
        try:
            if fd is not None:
                try:
                    os.close(fd)
                except OSError as exc:
                    cleanup_error = exc
                finally:
                    fd = None
            if file_path is not None:
                try:
                    file_path.unlink(missing_ok=True)
                except OSError as exc:
                    if cleanup_error is None:
                        cleanup_error = exc
            if cleanup_error is not None:
                raise HostSecretBootstrapError(
                    "host secret bootstrap failed for declared consumer"
                ) from cleanup_error
        finally:
            cleanup_in_progress = False

    try:
        with _temporary_signal_handlers(cleanup_then_terminate):
            try:
                # Defer catchable termination until the descriptor/path pair has
                # reached a cleanup-safe state. A handler may run after mkstemp
                # returns but before Python assigns either value.
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
                materialization_ready = True
                if termination_signal is not None:
                    raise HostSecretBootstrapTerminated(termination_signal)
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
        try:
            active_process.wait(timeout=_CHILD_POST_KILL_REAP_SECONDS)
        except subprocess.TimeoutExpired:
            # A killed child can remain uninterruptible. Do not let an unbounded
            # reap prevent the outer context from removing plaintext material.
            pass

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
    run_on_credential_unavailable: bool = False,
) -> int:
    """Launch *command* with a temporary secret env-file pointer, then clean it."""
    selected_command = list(command)
    if not selected_command:
        raise HostSecretBootstrapError(
            "host secret bootstrap failed for declared consumer"
        )
    try:
        selected_contract = contract or load_host_secret_contract()
    except Exception as exc:
        raise HostSecretBootstrapError(
            "host secret bootstrap failed for declared consumer"
        ) from exc
    try:
        materialized = materialize_consumer_environment(
            channel=channel,
            consumer=consumer,
            keychain_lookup=keychain_lookup,
            contract=selected_contract,
            directory=directory,
        )
        with materialized as env_file:
            child_env = _clean_child_environment(selected_contract)
            child_env[HOST_SECRET_RUNTIME_ENV_FILE] = str(env_file)
            return runner(selected_command, child_env)
    except HostSecretCredentialUnavailableError as exc:
        if not run_on_credential_unavailable:
            raise
        # The handoff drops the WHOLE layer, not just the failed secret, so an
        # optional secret must never be able to trigger it: that would let a
        # misconfigured optional credential silently de-provision a *required*
        # one declared for the same consumer (#4489). Only a required
        # credential's unavailability is something a caller may opt into
        # running without.
        if selected_contract.is_optional(exc.credential_identity_ref):
            raise
        # Model Inquiry owns the durable typed terminal receipt. This opt-in
        # handoff carries only the declared logical identifier, never a value,
        # and still launches without any provider credential binding.
        child_env = _clean_child_environment(selected_contract)
        child_env[HOST_SECRET_BOOTSTRAP_FAILURE_REF] = exc.credential_identity_ref
        return runner(selected_command, child_env)


def _clean_child_environment(contract: HostSecretContract) -> dict[str, str]:
    """Return ambient state with every bootstrap-owned surface removed."""
    child_env = dict(os.environ)
    child_env.pop(HOST_SECRET_RUNTIME_ENV_FILE, None)
    child_env.pop(HOST_SECRET_BOOTSTRAP_FAILURE_REF, None)
    for env_name in contract.child_bindings:
        child_env.pop(env_name, None)
    return child_env


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Launch a declared consumer with redacted host-secret bootstrap",
    )
    parser.add_argument("--channel", required=True)
    parser.add_argument("--consumer", required=True)
    parser.add_argument(
        "--run-on-credential-unavailable",
        action="store_true",
        help=(
            "run the child with a value-free typed failure handoff when a declared "
            "API credential is unavailable"
        ),
    )
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
            run_on_credential_unavailable=args.run_on_credential_unavailable,
        )
    except HostSecretBootstrapTerminated as exc:
        print(
            "host secret bootstrap terminated; temporary material removed",
            file=sys.stderr,
        )
        return 128 + exc.signum
    except HostSecretBootstrapError as exc:
        print(
            f"{exc}; "
            "verify the declared Keychain item and non-interactive access",
            file=sys.stderr,
        )
        return 78


if __name__ == "__main__":
    raise SystemExit(main())
