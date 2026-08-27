"""Serialized, non-authoritative Builder Thread exchange.

The process that creates :class:`SerializedThreadWriter` is the designated
BuilderOps/Mac mini writer.  Clients only receive an endpoint; this module has
no client filesystem API and deliberately never discovers a vault path.
"""

from __future__ import annotations

import hashlib
import ipaddress
import idna
import json
import os
import re
import threading
import unicodedata
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol, cast
from urllib.parse import unquote, urlsplit


PRIVACY_CLASS: Literal["shared_non_sensitive"] = "shared_non_sensitive"
_IDENTITY = re.compile(r"^[a-z][a-z0-9_-]{1,31}:[A-Za-z0-9._:-]{2,119}$")
_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SOURCE_REF = re.compile(
    r"^(?:builderops|conversation|doc|git|github):[A-Za-z0-9._:/#@+-]{1,255}$"
)
_CREDENTIAL_CONTENT = re.compile(
    r"(?im)(password|secret|credential|token|api[_-]?key|bearer|"
    r"^[ \t]*aws_(?:access_key_id|secret_access_key)\s*=|"
    r"^[ \t]*authorization:\s*(?:basic|bearer)\b|"
    r"^[ \t]*-----begin (?:[a-z ]* )?private key-----|"
    r"\bAKIA[0-9A-Z]{16}\b|\bgithub_pat_[A-Za-z0-9_]{20,}|"
    r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b)"
)
_CODE_OR_PATCH = re.compile(
    r"(?m)^[ \t]*(?:diff --git |--- a/|\+\+\+ b/|@@ |```|"
    r"git diff(?:[ \t]|$)|"
    r"async[ \t]+def[ \t]+[A-Za-z_][A-Za-z0-9_]*[ \t]*\(|"
    r"(?:def|function)[ \t]+[A-Za-z_][A-Za-z0-9_]*[ \t]*\(|"
    r"class[ \t]+[A-Za-z_][A-Za-z0-9_]*[ \t]*(?:\(|:)|"
    r"(?:const|let|var)[ \t]+[A-Za-z_$][A-Za-z0-9_$]*[ \t]*=[ \t]*|"
    r"from[ \t]+[A-Za-z0-9_.]+[ \t]+import(?:[ \t]|$)|"
    r"import[ \t]+[A-Za-z0-9_.]+(?:$|,[ \t]*|[ \t]+as\b)|"
    r"(?:package|func)[ \t]+[A-Za-z_][A-Za-z0-9_]*|"
    r"print[ \t]*\(|"
    r"(?:return|yield)\b[ \t]*(?:[0-9'\"(\[{])|"
    r"throw(?:[ \t]+new[ \t]+[A-Za-z_$][A-Za-z0-9_$]*|[ \t]*\()|"
    r"await[ \t]+(?:[A-Za-z_$][A-Za-z0-9_$]*[ \t]*\(|Promise\.)|"
    r"lambda[ \t]+[^:\n]+:|"
    r"if[ \t]+[^:\n]+:[ \t]*$|"
    r"console\.(?:log|error|warn)[ \t]*\(|"
    r"[A-Za-z_$][A-Za-z0-9_$]*[ \t]*=[ \t]*(?:\([^)]*\)|[A-Za-z_$][A-Za-z0-9_$]*)[ \t]*=>)"
)
_MAX_TEXT = 500
_MAX_COMPONENTS = 64
_MAX_THREAD_ENTRIES = 32
_MAX_TOTAL_ENTRIES = 100
_ROOT_IDENTITY = "builder-thread-writer.json"
_ENTRY_DIRECTORY = "builder-thread-entries"
_REPOSITORY_VAULT_ROOT = (Path(__file__).resolve().parents[2] / "vault").resolve()
_WRITER_ROOT_ENV = "BUILDEROPS_THREAD_WRITER_ROOT"
_WRITER_VAULT_ID_ENV = "BUILDEROPS_THREAD_WRITER_VAULT_ID"


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
            if self._persistence_unavailable:
                raise WriterUnavailableError("serialized writer persistence is unavailable")
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
                raise WriterUnavailableError("serialized writer persistence is unavailable") from exc
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
        try:
            payload = _strict_json_loads(identity.read_text(encoding="utf-8"))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise BuilderThreadError("external writer root is not the pinned vault identity") from exc
        if (
            not isinstance(payload, dict)
            or set(payload) != {"schema", "vault_id"}
            or payload.get("schema") != "builder-thread-writer.v1"
            or payload.get("vault_id") != self._vault_id
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
                payload = _strict_json_loads(path.read_text(encoding="utf-8"))
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
        raise WriterUnavailableError(
            "Builder Thread production writer is unavailable pending privacy-boundary replacement"
        )

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
    _validate_shared_text(command.request_id, field="request_id")
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
    _validate_shared_text(value, field=field)


def _validate_identity(value: str | None, *, field: str) -> None:
    if not isinstance(value, str) or not _IDENTITY.fullmatch(value):
        raise BuilderThreadError(f"{field} must be a named identity")
    _validate_shared_text(value, field=field)


def _validate_text(value: str | None, *, field: str) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > _MAX_TEXT:
        raise BuilderThreadError(f"{field} must be bounded non-empty text")
    _validate_shared_text(value, field=field)


def _validate_source_refs(source_refs: tuple[str, ...]) -> None:
    if not source_refs or len(source_refs) > 8:
        raise BuilderThreadError("source refs must be bounded provenance")
    for source_ref in source_refs:
        if not isinstance(source_ref, str) or not _SOURCE_REF.fullmatch(source_ref):
            raise BuilderThreadError("source_ref must be typed bounded provenance")
        _validate_shared_text(source_ref, field="source_ref")


def _validate_shared_text(value: str, *, field: str) -> None:
    """Apply the closed structural privacy classifier without exposing input."""
    if _classify_shared_text(value) != "valid":
        raise BuilderThreadError(f"{field} is not shared_non_sensitive")


def _classify_shared_text(value: str) -> Literal["valid", "terminal_private", "indeterminate"]:
    """Classify bounded shared text with a URI-aware, fail-closed scanner.

    URI parsing is deliberately separated from path scanning: only the parsed
    path of a valid HTTP(S) URI is a resource path. Query, fragment, opaque,
    filesystem, malformed, and ordinary text remain untrusted components.
    """
    if len(value) > _MAX_TEXT:
        return "indeterminate"
    forms = _decoded_forms(value)
    if forms is None:
        return "indeterminate"
    if len(forms) > _MAX_COMPONENTS:
        return "indeterminate"
    for form in forms:
        outcome = _classify_form(form)
        if outcome != "valid":
            return outcome
    return "valid"


def _decoded_forms(value: str) -> list[str] | None:
    forms = [value]
    current = value
    for _ in range(2):
        if not _has_valid_percent_escapes(current):
            return None
        decoded = unquote(current)
        if decoded == current:
            return forms
        forms.append(decoded)
        current = decoded
    if not _has_valid_percent_escapes(current) or unquote(current) != current:
        return None
    return forms


def _has_valid_percent_escapes(value: str) -> bool:
    index = 0
    while index < len(value):
        if value[index] == "%":
            if index + 2 >= len(value) or any(char not in "0123456789abcdefABCDEF" for char in value[index + 1:index + 3]):
                return False
            index += 3
        else:
            index += 1
    return True


def _classify_form(value: str) -> Literal["valid", "terminal_private", "indeterminate"]:
    # Decoding may turn an encoded path segment into whitespace. Recognise
    # credential/code forms at every segment boundary before lexical URI
    # scanning terminates the candidate at that whitespace.
    if _contains_credential_or_code(value.replace("/", "\n")):
        return "terminal_private"
    spans = _uri_spans(value)
    remainder = list(value)
    components = 0
    for start, end in spans:
        components += 1
        if components > _MAX_COMPONENTS:
            return "indeterminate"
        outcome = _classify_uri(value[start:end])
        if outcome != "valid":
            return outcome
        scheme = value[start:value.find(":", start)].lower()
        if scheme in {"http", "https"}:
            remainder[start:end] = " " * (end - start)
    plain = "".join(remainder)
    if _contains_credential_or_code(plain) or _contains_private_path(plain):
        return "terminal_private"
    return "valid"


def _uri_spans(value: str) -> list[tuple[int, int]]:
    """Return bounded lexical URI candidates without assigning them safety."""
    spans: list[tuple[int, int]] = []
    index = 0
    terminators = set(" \t\r\n<>\"`}")
    while index < len(value):
        if not value[index].isalpha() or not _token_boundary(value, index):
            index += 1
            continue
        cursor = index + 1
        while cursor < len(value) and (value[cursor].isalnum() or value[cursor] in "+-."):
            cursor += 1
        if cursor >= len(value) or value[cursor] != ":":
            index += 1
            continue
        # One-letter forms are overwhelmingly path/code punctuation; a Windows
        # drive is handled by path scanning, not reinterpreted as a URI.
        if cursor == index + 1:
            index += 1
            continue
        end = cursor + 1
        while end < len(value) and value[end] not in terminators:
            end += 1
        spans.append((index, end))
        index = end
    return spans


def _token_boundary(value: str, index: int) -> bool:
    return index == 0 or value[index - 1] not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_%+-."


def _classify_uri(candidate: str) -> Literal["valid", "terminal_private", "indeterminate"]:
    try:
        parsed = urlsplit(candidate)
    except ValueError:
        return "indeterminate"
    scheme = parsed.scheme.lower()
    if not scheme:
        return "valid"
    if scheme in {"http", "https"}:
        if not candidate.lower().startswith(f"{scheme}://") or not parsed.netloc or "@" in parsed.netloc:
            return "indeterminate"
        if not _valid_http_authority(parsed.netloc):
            return "indeterminate"
        # The whole URI still receives credential/code recognition. Only its
        # parsed path skips local-host-path recognition.
        if _contains_credential_or_code(candidate) or _contains_credential_or_code(
            parsed.path.replace("/", "\n")
        ):
            return "terminal_private"
        for component in (parsed.netloc, parsed.query, parsed.fragment):
            outcome = _classify_form(component)
            if outcome != "valid":
                return outcome
        return "valid"
    if scheme in {"file", "smb", "nfs", "ssh", "sftp"}:
        if not candidate.startswith(f"{scheme}://") or not parsed.netloc or not parsed.path:
            return "indeterminate"
    if _contains_credential_or_code(candidate) or _contains_private_path(candidate):
        return "terminal_private"
    return "valid"


def _valid_http_authority(authority: str) -> bool:
    try:
        parsed = urlsplit(f"https://{authority}")
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        return False
    if not host or "@" in authority or port is not None and not 0 <= port <= 65535:
        return False
    if ":" in host:
        try:
            ipaddress.IPv6Address(host.split("%", 1)[0])
        except ValueError:
            return False
        return "%" not in host or "%25" in authority
    try:
        ipaddress.IPv4Address(host)
        return True
    except ValueError:
        pass
    try:
        encoded = idna.encode(host, uts46=False, std3_rules=True).decode("ascii")
    except idna.IDNAError:
        return False
    if len(encoded) > 253:
        return False
    for label in encoded.split("."):
        if label.lower().startswith("xn--"):
            try:
                decoded_label = idna.decode(label.encode("ascii"), uts46=False, std3_rules=True)
                if idna.encode(decoded_label, uts46=False, std3_rules=True).decode("ascii").lower() != label.lower():
                    return False
            except idna.IDNAError:
                return False
            if any(unicodedata.category(char).startswith("C") for char in decoded_label):
                return False
    return all(
        1 <= len(label) <= 63
        and not label.startswith("-")
        and not label.endswith("-")
        and all(char.isascii() and (char.isalnum() or char == "-") for char in label)
        for label in encoded.split(".")
    )


def _contains_credential_or_code(value: str) -> bool:
    return bool(_CREDENTIAL_CONTENT.search(value) or _CODE_OR_PATCH.search(value))


def _contains_private_path(value: str) -> bool:
    """Recognise standalone POSIX, tilde, drive, rooted, and UNC path tokens."""
    for index, char in enumerate(value):
        if not _token_boundary(value, index):
            continue
        if char == "/":
            return True
        if char == "~":
            cursor = index + 1
            while cursor < len(value) and (value[cursor].isalnum() or value[cursor] in "_.-"):
                cursor += 1
            if cursor == len(value) or value[cursor] in "\\/ \t\r\n)]},;!?":
                return True
        if char == "\\":
            return True
        if char.isalpha() and index + 2 < len(value) and value[index + 1] == ":" and value[index + 2] in "\\/":
            return True
    return False


def _strict_json_loads(value: str) -> Any:
    def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = item
        return result

    return json.loads(value, object_pairs_hook=object_pairs)


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
        or set(payload) != {"command", "request_digest", "sequence", "schema", "vault_id"}
        or payload.get("schema") != "builder-thread-command.v1"
        or payload.get("vault_id") != vault_id
        or not isinstance(payload.get("command"), dict)
    ):
        raise ValueError("invalid writer command record")
    command = payload["command"]
    if set(command) != {
        "actor",
        "content",
        "kind",
        "recipient",
        "request_id",
        "source_refs",
        "subject",
        "thread_id",
    }:
        raise ValueError("invalid writer command fields")
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
