"""Encrypted, same-ID VM handoff for the bounded BWS reader-token targets."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time
from typing import Protocol
from typing import TextIO
from uuid import UUID, uuid4

from app.ops.bws_secret_admin import _security_framework_keychain_lookup
from app.ops.host_secret_controller import (
    HostSecretController,
    TerminalEvidence,
)


_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TARGET_CONFIG = _REPOSITORY_ROOT / "config/secrets/bws_reader_token_targets.json"
_EXPECTED_TARGETS = {
    "ygg-dev": ("dev", "non-prod", "non-prod-reader"),
    "ygg-test": ("test", "non-prod", "non-prod-reader"),
    "ygg-prod": ("prod", "prod", "prod-reader"),
}
_KEYCHAIN_SERVICE = "yggdrasil.bws-reader"
_CREDENTIAL_NAME = "bws-machine-account-token"
_GENERATION_PATTERN = re.compile(
    r"^generations/gen-([0-9a-f-]{36})-([0-9a-f-]{36})\.cred$"
)
_ACTIVE_SYSTEMD_STATES = {"activating", "active", "deactivating", "reloading"}


class TokenPushError(RuntimeError):
    """Redacted refusal; callers must inspect the value-free operation receipt."""

    def __init__(self) -> None:
        super().__init__("reader-token push refused; inspect value-free operation status")


@dataclass(frozen=True)
class TokenPushTarget:
    vm: str
    channel: str
    project: str
    reader_account: str
    ssh_host: str

    @property
    def keychain_account(self) -> str:
        return self.reader_account + ".token"


def load_token_push_targets(path: Path = DEFAULT_TARGET_CONFIG) -> dict[str, TokenPushTarget]:
    """Load the fixed target map; config cannot widen the account/project boundary."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if (
            not isinstance(payload, dict)
            or set(payload) != {"version", "keychain_service", "targets"}
            or type(payload["version"]) is not int
            or payload["version"] != 1
            or payload["keychain_service"] != _KEYCHAIN_SERVICE
            or not isinstance(payload["targets"], list)
            or len(payload["targets"]) != len(_EXPECTED_TARGETS)
        ):
            raise TokenPushError()
        targets: dict[str, TokenPushTarget] = {}
        for row in payload["targets"]:
            if not isinstance(row, dict) or set(row) != {
                "vm", "channel", "project", "reader_account", "ssh_host"
            }:
                raise TokenPushError()
            vm = row["vm"]
            expected = _EXPECTED_TARGETS.get(vm)
            if (
                expected is None
                or vm in targets
                or (row["channel"], row["project"], row["reader_account"]) != expected
                or row["ssh_host"] != vm
            ):
                raise TokenPushError()
            targets[vm] = TokenPushTarget(
                vm, row["channel"], row["project"], row["reader_account"], row["ssh_host"]
            )
        if set(targets) != set(_EXPECTED_TARGETS):
            raise TokenPushError()
        return targets
    except TokenPushError:
        raise
    except Exception:
        raise TokenPushError() from None


def validate_reader_token(value: str) -> bool:
    try:
        encoded = value.encode("utf-8", errors="strict")
    except (AttributeError, UnicodeError):
        return False
    return (
        1 <= len(encoded) <= 4096
        and all(char.isprintable() and not char.isspace() for char in value)
    )


class ReaderTokenSource(Protocol):
    def read(self, target: TokenPushTarget) -> str: ...


class KeychainReaderTokenSource:
    """Read one exact-byte reader token from the Mac agent-host Keychain."""

    def __init__(
        self,
        *,
        lookup: Callable[[str, str], str] = _security_framework_keychain_lookup,
        keychain_service: str = _KEYCHAIN_SERVICE,
    ) -> None:
        if keychain_service != _KEYCHAIN_SERVICE:
            raise TokenPushError()
        self._lookup = lookup
        self._service = keychain_service

    def read(self, target: TokenPushTarget) -> str:
        if sys.platform != "darwin":
            raise TokenPushError()
        try:
            token = self._lookup(self._service, target.keychain_account)
            if not validate_reader_token(token):
                raise TokenPushError()
            return token
        except Exception:
            raise TokenPushError() from None


@dataclass(frozen=True)
class TokenPushReceipt:
    operation_id: str
    channel: str
    kind: str
    stage: str
    terminal_result: str | None
    attempt_id: str
    prior_generation: str | None
    generation_id: str | None

    def validate(self) -> None:
        try:
            valid = (
                str(UUID(self.operation_id)) == self.operation_id
                and str(UUID(self.attempt_id)) == self.attempt_id
                and self.channel in {"dev", "test", "prod"}
                and self.kind == "token-push"
                and self.stage in {"prepared", "applying", "committed", "aborted"}
                and self.terminal_result
                == (self.stage if self.stage in {"committed", "aborted"} else None)
                and (
                    self.prior_generation is None
                    or str(UUID(self.prior_generation)) == self.prior_generation
                )
                and (
                    self.generation_id is None
                    or str(UUID(self.generation_id)) == self.generation_id
                )
                and (
                    (self.stage in {"applying", "committed"})
                    == (self.generation_id is not None)
                )
                and (
                    self.generation_id is None
                    or self.generation_id != self.prior_generation
                )
            )
        except Exception:
            valid = False
        if not valid:
            raise TokenPushError()

    def evidence(self) -> TerminalEvidence:
        self.validate()
        if self.terminal_result is None:
            raise TokenPushError()
        return TerminalEvidence(
            self.operation_id, self.kind, self.channel, self.terminal_result, "remote-terminal"
        )


def _receipt_from_mapping(payload: object) -> TokenPushReceipt:
    try:
        if not isinstance(payload, dict) or set(payload) != {
            "operation_id", "channel", "kind", "stage", "terminal_result",
            "attempt_id", "prior_generation", "generation_id",
        }:
            raise TokenPushError()
        receipt = TokenPushReceipt(**payload)
        receipt.validate()
        return receipt
    except TokenPushError:
        raise
    except Exception:
        raise TokenPushError() from None


class TokenPushRemote(Protocol):
    def inspect(self, channel: str) -> str | None: ...

    def push(
        self,
        target: TokenPushTarget,
        operation_id: str,
        attempt_id: str,
        prior_generation: str | None,
        token: str,
    ) -> TokenPushReceipt: ...

    def reconcile(
        self, target: TokenPushTarget, operation_id: str, prior_generation: str | None
    ) -> TokenPushReceipt: ...


CommandRunner = Callable[..., subprocess.CompletedProcess[bytes]]


class SshTokenPushRemote:
    """VLAN-first SSH adapter; the credential travels only on stdin."""

    def __init__(
        self,
        *,
        runner: CommandRunner = subprocess.run,
        launcher: str = "/usr/local/libexec/yggdrasil-bws-deploy",
    ) -> None:
        self._runner = runner
        self._launcher = launcher

    def _call(
        self,
        target: TokenPushTarget,
        action: str,
        arguments: tuple[str, ...] = (),
        *,
        token: str | None = None,
    ) -> bytes:
        command = [
            "ssh", "-o", "BatchMode=yes", "--", target.ssh_host,
            "sudo", "-n", self._launcher, action, target.channel, *arguments,
        ]
        try:
            result = self._runner(
                command,
                input=token.encode("utf-8") if token is not None else None,
                capture_output=True,
                check=False,
            )
            if result.returncode != 0:
                raise TokenPushError()
            return result.stdout
        except Exception:
            raise TokenPushError() from None

    def inspect(self, channel: str) -> str | None:
        target = next((row for row in load_token_push_targets().values() if row.channel == channel), None)
        if target is None:
            raise TokenPushError()
        try:
            payload = json.loads(self._call(target, "token-push-inspect"))
            if not isinstance(payload, dict) or set(payload) != {"generation_id"}:
                raise TokenPushError()
            generation = payload["generation_id"]
            if generation is not None and (
                not isinstance(generation, str) or str(UUID(generation)) != generation
            ):
                raise TokenPushError()
            return generation
        except TokenPushError:
            raise
        except Exception:
            raise TokenPushError() from None

    def push(
        self,
        target: TokenPushTarget,
        operation_id: str,
        attempt_id: str,
        prior_generation: str | None,
        token: str,
    ) -> TokenPushReceipt:
        prior = prior_generation or "absent"
        payload = self._call(
            target,
            "token-push",
            (operation_id, attempt_id, prior),
            token=token,
        )
        return _receipt_from_mapping(json.loads(payload))

    def reconcile(
        self, target: TokenPushTarget, operation_id: str, prior_generation: str | None
    ) -> TokenPushReceipt:
        receipt = _receipt_from_mapping(
            json.loads(self._call(target, "token-push-status", (operation_id,)))
        )
        if receipt.prior_generation != prior_generation:
            raise TokenPushError()
        return receipt


class TokenPushAdmin:
    """Coordinates local admission, exact Keychain resolution and remote receipts."""

    def __init__(
        self,
        *,
        controller: HostSecretController | None = None,
        token_source: ReaderTokenSource | None = None,
        remote_factory: Callable[[], TokenPushRemote] = SshTokenPushRemote,
        targets_path: Path = DEFAULT_TARGET_CONFIG,
    ) -> None:
        self.controller = controller or HostSecretController()
        self.token_source = token_source or KeychainReaderTokenSource()
        self.remote_factory = remote_factory
        self.targets_path = targets_path

    def push(self, vm: str) -> TokenPushReceipt:
        try:
            targets = load_token_push_targets(self.targets_path)
            target = targets.get(vm)
            if target is None:
                raise TokenPushError()
            remote = self.remote_factory()
            with self.controller.token_push_operation(target.channel) as (operation, pending):
                if pending is None:
                    prior_generation = remote.inspect(target.channel)
                    operation.prepare_token_push(prior_generation)
                else:
                    prior_generation = pending["prior_generation"]
                    if pending["stage"] == "sent":
                        receipt = remote.reconcile(
                            target, operation.operation_id, prior_generation
                        )
                        if receipt.operation_id != operation.operation_id:
                            raise TokenPushError()
                        if receipt.stage == "committed":
                            operation.finish(receipt.evidence())
                            return receipt
                        if receipt.stage != "aborted":
                            raise TokenPushError()

                if prior_generation is not None and str(UUID(prior_generation)) != prior_generation:
                    raise TokenPushError()
                try:
                    token = self.token_source.read(target)
                except Exception:
                    if not operation.mutation_started:
                        operation.finish(TerminalEvidence(
                            operation.operation_id, "token-push", target.channel,
                            "aborted", "host-preflight",
                        ))
                    raise TokenPushError() from None

                operation.prepare_mutation()
                attempt_id = str(uuid4())
                receipt = remote.push(
                    target, operation.operation_id, attempt_id, prior_generation, token
                )
                del token
                receipt.validate()
                if (
                    receipt.operation_id != operation.operation_id
                    or receipt.attempt_id != attempt_id
                    or receipt.channel != target.channel
                    or receipt.prior_generation != prior_generation
                ):
                    raise TokenPushError()
                if receipt.stage == "committed":
                    operation.finish(receipt.evidence())
                    return receipt
                # A durable aborted receipt authorizes a later same-ID retry.
                # Keep the host operation pending so that later commands first
                # reconcile that receipt instead of silently allocating a new ID.
                raise TokenPushError()
        except TokenPushError:
            raise
        except Exception:
            raise TokenPushError() from None


def _secure_directory(path: Path) -> None:
    if not path.is_absolute():
        raise TokenPushError()
    for parent in (path, *path.parents):
        if parent.is_symlink():
            raise TokenPushError()
    try:
        missing: list[Path] = []
        cursor = path
        while not cursor.exists():
            missing.append(cursor)
            cursor = cursor.parent
        for directory in reversed(missing):
            directory.mkdir(mode=0o700)
            parent_fd = os.open(
                directory.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            )
            try:
                os.fsync(parent_fd)
            finally:
                os.close(parent_fd)
        info = path.stat(follow_symlinks=False)
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != 0o700
        ):
            raise TokenPushError()
    except TokenPushError:
        raise
    except Exception:
        raise TokenPushError() from None


@dataclass(frozen=True)
class _Pointer:
    generation_id: str
    operation_id: str
    relative_path: str


class TokenPushStore:
    """Per-channel private journal, lock, immutable encrypted generations and pointer."""

    def __init__(self, state_root: Path, channel: str) -> None:
        if not state_root.is_absolute() or channel not in {"dev", "test", "prod"}:
            raise TokenPushError()
        self.state_root = state_root
        self.channel = channel
        self.journal_directory = state_root / "bws-token-push" / channel
        self.credential_directory = state_root / "bws-tokens" / channel

    @contextmanager
    def locked(self) -> Iterator[None]:
        _secure_directory(self.journal_directory)
        _secure_directory(self.credential_directory)
        _secure_directory(self.credential_directory / "generations")
        descriptor = None
        try:
            descriptor = os.open(
                self.journal_directory / "operation.lock",
                os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                0o600,
            )
            info = os.fstat(descriptor)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_nlink != 1
            ):
                raise TokenPushError()
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        except TokenPushError:
            raise
        except Exception:
            raise TokenPushError() from None
        finally:
            if descriptor is not None:
                os.close(descriptor)

    @property
    def journal_path(self) -> Path:
        return self.journal_directory / "operation.json"

    def read(self) -> TokenPushReceipt | None:
        try:
            descriptor = os.open(
                self.journal_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
            )
        except FileNotFoundError:
            return None
        except Exception:
            raise TokenPushError() from None
        with os.fdopen(descriptor, "r", encoding="utf-8") as source:
            info = os.fstat(source.fileno())
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_nlink != 1
                or info.st_size > 4096
            ):
                raise TokenPushError()
            receipt = _receipt_from_mapping(json.load(source))
            if receipt.channel != self.channel:
                raise TokenPushError()
            return receipt

    def write(self, receipt: TokenPushReceipt) -> None:
        receipt.validate()
        if receipt.channel != self.channel:
            raise TokenPushError()
        temporary = self.journal_directory / (".operation-" + str(uuid4()) + ".tmp")
        raw = (json.dumps(asdict(receipt), sort_keys=True) + "\n").encode("utf-8")
        descriptor = None
        try:
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
            )
            if os.write(descriptor, raw) != len(raw):
                raise TokenPushError()
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = None
            os.replace(temporary, self.journal_path)
            directory_fd = os.open(self.journal_directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except TokenPushError:
            raise
        except Exception:
            raise TokenPushError() from None
        finally:
            if descriptor is not None:
                os.close(descriptor)
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def current(self) -> _Pointer | None:
        path = self.credential_directory / "current"
        try:
            relative = os.readlink(path)
        except FileNotFoundError:
            return None
        except Exception:
            raise TokenPushError() from None
        match = _GENERATION_PATTERN.fullmatch(relative)
        if match is None:
            raise TokenPushError()
        generation_id, operation_id = match.groups()
        for value in (generation_id, operation_id):
            if str(UUID(value)) != value:
                raise TokenPushError()
        generation = self.credential_directory / relative
        try:
            info = generation.stat(follow_symlinks=False)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_nlink != 1
                or info.st_size < 1
            ):
                raise TokenPushError()
        except TokenPushError:
            raise
        except Exception:
            raise TokenPushError() from None
        return _Pointer(generation_id, operation_id, relative)

    def activate(self, pointer: _Pointer) -> None:
        temporary = self.credential_directory / (".current-" + str(uuid4()) + ".tmp")
        current = self.credential_directory / "current"
        try:
            os.symlink(pointer.relative_path, temporary)
            os.replace(temporary, current)
            directory_fd = os.open(
                self.credential_directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            )
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except Exception:
            raise TokenPushError() from None
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def install_generation(self, operation_id: str, generation_id: str, encrypted: bytes) -> _Pointer:
        if not encrypted or len(encrypted) > 1024 * 1024:
            raise TokenPushError()
        generation_directory = self.credential_directory / "generations"
        name = f"gen-{generation_id}-{operation_id}.cred"
        temporary = generation_directory / ("." + name + ".tmp")
        target = generation_directory / name
        descriptor = None
        try:
            descriptor = os.open(
                temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
            )
            if os.write(descriptor, encrypted) != len(encrypted):
                raise TokenPushError()
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = None
            os.link(temporary, target, follow_symlinks=False)
            temporary.unlink()
            directory_fd = os.open(
                generation_directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            )
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except TokenPushError:
            raise
        except Exception:
            raise TokenPushError() from None
        finally:
            if descriptor is not None:
                os.close(descriptor)
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
        return _Pointer(
            generation_id,
            operation_id,
            f"generations/{name}",
        )

    def restore(self, pointer: _Pointer | None) -> None:
        current = self.credential_directory / "current"
        if pointer is None:
            try:
                current.unlink()
            except FileNotFoundError:
                pass
            directory_fd = os.open(
                self.credential_directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            )
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            return
        self.activate(pointer)


def _token_push_unit(channel: str, operation_id: str, attempt_id: str) -> str:
    for value in (operation_id, attempt_id):
        if str(UUID(value)) != value:
            raise TokenPushError()
    if channel not in {"dev", "test", "prod"}:
        raise TokenPushError()
    return f"yggdrasil-bws-token-push-{channel}-{operation_id}-{attempt_id}.service"


def _command(
    argv: list[str],
    *,
    input_bytes: bytes | None = None,
    runner: CommandRunner = subprocess.run,
) -> subprocess.CompletedProcess[bytes]:
    try:
        return runner(argv, input=input_bytes, capture_output=True, check=False)
    except Exception:
        raise TokenPushError() from None


def _wait_for_unit(channel: str, receipt: TokenPushReceipt, runner: CommandRunner) -> None:
    unit = _token_push_unit(channel, receipt.operation_id, receipt.attempt_id)
    while True:
        result = _command(
            ["systemctl", "show", unit, "--property=ActiveState", "--value"],
            runner=runner,
        )
        state = result.stdout.decode("utf-8", errors="strict").strip()
        if result.returncode != 0:
            raise TokenPushError()
        if state in {"inactive", "failed"}:
            return
        if state not in _ACTIVE_SYSTEMD_STATES:
            raise TokenPushError()
        time.sleep(0.25)


class VmChannelMutationLock:
    """Reuse the deployment channel mkdir/flock admission on the VM."""

    def __init__(self, app_root: Path, channel: str) -> None:
        self.path = app_root / "config" / "deploy" / f"{channel}.env.lock"
        self.descriptor: int | None = None
        self.acquired = False

    def __enter__(self) -> VmChannelMutationLock:
        try:
            self.path.mkdir(mode=0o700)
        except FileExistsError:
            return self
        except Exception:
            raise TokenPushError() from None
        try:
            self.descriptor = os.open(
                self.path / "bws-owner",
                os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
            )
            fcntl.flock(self.descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.acquired = True
            return self
        except Exception:
            if self.descriptor is not None:
                os.close(self.descriptor)
                self.descriptor = None
            try:
                (self.path / "bws-owner").unlink()
                self.path.rmdir()
            except Exception:
                pass
            raise TokenPushError() from None

    def __exit__(self, *_: object) -> None:
        if self.descriptor is not None:
            os.close(self.descriptor)
            self.descriptor = None
        if self.acquired:
            try:
                (self.path / "bws-owner").unlink()
                self.path.rmdir()
            except Exception:
                # Retaining a stale lock is safer than admitting another writer.
                pass
            self.acquired = False


def _systemd_encrypt(token: str, runner: CommandRunner) -> bytes:
    token_bytes = token.encode("utf-8")
    encrypted = _command(
        ["systemd-creds", "encrypt", "--with-key=host", f"--name={_CREDENTIAL_NAME}", "-", "-"],
        input_bytes=token_bytes,
        runner=runner,
    )
    if encrypted.returncode != 0 or not encrypted.stdout:
        raise TokenPushError()
    decrypted = _command(
        ["systemd-creds", "decrypt", f"--name={_CREDENTIAL_NAME}", "-", "-"],
        input_bytes=encrypted.stdout,
        runner=runner,
    )
    if decrypted.returncode != 0 or decrypted.stdout != token_bytes:
        raise TokenPushError()
    return encrypted.stdout


def _write_stage(
    store: TokenPushStore,
    receipt: TokenPushReceipt,
    stage: str,
    *,
    generation_id: str | None = None,
    terminal_result: str | None = None,
) -> TokenPushReceipt:
    updated = TokenPushReceipt(
        receipt.operation_id,
        receipt.channel,
        "token-push",
        stage,
        terminal_result,
        receipt.attempt_id,
        receipt.prior_generation,
        generation_id,
    )
    updated.validate()
    store.write(updated)
    return updated


def _terminal_pointer_matches(store: TokenPushStore, receipt: TokenPushReceipt) -> bool:
    pointer = store.current()
    if receipt.stage == "committed":
        return bool(
            pointer
            and pointer.generation_id == receipt.generation_id
            and pointer.operation_id == receipt.operation_id
        )
    if receipt.stage == "aborted":
        return (pointer.generation_id if pointer else None) == receipt.prior_generation
    return False


def vm_token_push_worker(
    *,
    app_root: Path,
    state_root: Path = Path("/var/lib/yggdrasil"),
    channel: str,
    operation_id: str,
    attempt_id: str,
    source: object,
    runner: CommandRunner = subprocess.run,
) -> TokenPushReceipt:
    """Apply one attempt under the remote journal and deployment channel locks."""
    try:
        if not isinstance(source, str) or not validate_reader_token(source):
            raise TokenPushError()
        store = TokenPushStore(state_root, channel)
        with store.locked():
            receipt = store.read()
            if (
                receipt is None
                or receipt.operation_id != operation_id
                or receipt.attempt_id != attempt_id
                or receipt.stage != "prepared"
            ):
                raise TokenPushError()
            prior_pointer = store.current()
            if (prior_pointer.generation_id if prior_pointer else None) != receipt.prior_generation:
                raise TokenPushError()
            channel_lock = VmChannelMutationLock(app_root, channel)
            with channel_lock:
                if not channel_lock.acquired:
                    _write_stage(store, receipt, "aborted", terminal_result="aborted")
                    aborted = store.read()
                    if aborted is None or not _terminal_pointer_matches(store, aborted):
                        raise TokenPushError()
                    return aborted

                applying: TokenPushReceipt | None = None
                generation_id: str | None = None
                pointer_attempted = False
                try:
                    encrypted = _systemd_encrypt(source, runner)  # type: ignore[arg-type]
                    generation_id = str(uuid4())
                    applying = _write_stage(
                        store, receipt, "applying", generation_id=generation_id
                    )
                    candidate = store.install_generation(
                        operation_id, generation_id, encrypted
                    )
                    pointer_attempted = True
                    store.activate(candidate)
                    selected = store.current()
                    if (
                        selected is None
                        or selected.generation_id != generation_id
                        or selected.operation_id != operation_id
                    ):
                        raise TokenPushError()
                    committed = _write_stage(
                        store,
                        applying,
                        "committed",
                        generation_id=generation_id,
                        terminal_result="committed",
                    )
                    if not _terminal_pointer_matches(store, committed):
                        raise TokenPushError()
                    return committed
                except Exception:
                    # Only close an attempt after proving the prior pointer is
                    # current. Once pointer mutation was attempted, restore it
                    # under the same locks before writing a terminal abort.
                    try:
                        latest = store.read()
                        if (
                            latest is None
                            or latest.operation_id != operation_id
                            or latest.attempt_id != attempt_id
                        ):
                            raise TokenPushError()
                        if latest.stage == "prepared":
                            current = store.current()
                            if (current.generation_id if current else None) != latest.prior_generation:
                                raise TokenPushError()
                            aborted = _write_stage(
                                store, latest, "aborted", terminal_result="aborted"
                            )
                            if not _terminal_pointer_matches(store, aborted):
                                raise TokenPushError()
                            return aborted
                        if latest.stage != "applying":
                            raise TokenPushError()
                        current = store.current()
                        if pointer_attempted:
                            if (
                                generation_id is not None
                                and current is not None
                                and current.generation_id == generation_id
                                and current.operation_id == operation_id
                            ):
                                store.restore(prior_pointer)
                            elif (current.relative_path if current else None) != (
                                prior_pointer.relative_path if prior_pointer else None
                            ):
                                raise TokenPushError()
                        current = store.current()
                        if (current.relative_path if current else None) != (
                            prior_pointer.relative_path if prior_pointer else None
                        ):
                            raise TokenPushError()
                        aborted = _write_stage(
                            store,
                            latest,
                            "aborted",
                            terminal_result="aborted",
                        )
                        if not _terminal_pointer_matches(store, aborted):
                            raise TokenPushError()
                        return aborted
                    except Exception:
                        raise TokenPushError() from None
    except TokenPushError:
        raise
    except Exception:
        raise TokenPushError() from None


def _encode_receipt(receipt: TokenPushReceipt) -> str:
    receipt.validate()
    return json.dumps(asdict(receipt), sort_keys=True)


def vm_token_push_inspect(
    *, state_root: Path = Path("/var/lib/yggdrasil"), channel: str
) -> dict[str, str | None]:
    store = TokenPushStore(state_root, channel)
    with store.locked():
        receipt = store.read()
        if receipt is not None:
            if receipt.terminal_result is None or not _terminal_pointer_matches(store, receipt):
                raise TokenPushError()
        pointer = store.current()
        return {"generation_id": pointer.generation_id if pointer else None}


def _run_supervised_worker(
    *,
    channel: str,
    operation_id: str,
    attempt_id: str,
    token: str,
    runner: CommandRunner,
    launcher: str = "/usr/local/libexec/yggdrasil-bws-deploy",
) -> None:
    unit = _token_push_unit(channel, operation_id, attempt_id)
    result = _command(
        [
            "systemd-run", "--quiet", "--pipe", "--wait", "--collect",
            f"--unit={unit}", "--property=Type=oneshot",
            "--property=TimeoutStartSec=infinity", "--property=TimeoutStopSec=infinity",
            "--", launcher, "token-push-worker", channel, operation_id, attempt_id,
        ],
        input_bytes=token.encode("utf-8"),
        runner=runner,
    )
    if result.returncode != 0:
        raise TokenPushError()


def vm_token_push_start(
    *,
    app_root: Path,
    channel: str,
    operation_id: str,
    attempt_id: str,
    prior_generation: str | None,
    source: object,
    state_root: Path = Path("/var/lib/yggdrasil"),
    runner: CommandRunner = subprocess.run,
    launcher: str = "/usr/local/libexec/yggdrasil-bws-deploy",
) -> TokenPushReceipt:
    """Persist the remote prepared receipt before dispatching a systemd worker."""
    try:
        if (
            source is None
            or not validate_reader_token(source)  # type: ignore[arg-type]
            or (prior_generation is not None and str(UUID(prior_generation)) != prior_generation)
        ):
            raise TokenPushError()
        store = TokenPushStore(state_root, channel)
        with store.locked():
            pointer = store.current()
            if (pointer.generation_id if pointer else None) != prior_generation:
                raise TokenPushError()
            previous = store.read()
            if previous is not None:
                if previous.terminal_result is None:
                    raise TokenPushError()
                if not _terminal_pointer_matches(store, previous):
                    raise TokenPushError()
                if previous.operation_id == operation_id and previous.stage == "committed":
                    return previous
                if previous.operation_id == operation_id and previous.stage != "aborted":
                    raise TokenPushError()
            prepared = TokenPushReceipt(
                operation_id,
                channel,
                "token-push",
                "prepared",
                None,
                attempt_id,
                prior_generation,
                None,
            )
            prepared.validate()
            store.write(prepared)
        _run_supervised_worker(
            channel=channel,
            operation_id=operation_id,
            attempt_id=attempt_id,
            token=source,  # type: ignore[arg-type]
            runner=runner,
            launcher=launcher,
        )
        with store.locked():
            receipt = store.read()
            if (
                receipt is None
                or receipt.operation_id != operation_id
                or receipt.attempt_id != attempt_id
            ):
                raise TokenPushError()
            if receipt.terminal_result is not None and _terminal_pointer_matches(store, receipt):
                return receipt
            raise TokenPushError()
    except TokenPushError:
        raise
    except Exception:
        raise TokenPushError() from None


def vm_token_push_status(
    *,
    state_root: Path = Path("/var/lib/yggdrasil"),
    channel: str,
    operation_id: str,
    runner: CommandRunner = subprocess.run,
) -> TokenPushReceipt:
    """Join an active unit, then reconcile only a durable matching terminal receipt."""
    try:
        store = TokenPushStore(state_root, channel)
        with store.locked():
            observed = store.read()
            if observed is None or observed.operation_id != operation_id:
                # Absence or another operation's receipt is explicitly indeterminate.
                raise TokenPushError()
            if observed.terminal_result is not None:
                if not _terminal_pointer_matches(store, observed):
                    raise TokenPushError()
                return observed
        _wait_for_unit(channel, observed, runner)
        with store.locked():
            receipt = store.read()
            if receipt is None or receipt.operation_id != operation_id:
                raise TokenPushError()
            if receipt.stage == "prepared":
                # The same-ID worker verifies attempt_id and stage while holding
                # this lock, so a late unit cannot act after this durable abort.
                current = store.current()
                if (current.generation_id if current else None) != receipt.prior_generation:
                    raise TokenPushError()
                receipt = _write_stage(
                    store, receipt, "aborted", terminal_result="aborted"
                )
            if receipt.terminal_result is None or not _terminal_pointer_matches(store, receipt):
                raise TokenPushError()
            return receipt
    except TokenPushError:
        raise
    except Exception:
        raise TokenPushError() from None


def read_remote_token(source: TextIO) -> str:
    """Read one bounded token from stdin without placing it in diagnostics."""
    try:
        value = source.read(4097)
        if not isinstance(value, str) or not validate_reader_token(value) or len(value.encode()) > 4096:
            raise TokenPushError()
        if source.read(1):
            raise TokenPushError()
        return value
    except TokenPushError:
        raise
    except Exception:
        raise TokenPushError() from None


def remote_main(
    argv: list[str],
    *,
    app_root: Path,
    input_stream: TextIO | None = None,
    runner: CommandRunner = subprocess.run,
) -> int:
    """VM-side actions called only by the installed root-owned launcher."""
    import argparse

    parser = argparse.ArgumentParser(prog="yggdrasil-bws-token-push")
    parser.add_argument(
        "action", choices=("token-push", "token-push-worker", "token-push-status", "token-push-inspect")
    )
    parser.add_argument("channel", choices=("dev", "test", "prod"))
    parser.add_argument("operation_id", nargs="?")
    parser.add_argument("attempt_id", nargs="?")
    parser.add_argument("prior_generation", nargs="?")
    try:
        args = parser.parse_args(argv)
        source = input_stream if input_stream is not None else sys.stdin
        if args.action == "token-push-inspect" and args.operation_id is None:
            result = vm_token_push_inspect(channel=args.channel)
            print(json.dumps(result, sort_keys=True))
        elif args.action == "token-push-status" and args.operation_id and not args.attempt_id:
            receipt = vm_token_push_status(
                channel=args.channel, operation_id=args.operation_id, runner=runner
            )
            print(_encode_receipt(receipt))
        elif args.action == "token-push" and args.operation_id and args.attempt_id and args.prior_generation:
            token = read_remote_token(source)
            receipt = vm_token_push_start(
                app_root=app_root,
                channel=args.channel,
                operation_id=args.operation_id,
                attempt_id=args.attempt_id,
                prior_generation=None if args.prior_generation == "absent" else args.prior_generation,
                source=token,
                runner=runner,
            )
            del token
            print(_encode_receipt(receipt))
        elif args.action == "token-push-worker" and args.operation_id and args.attempt_id and not args.prior_generation:
            token = read_remote_token(source)
            vm_token_push_worker(
                app_root=app_root,
                channel=args.channel,
                operation_id=args.operation_id,
                attempt_id=args.attempt_id,
                source=token,
                runner=runner,
            )
            del token
        else:
            raise TokenPushError()
        return 0
    except Exception:
        print("reader-token operation refused; status may remain pending", file=sys.stderr)
        return 78
