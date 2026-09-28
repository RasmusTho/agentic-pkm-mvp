"""Host-local BWS admission. This lock is not cross-host/provider fencing.

Only cooperating entrypoints are serialized. No exception, timeout, lock release,
marker or generation pointer can terminate a possibly applied remote mutation.
Operation-specific callers must obtain authoritative evidence before finish/reconcile.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import json
import os
from pathlib import Path
import stat
from uuid import UUID, uuid4


class HostSecretAdmissionError(RuntimeError):
    def __init__(self) -> None:
        super().__init__(
            "host secret operation refused; admission or terminal evidence unavailable"
        )


_KINDS = {"check", "import", "token-push", "deploy", "bootstrap"}
_TARGETS = {"dev", "test", "prod", "shared"}
_TERMINAL_SOURCES = {
    "check": "read-complete",
    "import": "provider-terminal",
    "bootstrap": "provider-terminal",
    "token-push": "remote-terminal",
    "deploy": "remote-terminal",
}


@dataclass(frozen=True)
class TerminalEvidence:
    operation_id: str
    kind: str
    target: str
    result: str
    source: str


class HostSecretOperation:
    def __init__(self, journal_fd: int, operation_id: str, kind: str, target: str) -> None:
        self._journal_fd = journal_fd
        self.operation_id = operation_id
        self.kind = kind
        self.target = target
        self._finished = False
        self._active = True

    def _record(self, stage: str, source: str | None = None) -> None:
        if not self._active or self._finished:
            raise HostSecretAdmissionError()
        record = {
            "operation_id": self.operation_id,
            "kind": self.kind,
            "target": self.target,
            "stage": stage,
            "source": source,
        }
        raw = (json.dumps(record, sort_keys=True) + "\n").encode()
        # A partial write or failed fsync leaves a poison/pending journal, never admission.
        if os.write(self._journal_fd, raw) != len(raw):
            raise HostSecretAdmissionError()
        os.fsync(self._journal_fd)

    def require_active(self, target: str) -> None:
        if not self._active or self._finished or self.target != target:
            raise HostSecretAdmissionError()
        os.fstat(self._journal_fd)

    def prepare_mutation(self) -> None:
        """Persist before the first remote effect; caller already holds the host lock."""
        if self.kind == "check":
            raise HostSecretAdmissionError()
        self._record("sent")

    def finish(self, evidence: TerminalEvidence) -> None:
        if (
            evidence.operation_id != self.operation_id
            or evidence.kind != self.kind
            or evidence.target != self.target
            or evidence.result not in {"committed", "aborted"}
            or evidence.source != _TERMINAL_SOURCES[self.kind]
        ):
            raise HostSecretAdmissionError()
        self._record(evidence.result, evidence.source)
        self._finished = True


class HostSecretController:
    """One stable lock and append-only value-free journal, outside Git/iCloud.

    `directory` is for isolated fixture controllers. Production uses one fixed
    per-owner state path; downstream entrypoints must share this controller.
    """

    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory or Path.home() / ".local/state/yggdrasil/secret-controller"

    @contextmanager
    def _locked_journal(self) -> Iterator[int]:
        directory_fd = lock_fd = journal_fd = None
        try:
            path = self.directory
            if not path.is_absolute() or any(
                part in {"Mobile Documents", "CloudStorage", ".git"} for part in path.parts
            ):
                raise HostSecretAdmissionError()
            # Reject symlinked ancestry and every repository, even untracked subdirectories.
            for parent in (path, *path.parents):
                if parent.is_symlink() or (parent / ".git").exists():
                    raise HostSecretAdmissionError()
            path.mkdir(mode=0o700, parents=True, exist_ok=True)
            directory_fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            info = os.fstat(directory_fd)
            if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
                raise HostSecretAdmissionError()
            lock_fd = self._open_file(directory_fd, "operation.lock")
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise HostSecretAdmissionError() from None
            journal_fd = self._open_file(directory_fd, "operations.jsonl")
            os.fsync(directory_fd)
            yield journal_fd
        except HostSecretAdmissionError:
            raise
        except Exception:
            raise HostSecretAdmissionError() from None
        finally:
            for descriptor in (journal_fd, lock_fd, directory_fd):
                if descriptor is not None:
                    os.close(descriptor)

    @staticmethod
    def _open_file(directory_fd: int, name: str) -> int:
        descriptor = os.open(
            name,
            os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW | os.O_NONBLOCK,
            0o600,
            dir_fd=directory_fd,
        )
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_nlink != 1
        ):
            os.close(descriptor)
            raise HostSecretAdmissionError()
        return descriptor

    @staticmethod
    def _pending(descriptor: int) -> dict[str, str | None] | None:
        os.lseek(descriptor, 0, os.SEEK_SET)
        with os.fdopen(os.dup(descriptor), "r", encoding="utf-8") as source:
            pending = None
            seen: set[str] = set()
            for line in source:
                if not line.endswith("\n"):
                    raise HostSecretAdmissionError()
                record = json.loads(line)
                if (
                    not isinstance(record, dict)
                    or set(record) != {"operation_id", "kind", "target", "stage", "source"}
                    or record["kind"] not in _KINDS
                    or record["target"] not in _TARGETS
                    or str(UUID(record["operation_id"])) != record["operation_id"]
                ):
                    raise HostSecretAdmissionError()
                if record["stage"] == "prepared":
                    if (
                        pending is not None
                        or record["operation_id"] in seen
                        or record["source"] is not None
                    ):
                        raise HostSecretAdmissionError()
                    seen.add(record["operation_id"])
                    pending = record
                else:
                    if pending is None or any(
                        record[k] != pending[k] for k in ("operation_id", "kind", "target")
                    ):
                        raise HostSecretAdmissionError()
                    if (
                        record["stage"] == "sent"
                        and record["source"] is None
                        and record["kind"] != "check"
                    ):
                        continue
                    if (
                        record["stage"] not in {"committed", "aborted"}
                        or record["source"] != _TERMINAL_SOURCES[record["kind"]]
                    ):
                        raise HostSecretAdmissionError()
                    pending = None
            return pending

    @contextmanager
    def admit(self, kind: str, target: str) -> Iterator[HostSecretOperation]:
        if (
            kind not in _KINDS
            or target not in _TARGETS
            or (target == "shared" and kind not in {"check", "import"})
        ):
            raise HostSecretAdmissionError()
        with self._locked_journal() as descriptor:
            if self._pending(descriptor) is not None:
                raise HostSecretAdmissionError()
            operation = HostSecretOperation(descriptor, str(uuid4()), kind, target)
            operation._record("prepared")
            try:
                yield operation
            finally:
                # Never clear a pending operation merely because the process unwound.
                operation._active = False

    def reconcile(self, readback: Callable[[str, str, str], TerminalEvidence]) -> None:
        """Read authoritative operation-specific terminal evidence under the host lock.

        Downstream adapters own authentication, durable receipt and provider terminality
        checks. No public CLI accepts caller assertions as terminal evidence.
        """
        with self._locked_journal() as descriptor:
            pending = self._pending(descriptor)
            if pending is None:
                raise HostSecretAdmissionError()
            operation = HostSecretOperation(
                descriptor,
                str(pending["operation_id"]),
                str(pending["kind"]),
                str(pending["target"]),
            )
            try:
                evidence = readback(operation.operation_id, operation.kind, operation.target)
                operation.finish(evidence)
            finally:
                operation._active = False
