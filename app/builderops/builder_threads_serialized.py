"""Serialized, non-authoritative Builder Thread exchange.

The process that creates :class:`SerializedThreadWriter` is the designated
BuilderOps/Mac mini writer.  Clients only receive an endpoint; this module has
no client filesystem API and deliberately never discovers a vault path.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Literal, Protocol, cast


PRIVACY_CLASS: Literal["shared_non_sensitive"] = "shared_non_sensitive"
_IDENTITY = re.compile(r"^[a-z][a-z0-9_-]{1,31}:[A-Za-z0-9._:-]{2,119}$")
_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SOURCE_REF = re.compile(
    r"^(?:builderops|conversation|doc|git|github):[A-Za-z0-9._:/#@+-]{1,255}$"
)
_PRIVATE_CONTENT = re.compile(
    r"(?im)(password|secret|credential|token|api[_-]?key|bearer\s+|"
    r"(?:~/.ssh|/(?:Users|home|private|root|etc|var|opt)/)|"
    r"^aws_(?:access_key_id|secret_access_key)\s*=|"
    r"^authorization:\s*(?:basic|bearer)\b|^-----begin [a-z ]+private key-----|"
    r"\bAKIA[0-9A-Z]{16}\b|\bgithub_pat_[A-Za-z0-9_]{20,}|"
    r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b)"
)
_CODE_OR_PATCH = re.compile(
    r"(?im)^(?:diff --git |--- a/|\+\+\+ b/|@@ |```|"
    r"\s*(?:def|class|function|const|let|var|import|from|package|func)\b|"
    r"\s*console\.(?:log|error|warn)\s*\(|\s*git diff(?:\s|$)|"
    r"\s*(?:print|return|throw|await|yield)\b\s*(?:\(|[a-z_$])|"
    r"\s*lambda\s+[^:\n]+:|\s*if\s+[^:\n]+:\s*$|"
    r"\s*[a-z_$][a-z0-9_$]*\s*=\s*(?:\([^)]*\)|[a-z_$][a-z0-9_$]*)\s*=>)"
)
_MAX_TEXT = 500
_MAX_THREAD_ENTRIES = 32
_MAX_TOTAL_ENTRIES = 100
_ROOT_IDENTITY = "builder-thread-writer.json"
_ENTRY_DIRECTORY = "builder-thread-entries"
_REPOSITORY_VAULT_ROOT = (Path(__file__).resolve().parents[2] / "vault").resolve()
_WRITER_ROOT_ENV = "BUILDEROPS_THREAD_WRITER_ROOT"
_WRITER_VAULT_ID_ENV = "BUILDEROPS_THREAD_WRITER_VAULT_ID"
_SEQUENCE_RESERVATION = ".builder-thread-sequence.lock"
_ROOT_RESERVATION_GUARD = threading.Lock()
_ROOT_RESERVATIONS: dict[Path, threading.Lock] = {}


class BuilderThreadError(ValueError):
    """A bounded refusal at the Builder Thread boundary."""


class WriterUnavailableError(BuilderThreadError):
    """The designated writer cannot currently accept or serve a request."""


class WriterHostConfigurationError(WriterUnavailableError):
    """The designated writer host lacks its required external-root settings."""


class WriterAcknowledgementLost(WriterUnavailableError):
    """The writer may have accepted a request but its caller got no result."""


class RequestReplayConflictError(BuilderThreadError):
    """A caller reused its request ID for changed semantics."""


class ThreadAlreadyRepresentedError(BuilderThreadError):
    """The create capture key already has a durable Builder Thread."""


@contextmanager
def _external_mutation_reservation(entries_root: Path) -> Iterator[None]:
    """Reserve one durable sequence allocation across writer hosts on this filesystem."""
    lock_path = (entries_root / _SEQUENCE_RESERVATION).resolve()
    with _ROOT_RESERVATION_GUARD:
        process_lock = _ROOT_RESERVATIONS.setdefault(lock_path, threading.Lock())
    if not process_lock.acquire(blocking=False):
        raise WriterUnavailableError("serialized writer overlap is unavailable")

    descriptor: int | None = None
    try:
        try:
            descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise WriterUnavailableError("serialized writer overlap is unavailable") from exc
        yield
    finally:
        if descriptor is not None:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)
        process_lock.release()


def initialize_external_writer_root(root: Path, *, vault_id: str) -> None:
    """Explicitly initialise the external writer-owned root for one vault ID."""
    _validate_identifier(vault_id, field="vault_id")
    _reject_repository_fixture_root(root)
    root.mkdir(parents=True, exist_ok=True)
    identity = root / _ROOT_IDENTITY
    expected = _canonical_json({"schema": "builder-thread-writer.v1", "vault_id": vault_id})
    if identity.exists():
        if identity.is_symlink() or identity.read_bytes() != expected:
            raise BuilderThreadError("external writer root identity conflicts")
    else:
        identity.write_bytes(expected)
    entries = root / _ENTRY_DIRECTORY
    entries.mkdir(exist_ok=True)
    if entries.is_symlink() or not entries.is_dir():
        raise BuilderThreadError("external writer entry directory is unavailable")


@dataclass(frozen=True)
class ThreadEntry:
    request_id: str
    kind: Literal["create", "reply", "close", "archive"]
    actor: str
    recipient: str | None
    content: str | None
    source_refs: tuple[str, ...]


@dataclass(frozen=True)
class BuilderThread:
    thread_id: str
    vault_id: str
    subject: str
    reply_expected: Literal[True]
    privacy_class: Literal["shared_non_sensitive"]
    state: Literal["open", "closed", "archived"]
    entries: tuple[ThreadEntry, ...]


@dataclass(frozen=True)
class ThreadMutation:
    request_id: str
    kind: Literal["create", "reply", "close", "archive"]
    actor: str
    thread_id: str | None = None
    recipient: str | None = None
    subject: str | None = None
    content: str | None = None
    source_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class ThreadMutationResult:
    thread: BuilderThread
    replayed: bool


@dataclass(frozen=True)
class BuilderInbox:
    recipient: str
    threads: tuple["BuilderThreadSummary", ...]
    truncated: bool


@dataclass(frozen=True)
class BuilderThreadSummary:
    thread_id: str
    subject: str
    state: Literal["open", "closed", "archived"]
    entry_count: int
    last_actor: str
    last_recipient: str | None
    last_source_refs: tuple[str, ...]


class WriterEndpoint(Protocol):
    """The only client capability: submit a command or read a projection."""

    def mutate(self, command: ThreadMutation) -> ThreadMutationResult: ...

    def read_thread(self, thread_id: str) -> BuilderThread: ...

    def inbox(self, recipient: str, *, limit: int) -> BuilderInbox: ...


class SerializedThreadWriter:
    """One host-local writer for immutable external Builder Thread contributions.

    The designated BuilderOps/Mac mini host initializes and owns ``state_root``
    outside this repository. Keeping mutation authority in this object avoids
    pretending that two clients can coordinate direct writes to an
    iCloud-synchronised file tree.
    """

    def __init__(self, *, vault_id: str, state_root: Path) -> None:
        _validate_identifier(vault_id, field="vault_id")
        _reject_repository_fixture_root(state_root)
        self._vault_id = vault_id
        self._state_root = state_root
        self._entries_root = state_root / _ENTRY_DIRECTORY
        self._threads: dict[str, BuilderThread] = {}
        self._request_digests: dict[str, str] = {}
        self._request_results: dict[str, BuilderThread] = {}
        self._capture_index: dict[str, str] = {}
        self._accepted_mutation_count = 0
        self._persistence_unavailable = False
        self._lock = threading.RLock()
        self._verify_external_root()
        self._restore_external_state()

    @property
    def accepted_mutation_count(self) -> int:
        return self._accepted_mutation_count

    def mutate(self, command: ThreadMutation) -> ThreadMutationResult:
        """Validate and apply exactly one command in the designated process."""
        with self._lock:
            _validate_command(command)
            if self._persistence_unavailable:
                raise WriterUnavailableError("serialized writer persistence is unavailable")
            with _external_mutation_reservation(self._entries_root):
                # A separately restored host has a stale in-memory sequence. Rebuild
                # under the shared reservation before allocating the next durable slot.
                self._restore_external_state()
                request_digest = _command_digest(command)
                previous_digest = self._request_digests.get(command.request_id)
                if previous_digest is not None:
                    if previous_digest != request_digest:
                        raise RequestReplayConflictError(
                            "request id reuse conflicts with accepted semantics"
                        )
                    return ThreadMutationResult(
                        thread=self._request_results[command.request_id], replayed=True
                    )

                if self._accepted_mutation_count >= _MAX_TOTAL_ENTRIES:
                    raise BuilderThreadError("serialized writer contribution bound reached")
                threads_before_write = self._threads.copy()
                capture_index_before_write = self._capture_index.copy()
                if command.kind == "create":
                    thread = self._create(command)
                else:
                    thread = self._append(command)
                try:
                    self._persist(
                        command,
                        request_digest,
                        sequence=self._accepted_mutation_count + 1,
                    )
                except OSError as exc:
                    self._threads = threads_before_write
                    self._capture_index = capture_index_before_write
                    self._persistence_unavailable = True
                    raise WriterUnavailableError(
                        "serialized writer persistence is unavailable"
                    ) from exc
                self._record(command, request_digest, thread)
                return ThreadMutationResult(thread=thread, replayed=False)

    def read_thread(self, thread_id: str) -> BuilderThread:
        _validate_identifier(thread_id, field="thread_id")
        with self._lock:
            try:
                return self._threads[thread_id]
            except KeyError as exc:
                raise BuilderThreadError("thread is unavailable") from exc

    def inbox(self, recipient: str, *, limit: int) -> BuilderInbox:
        _validate_identity(recipient, field="recipient")
        if not 1 <= limit <= 100:
            raise BuilderThreadError("inbox limit must be between 1 and 100")
        with self._lock:
            matching = tuple(
                _summary(thread)
                for thread in self._threads.values()
                if thread.state == "open"
                and any(entry.recipient == recipient for entry in thread.entries)
            )
        return BuilderInbox(
            recipient=recipient,
            threads=matching[:limit],
            truncated=len(matching) > limit,
        )

    def _create(self, command: ThreadMutation) -> BuilderThread:
        assert command.recipient is not None
        assert command.subject is not None
        capture_key = _capture_key(command.recipient, command.subject, command.source_refs)
        if capture_key in self._capture_index:
            raise ThreadAlreadyRepresentedError("capture already has a durable Builder Thread")
        thread_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{self._vault_id}:{capture_key}"))
        entry = ThreadEntry(
            request_id=command.request_id,
            kind="create",
            actor=command.actor,
            recipient=command.recipient,
            content=command.content,
            source_refs=command.source_refs,
        )
        thread = BuilderThread(
            thread_id=thread_id,
            vault_id=self._vault_id,
            subject=command.subject,
            reply_expected=True,
            privacy_class=PRIVACY_CLASS,
            state="open",
            entries=(entry,),
        )
        self._threads[thread_id] = thread
        self._capture_index[capture_key] = thread_id
        return thread

    def _append(self, command: ThreadMutation) -> BuilderThread:
        assert command.thread_id is not None
        current = self.read_thread(command.thread_id)
        if len(current.entries) >= _MAX_THREAD_ENTRIES:
            raise BuilderThreadError("thread contribution bound reached")
        if command.kind == "reply":
            if current.state != "open":
                raise BuilderThreadError("only an open thread can receive a reply")
            next_state: Literal["open", "closed", "archived"] = "open"
        elif command.kind == "close":
            if current.state != "open":
                raise BuilderThreadError("only an open thread can close")
            opening_recipient = current.entries[0].recipient
            if not any(
                entry.kind == "reply" and entry.actor == opening_recipient
                for entry in current.entries
            ):
                raise BuilderThreadError(
                    "close requires a reply from the named recipient"
                )
            next_state = "closed"
        else:
            if current.state != "closed":
                raise BuilderThreadError("only a closed thread can archive")
            next_state = "archived"
        entry = ThreadEntry(
            request_id=command.request_id,
            kind=command.kind,
            actor=command.actor,
            recipient=command.recipient,
            content=command.content,
            source_refs=command.source_refs,
        )
        updated = BuilderThread(
            thread_id=current.thread_id,
            vault_id=current.vault_id,
            subject=current.subject,
            reply_expected=current.reply_expected,
            privacy_class=PRIVACY_CLASS,
            state=next_state,
            entries=(*current.entries, entry),
        )
        self._threads[current.thread_id] = updated
        return updated

    def _verify_external_root(self) -> None:
        identity = self._state_root / _ROOT_IDENTITY
        expected = _canonical_json({"schema": "builder-thread-writer.v1", "vault_id": self._vault_id})
        if (
            self._state_root.is_symlink()
            or identity.is_symlink()
            or not identity.is_file()
            or identity.read_bytes() != expected
            or self._entries_root.is_symlink()
            or not self._entries_root.is_dir()
        ):
            raise BuilderThreadError("external writer root is not the pinned vault identity")

    def _restore_external_state(self) -> None:
        self._threads = {}
        self._request_digests = {}
        self._request_results = {}
        self._capture_index = {}
        self._accepted_mutation_count = 0
        records: list[tuple[int, ThreadMutation, str]] = []
        for path in self._entries_root.glob("*.json"):
            if path.is_symlink():
                raise BuilderThreadError("external writer entry is unavailable")
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                sequence = payload["sequence"]
                command = _command_from_record(payload, vault_id=self._vault_id)
                if path.name != f"{command.request_id}.json":
                    raise ValueError("invalid writer entry identity")
                digest = payload["request_digest"]
                if not isinstance(sequence, int) or isinstance(sequence, bool):
                    raise ValueError("invalid writer sequence")
                if not isinstance(digest, str) or digest != _command_digest(command):
                    raise ValueError("invalid writer digest")
                _validate_command(command)
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise BuilderThreadError("external writer entry is invalid") from exc
            records.append((sequence, command, digest))
        if len(records) > _MAX_TOTAL_ENTRIES:
            raise BuilderThreadError("external writer contribution bound exceeded")
        for expected_sequence, (sequence, command, digest) in enumerate(
            sorted(records, key=lambda record: record[0]), start=1
        ):
            if sequence != expected_sequence:
                raise BuilderThreadError("external writer entry order conflicts")
            if command.request_id in self._request_digests:
                raise BuilderThreadError("external writer entry conflicts")
            thread = self._create(command) if command.kind == "create" else self._append(command)
            self._record(command, digest, thread)

    def _persist(self, command: ThreadMutation, request_digest: str, *, sequence: int) -> None:
        path = self._entries_root / f"{command.request_id}.json"
        payload = {
            "command": _command_record(command),
            "request_digest": request_digest,
            "sequence": sequence,
            "schema": "builder-thread-command.v1",
            "vault_id": self._vault_id,
        }
        temporary_path = self._entries_root / f".{path.name}.{uuid.uuid4().hex}.tmp"
        with temporary_path.open("xb") as handle:
            handle.write(_canonical_json(payload))
        os.link(temporary_path, path)
        try:
            temporary_path.unlink()
        except OSError:
            pass

    def _record(
        self, command: ThreadMutation, request_digest: str, thread: BuilderThread
    ) -> None:
        self._request_digests[command.request_id] = request_digest
        self._request_results[command.request_id] = thread
        self._accepted_mutation_count += 1


class BoundWriterEndpoint:
    """Host-issued endpoint capability bound to exactly one client identity."""

    def __init__(self, writer: SerializedThreadWriter, *, client_id: str) -> None:
        self._writer = writer
        _validate_identity(client_id, field="client_id")
        self._client_id = client_id
        self.mutation_count = 0

    def mutate(self, command: ThreadMutation) -> ThreadMutationResult:
        if command.actor != self._client_id:
            raise BuilderThreadError("actor must match the endpoint client identity")
        self.mutation_count += 1
        return self._writer.mutate(command)

    def read_thread(self, thread_id: str) -> BuilderThread:
        return self._writer.read_thread(thread_id)

    def inbox(self, recipient: str, *, limit: int) -> BuilderInbox:
        return self._writer.inbox(recipient, limit=limit)


class BuilderThreadWriterHost:
    """Production host factory; clients never read its external-root settings."""

    def __init__(self, writer: SerializedThreadWriter) -> None:
        self._writer = writer

    @classmethod
    def from_environment(cls) -> BuilderThreadWriterHost:
        root_value = os.getenv(_WRITER_ROOT_ENV, "").strip()
        vault_id = os.getenv(_WRITER_VAULT_ID_ENV, "").strip()
        if not root_value or not vault_id:
            raise WriterHostConfigurationError(
                f"{_WRITER_ROOT_ENV} and {_WRITER_VAULT_ID_ENV} are required on the writer host"
            )
        root = Path(root_value)
        initialize_external_writer_root(root, vault_id=vault_id)
        return cls(SerializedThreadWriter(vault_id=vault_id, state_root=root))

    def endpoint_for(self, client_id: str) -> BoundWriterEndpoint:
        return BoundWriterEndpoint(self._writer, client_id=client_id)


# Compatibility alias for focused in-process contract tests. Production host
# construction is :meth:`BuilderThreadWriterHost.from_environment`.
InProcessWriterEndpoint = BoundWriterEndpoint


class BuilderThreadClient:
    """Codex/Claude client restricted to the designated endpoint contract."""

    def __init__(self, endpoint: WriterEndpoint, *, client_id: str) -> None:
        _validate_identity(client_id, field="client_id")
        self._endpoint = endpoint
        self.client_id = client_id

    @classmethod
    def from_environment(cls) -> "BuilderThreadClient":
        """Construct the sanctioned configured HTTP client without vault access."""
        from app.builderops.builder_thread_endpoint import configured_builder_thread_client

        return configured_builder_thread_client()

    def create(
        self,
        *,
        request_id: str,
        actor: str,
        recipient: str,
        subject: str,
        content: str,
        source_refs: tuple[str, ...],
    ) -> ThreadMutationResult:
        self._validate_actor(actor)
        return self._endpoint.mutate(
            ThreadMutation(
                request_id=request_id,
                kind="create",
                actor=actor,
                recipient=recipient,
                subject=subject,
                content=content,
                source_refs=source_refs,
            )
        )

    def reply(
        self,
        *,
        request_id: str,
        thread_id: str,
        actor: str,
        recipient: str,
        content: str,
        source_refs: tuple[str, ...],
    ) -> ThreadMutationResult:
        self._validate_actor(actor)
        return self._endpoint.mutate(
            ThreadMutation(
                request_id=request_id,
                kind="reply",
                actor=actor,
                thread_id=thread_id,
                recipient=recipient,
                content=content,
                source_refs=source_refs,
            )
        )

    def close(
        self, *, request_id: str, thread_id: str, actor: str, reason: str
    ) -> ThreadMutationResult:
        self._validate_actor(actor)
        return self._endpoint.mutate(
            ThreadMutation(
                request_id=request_id,
                kind="close",
                actor=actor,
                thread_id=thread_id,
                content=reason,
            )
        )

    def archive(
        self, *, request_id: str, thread_id: str, actor: str
    ) -> ThreadMutationResult:
        self._validate_actor(actor)
        return self._endpoint.mutate(
            ThreadMutation(
                request_id=request_id,
                kind="archive",
                actor=actor,
                thread_id=thread_id,
            )
        )

    def read(self, thread_id: str) -> BuilderThread:
        return self._endpoint.read_thread(thread_id)

    def inbox(self, recipient: str, *, limit: int) -> BuilderInbox:
        return self._endpoint.inbox(recipient, limit=limit)

    def _validate_actor(self, actor: str) -> None:
        if actor != self.client_id:
            raise BuilderThreadError("actor must match the endpoint client identity")


def _reject_repository_fixture_root(root: Path) -> None:
    resolved_root = root.resolve()
    if resolved_root == _REPOSITORY_VAULT_ROOT or _REPOSITORY_VAULT_ROOT in resolved_root.parents:
        raise BuilderThreadError("repository vault fixture cannot be a writer root")


def _validate_command(command: ThreadMutation) -> None:
    if command.kind not in {"create", "reply", "close", "archive"}:
        raise BuilderThreadError("unsupported thread mutation")
    if not _REQUEST_ID.fullmatch(command.request_id):
        raise BuilderThreadError("request_id must be a filename-safe bounded identifier")
    _validate_identity(command.actor, field="actor")
    if command.kind == "create":
        if command.thread_id is not None:
            raise BuilderThreadError("create cannot name an existing thread")
        _validate_identity(command.recipient, field="recipient")
        _validate_text(command.subject, field="subject")
        _validate_text(command.content, field="content")
        _validate_source_refs(command.source_refs)
        return
    _validate_identifier(command.thread_id, field="thread_id")
    if command.kind == "reply":
        _validate_identity(command.recipient, field="recipient")
        _validate_text(command.content, field="content")
        _validate_source_refs(command.source_refs)
    elif command.kind == "close":
        _validate_text(command.content, field="reason")
        if command.recipient is not None or command.source_refs:
            raise BuilderThreadError("close accepts only an attributed reason")
    elif command.kind == "archive":
        if command.recipient is not None or command.content is not None or command.source_refs:
            raise BuilderThreadError("archive accepts no content or source refs")


def _validate_identifier(value: str | None, *, field: str) -> None:
    if not isinstance(value, str) or not value or len(value) > 128:
        raise BuilderThreadError(f"{field} must be a bounded identifier")


def _validate_identity(value: str | None, *, field: str) -> None:
    if not isinstance(value, str) or not _IDENTITY.fullmatch(value):
        raise BuilderThreadError(f"{field} must be a named identity")


def _validate_text(value: str | None, *, field: str) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > _MAX_TEXT:
        raise BuilderThreadError(f"{field} must be bounded non-empty text")
    if _PRIVATE_CONTENT.search(value):
        raise BuilderThreadError(f"{field} is not shared_non_sensitive")
    if _CODE_OR_PATCH.search(value):
        raise BuilderThreadError(f"{field} is not shared_non_sensitive")


def _validate_source_refs(source_refs: tuple[str, ...]) -> None:
    if not source_refs or len(source_refs) > 8:
        raise BuilderThreadError("source refs must be bounded provenance")
    for source_ref in source_refs:
        if not isinstance(source_ref, str) or not _SOURCE_REF.fullmatch(source_ref):
            raise BuilderThreadError("source_ref must be typed bounded provenance")
        if _PRIVATE_CONTENT.search(source_ref):
            raise BuilderThreadError("source_ref is not shared_non_sensitive")


def _capture_key(recipient: str, subject: str, source_refs: tuple[str, ...]) -> str:
    return _command_digest(
        ThreadMutation(
            request_id="capture-key",
            kind="create",
            actor="system:writer",
            recipient=recipient,
            subject=subject,
            content="capture-key",
            source_refs=source_refs,
        )
    )


def _command_digest(command: ThreadMutation) -> str:
    return hashlib.sha256(_canonical_json(_command_record(command))).hexdigest()


def _canonical_json(payload: Any) -> bytes:
    return (
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        + b"\n"
    )


def _command_record(command: ThreadMutation) -> dict[str, Any]:
    return {
        "actor": command.actor,
        "content": command.content,
        "kind": command.kind,
        "recipient": command.recipient,
        "request_id": command.request_id,
        "source_refs": list(command.source_refs),
        "subject": command.subject,
        "thread_id": command.thread_id,
    }


def _command_from_record(payload: Any, *, vault_id: str) -> ThreadMutation:
    if (
        not isinstance(payload, dict)
        or payload.get("schema") != "builder-thread-command.v1"
        or payload.get("vault_id") != vault_id
        or not isinstance(payload.get("command"), dict)
    ):
        raise ValueError("invalid writer command record")
    command = payload["command"]
    kind = command.get("kind")
    source_refs = command.get("source_refs")
    if kind not in {"create", "reply", "close", "archive"} or not isinstance(source_refs, list):
        raise ValueError("invalid writer command fields")
    if not all(isinstance(source_ref, str) for source_ref in source_refs):
        raise ValueError("invalid writer source refs")
    return ThreadMutation(
        request_id=command.get("request_id"),
        kind=cast(Literal["create", "reply", "close", "archive"], kind),
        actor=command.get("actor"),
        thread_id=command.get("thread_id"),
        recipient=command.get("recipient"),
        subject=command.get("subject"),
        content=command.get("content"),
        source_refs=tuple(source_refs),
    )


def _summary(thread: BuilderThread) -> BuilderThreadSummary:
    last = thread.entries[-1]
    return BuilderThreadSummary(
        thread_id=thread.thread_id,
        subject=thread.subject,
        state=thread.state,
        entry_count=len(thread.entries),
        last_actor=last.actor,
        last_recipient=last.recipient,
        last_source_refs=last.source_refs,
    )
