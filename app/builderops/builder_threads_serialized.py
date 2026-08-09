"""Serialized, non-authoritative Builder Thread exchange.

The process that creates :class:`SerializedThreadWriter` is the designated
BuilderOps/Mac mini writer.  Clients only receive an endpoint; this module has
no client filesystem API and deliberately never discovers a vault path.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import uuid
from dataclasses import dataclass
from typing import Literal, Protocol


PRIVACY_CLASS: Literal["shared_non_sensitive"] = "shared_non_sensitive"
_IDENTITY = re.compile(r"^[a-z][a-z0-9_-]{1,31}:[A-Za-z0-9._:-]{2,119}$")
_SOURCE_REF = re.compile(
    r"^(?:builderops|conversation|doc|git|github):[A-Za-z0-9._:/#@+-]{1,255}$"
)
_PRIVATE_CONTENT = re.compile(
    r"(?i)(password|secret|credential|token|api[_-]?key|bearer\s+|/(?:Users|home|private)/)"
)
_MAX_TEXT = 500


class BuilderThreadError(ValueError):
    """A bounded refusal at the Builder Thread boundary."""


class WriterUnavailableError(BuilderThreadError):
    """The designated writer cannot currently accept or serve a request."""


class WriterAcknowledgementLost(WriterUnavailableError):
    """The writer may have accepted a request but its caller got no result."""


class RequestReplayConflictError(BuilderThreadError):
    """A caller reused its request ID for changed semantics."""


class ThreadAlreadyRepresentedError(BuilderThreadError):
    """The create capture key already has a durable Builder Thread."""


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
    """One host-local writer for immutable-in-memory Builder Thread snapshots.

    Persistence and host deployment are outside this repo contract: an operator
    runs this one writer against the external BuilderOps vault.  Keeping the
    mutation authority in this object avoids pretending that two clients can
    coordinate direct writes to an iCloud-synchronised file tree.
    """

    def __init__(self, *, vault_id: str) -> None:
        _validate_identifier(vault_id, field="vault_id")
        self._vault_id = vault_id
        self._threads: dict[str, BuilderThread] = {}
        self._request_digests: dict[str, str] = {}
        self._request_results: dict[str, BuilderThread] = {}
        self._capture_index: dict[str, str] = {}
        self._accepted_mutation_count = 0
        self._lock = threading.RLock()

    @property
    def accepted_mutation_count(self) -> int:
        return self._accepted_mutation_count

    def mutate(self, command: ThreadMutation) -> ThreadMutationResult:
        """Validate and apply exactly one command in the designated process."""
        with self._lock:
            _validate_command(command)
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

            if command.kind == "create":
                thread = self._create(command)
            else:
                thread = self._append(command)

            self._request_digests[command.request_id] = request_digest
            self._request_results[command.request_id] = thread
            self._accepted_mutation_count += 1
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
        if command.kind == "reply":
            if current.state != "open":
                raise BuilderThreadError("only an open thread can receive a reply")
            next_state: Literal["open", "closed", "archived"] = "open"
        elif command.kind == "close":
            if current.state != "open":
                raise BuilderThreadError("only an open thread can close")
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


class InProcessWriterEndpoint:
    """Test/development endpoint adapter; production clients use a remote adapter."""

    def __init__(self, writer: SerializedThreadWriter) -> None:
        self._writer = writer
        self.mutation_count = 0

    def mutate(self, command: ThreadMutation) -> ThreadMutationResult:
        self.mutation_count += 1
        return self._writer.mutate(command)

    def read_thread(self, thread_id: str) -> BuilderThread:
        return self._writer.read_thread(thread_id)

    def inbox(self, recipient: str, *, limit: int) -> BuilderInbox:
        return self._writer.inbox(recipient, limit=limit)


class BuilderThreadClient:
    """Codex/Claude client restricted to the designated endpoint contract."""

    def __init__(self, endpoint: WriterEndpoint, *, client_id: str) -> None:
        _validate_identity(client_id, field="client_id")
        self._endpoint = endpoint
        self.client_id = client_id

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


def _validate_command(command: ThreadMutation) -> None:
    if command.kind not in {"create", "reply", "close", "archive"}:
        raise BuilderThreadError("unsupported thread mutation")
    _validate_identifier(command.request_id, field="request_id")
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
    canonical = json.dumps(
        {
            "actor": command.actor,
            "content": command.content,
            "kind": command.kind,
            "recipient": command.recipient,
            "request_id": command.request_id,
            "source_refs": command.source_refs,
            "subject": command.subject,
            "thread_id": command.thread_id,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


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
