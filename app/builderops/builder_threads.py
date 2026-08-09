"""Immutable, shared-non-sensitive Builder Thread artifacts.

The shared filesystem is an artifact transport, never a coordination or delivery
authority. Every operation validates the pinned vault genesis and reconstructs
thread state from content-addressed contribution envelopes.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import unquote

from app.builderops.vault_queue import _content_is_local, _may_be_sqlite_image


GENESIS_SCHEMA = "builder-thread.genesis.v1"
ENTRY_SCHEMA = "builder-thread.contribution.v1"
ENTRY_CLAIM_SCHEMA = "builder-thread.entry-claim.v1"
PRIVACY_CLASS = "shared_non_sensitive"
BUILDER_ROOT_NAME = "builder-threads"
GENESIS_NAME = "genesis.json"
VAULT_GENESIS_NAME = "vault-genesis.json"
ENTRY_TYPES = frozenset({"open", "reply", "close", "archive", "quarantine"})
SOURCE_REF_TYPES = frozenset(
    {
        "builderops_record",
        "codex_thread",
        "git_commit",
        "github_issue",
        "github_pr",
        "repo_path",
    }
)
QUARANTINE_REASONS = frozenset(
    {
        "argv_env_stderr",
        "concurrent_conflict",
        "credential_like_content",
        "private_host_path",
        "privacy_misclassification",
    }
)
SCAFFOLD_DIRS = (
    ".builderops/claims",
    "agent-delivery/Backlog",
    "agent-delivery/Ready",
    "agent-delivery/In Progress",
    "agent-delivery/Review",
    "agent-delivery/Blocked",
    "agent-delivery/Done",
)
ENTRY_KEYS = frozenset(
    {
        "actor_id",
        "basis_hash",
        "basis_hashes",
        "capture_key",
        "content",
        "created_at",
        "entry_id",
        "entry_type",
        "parent_hash",
        "privacy_class",
        "reason_code",
        "recipient_id",
        "reply_expected",
        "schema",
        "source_refs",
        "subject",
        "target_hash",
        "thread_id",
        "vault_id",
    }
)
GENESIS_KEYS = frozenset({"created_at", "privacy_class", "schema", "vault_id"})
ENTRY_CLAIM_KEYS = frozenset(
    {"entry_id", "privacy_class", "request_hash", "schema", "thread_id", "vault_id"}
)
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
IDENTITY_RE = re.compile(r"^(?:agent|automation|human):[A-Za-z0-9][A-Za-z0-9._:-]{1,119}$")
REPO_PATH_RE = re.compile(r"^[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_. -]+)*(?::[1-9][0-9]*)?$")
REF_VALUE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/#@+-]{0,255}$")
BUILDEROPS_REF_RE = re.compile(r"^[a-z][a-z0-9_:-]{2,127}$")
CODEX_THREAD_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
GIT_COMMIT_RE = re.compile(r"^[0-9a-f]{7,64}$")
GITHUB_NUMBER_RE = re.compile(r"^#?[1-9][0-9]*$")
CONFLICT_COPY_RE = re.compile(r"conflicted copy", re.IGNORECASE)
TEMP_FILE_RE = re.compile(r"^\.tmp-(?P<stem>.+)-[0-9a-f]{32}$")
SLOT_RESERVATION_NAME = ".reservation"
RECONCILE_ATTEMPTS = 61
PRIVATE_PATH_RE = re.compile(
    r"(?:file:(?://)?|~[/\\]|"
    r"(?<![A-Za-z0-9._~/-])/(?!/|\s)[^\s<>`\"']+|"
    r"(?<![:/])//[^\s<>]+|(?<![A-Za-z0-9])\\\\[^\s<>]+|"
    r"(?<![A-Za-z0-9\\])\\(?![\\\s])[^\s<>]+|"
    r"(?<![A-Za-z0-9])[A-Za-z]:[/\\]|%2f[^\s<>]+)",
    re.IGNORECASE,
)
SECRET_RE = re.compile(
    r"(?:(?:proxy-)?authorization\s*:\s*(?:bearer|basic)|"
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----|"
    r"[A-Za-z][A-Za-z0-9+.-]*://[^/\s:@]+:[^@/\s]+@|"
    r"[?&](?:access[_-]?token|api[_-]?key|token)=[^&#\s]+|"
    r"\b(?:api[_-]?key|access[_-]?token|password|client[_-]?secret)\s*[:=]|"
    r"\b(?:gh[pousr]_[A-Za-z0-9]{12,}|github_pat_[A-Za-z0-9_]{12,}|"
    r"sk-(?:proj-)?[A-Za-z0-9_-]{12,}|AKIA[0-9A-Z]{16}|"
    r"xox[baprs]-[A-Za-z0-9-]{8,}|AIza[0-9A-Za-z_-]{20,}|"
    r"eyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}))",
    re.IGNORECASE,
)
ENV_RE = re.compile(
    r"(?:^|[\s;,([{])(?:export\s+)?[A-Za-z_][A-Za-z0-9_]{1,63}\s*=\s*\S+",
    re.IGNORECASE,
)
ARGV_STDERR_RE = re.compile(
    r"(?:\b(?:sys\.)?argv(?:\s+was)?\s*(?:[:=]|\[)|"
    r"\bstderr\s*(?:[:=]|\[)|Traceback \(most recent call last\))",
    re.IGNORECASE,
)


class BuilderThreadError(ValueError):
    """Base error for Builder Thread refusals."""


class BuilderThreadValidationError(BuilderThreadError):
    """An artifact, root, or operation violates the contract."""


class BuilderThreadConflictError(BuilderThreadError):
    """Concurrent or replayed artifacts cannot be reconciled safely."""


class BuilderThreadPrivacyError(BuilderThreadError):
    """Content does not fit the shared-non-sensitive boundary."""


class _ExistingThreadDestination(BuilderThreadConflictError):
    """Another writer already claimed the deterministic thread directory."""


class _ExistingEntryReservation(RuntimeError):
    """Another writer reserved this entry identity after our read snapshot."""


class _ActiveEntryClaim(RuntimeError):
    """A complete claim may still be inside the bounded publication window."""


def _stamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _canonical_bytes(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _snapshot_hash(hashes: Iterable[str]) -> str:
    return _sha256(_canonical_bytes({"artifact_hashes": sorted(set(hashes))}))


def _same_idempotent_request(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    return left.get("entry_id") == right.get("entry_id") and {
        key: value for key, value in left.items() if key != "created_at"
    } == {key: value for key, value in right.items() if key != "created_at"}


def _request_hash(entry: Mapping[str, Any]) -> str:
    return _sha256(
        _canonical_bytes(
            {key: value for key, value in entry.items() if key != "created_at"}
        )
    )


def _capture_thread_id(vault_id: str, capture_key: str) -> str:
    """Derive one UUIDv4-shaped path identity for one represented capture."""

    raw = bytearray(hashlib.sha256(f"{vault_id}:{capture_key}".encode()).digest()[:16])
    raw[6] = (raw[6] & 0x0F) | 0x40
    raw[8] = (raw[8] & 0x3F) | 0x80
    return str(uuid.UUID(bytes=bytes(raw)))


def _capture_key(recipient_id: str, source_refs: list[dict[str, str]], subject: str) -> str:
    return _sha256(
        _canonical_bytes(
            {
                "recipient_id": recipient_id,
                "source_refs": source_refs,
                "subject": subject.casefold(),
            }
        )
    )


def _uuid4(value: Any, *, field: str) -> str:
    if not isinstance(value, str):
        raise BuilderThreadValidationError(f"{field} must be a canonical UUIDv4")
    normalized = value.strip().lower()
    if not UUID_RE.fullmatch(normalized):
        raise BuilderThreadValidationError(f"{field} must be a canonical UUIDv4")
    return normalized


def _identity(value: Any, *, field: str, enforce_privacy: bool = True) -> str:
    if not isinstance(value, str):
        raise BuilderThreadValidationError(f"{field} requires a named recipient/actor identity")
    normalized = value.strip()
    if not IDENTITY_RE.fullmatch(normalized):
        raise BuilderThreadValidationError(f"{field} requires a named recipient/actor identity")
    if enforce_privacy:
        _privacy_check(normalized, field=field)
    return normalized


def _validate_timestamp(value: Any) -> str:
    if not isinstance(value, str):
        raise BuilderThreadValidationError("created_at must be RFC3339 UTC")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise BuilderThreadValidationError("created_at must be RFC3339 UTC seconds") from exc
    return parsed.replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _bounded_text(
    value: Any,
    *,
    field: str,
    maximum: int,
    required: bool = True,
) -> str | None:
    if value is None:
        if required:
            raise BuilderThreadValidationError(f"{field} is required")
        return None
    if not isinstance(value, str):
        raise BuilderThreadValidationError(f"{field} must be text")
    normalized = value.strip()
    if required and not normalized:
        raise BuilderThreadValidationError(f"{field} is required")
    if not normalized:
        return None
    if len(normalized) > maximum:
        raise BuilderThreadValidationError(f"{field} exceeds {maximum} characters")
    if "\x00" in normalized:
        raise BuilderThreadValidationError(f"{field} contains NUL")
    return normalized


def _privacy_check(value: str | None, *, field: str) -> None:
    if value is None:
        return
    variants = [value]
    decoded = value
    for _ in range(2):
        candidate = unquote(decoded)
        if candidate == decoded:
            break
        variants.append(candidate)
        decoded = candidate
    slash_translation = str.maketrans(
        {
            "⁄": "/",  # fraction slash
            "∕": "/",  # division slash
            "⧸": "/",  # big solidus
            "／": "/",  # fullwidth solidus
            "＼": "\\",  # fullwidth reverse solidus
        }
    )
    variants.extend(item.translate(slash_translation) for item in tuple(variants))
    for candidate in variants:
        if SECRET_RE.search(candidate):
            raise BuilderThreadPrivacyError(f"{field} contains credential-like content")
        if PRIVATE_PATH_RE.search(candidate):
            raise BuilderThreadPrivacyError(f"{field} contains a private host path")
        if ENV_RE.search(candidate) or ARGV_STDERR_RE.search(candidate):
            raise BuilderThreadPrivacyError(f"{field} contains argv/env/stderr material")


def _source_refs(values: Any, *, enforce_privacy: bool = True) -> list[dict[str, str]]:
    if not isinstance(values, (list, tuple)):
        raise BuilderThreadValidationError("source refs must be a bounded array")
    result: list[dict[str, str]] = []
    for raw in values:
        if not isinstance(raw, Mapping):
            raise BuilderThreadValidationError("source refs must be objects")
        if set(raw) != {"type", "value"}:
            raise BuilderThreadValidationError("source refs require exactly type and value")
        if not isinstance(raw["type"], str) or not isinstance(raw["value"], str):
            raise BuilderThreadValidationError("source ref type and value must be text")
        ref_type = raw["type"].strip()
        value = raw["value"].strip()
        if ref_type not in SOURCE_REF_TYPES:
            raise BuilderThreadValidationError("unsupported source ref type")
        matcher = {
            "builderops_record": BUILDEROPS_REF_RE,
            "codex_thread": CODEX_THREAD_RE,
            "git_commit": GIT_COMMIT_RE,
            "github_issue": GITHUB_NUMBER_RE,
            "github_pr": GITHUB_NUMBER_RE,
            "repo_path": REPO_PATH_RE,
        }.get(ref_type, REF_VALUE_RE)
        repo_path = value.rsplit(":", 1)[0]
        has_dot_segment = ref_type == "repo_path" and any(
            part in {".", ".."} for part in repo_path.split("/")
        )
        if (
            not matcher.fullmatch(value)
            or value.startswith(("/", "~"))
            or has_dot_segment
        ):
            raise BuilderThreadValidationError(f"unsafe source ref: {ref_type}")
        if enforce_privacy:
            _privacy_check(value, field="source_ref")
        result.append({"type": ref_type, "value": value})
    deduplicated = sorted(
        {json.dumps(item, sort_keys=True): item for item in result}.values(),
        key=lambda item: (item["type"], item["value"]),
    )
    if not deduplicated:
        raise BuilderThreadValidationError("at least one authority-safe source ref is required")
    if len(deduplicated) > BuilderThreadService.MAX_SOURCE_REFS:
        raise BuilderThreadValidationError("too many source refs")
    return deduplicated


def _fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _real_directory(path: Path, *, label: str) -> None:
    try:
        info = path.lstat()
    except FileNotFoundError as exc:
        raise BuilderThreadValidationError(f"missing BuilderOps scaffold: {label}") from exc
    if stat.S_ISLNK(info.st_mode):
        raise BuilderThreadValidationError(f"symlink forbidden at {label}")
    if not stat.S_ISDIR(info.st_mode):
        raise BuilderThreadValidationError(f"BuilderOps scaffold is not a directory: {label}")


def _safe_mkdir(path: Path) -> None:
    path.mkdir(mode=0o700, parents=False, exist_ok=True)
    _real_directory(path, label=path.name)
    _fsync_directory(path.parent)


def _atomic_publish(path: Path, data: bytes) -> bool:
    """Install complete bytes without exposing a partially written final file."""

    path.parent.mkdir(mode=0o700, parents=False, exist_ok=True)
    _real_directory(path.parent, label=path.parent.name)
    temp = path.parent / f".tmp-{path.stem}-{uuid.uuid4().hex}"
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb", closefd=True) as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if temp.read_bytes() != data:
            raise BuilderThreadConflictError("temporary artifact readback mismatch")
        try:
            os.link(temp, path)
            _fsync_directory(path.parent)
        except FileExistsError:
            existing = path.read_bytes()
            if existing != data:
                raise BuilderThreadConflictError(f"no-overwrite replay conflict at {path.name}")
            return False
        if path.read_bytes() != data:
            raise BuilderThreadConflictError("published artifact readback mismatch")
        return True
    finally:
        temp.unlink(missing_ok=True)
        _fsync_directory(path.parent)


class BuilderThreadService:
    """File-first Builder Thread writer, reader, validator, and inbox reducer."""

    MAX_CONTENT_CHARS = 4_000
    MAX_SUBJECT_CHARS = 160
    MAX_SOURCE_REFS = 8
    MAX_ENTRIES_PER_THREAD = 128
    MAX_LIST_THREADS = 100
    INCIDENT_SOURCE_REFS = [
        {"type": "repo_path", "value": "docs/builderops/BUILDEROPS_VAULT_STORE.md"}
    ]

    def __init__(self, root: Path, *, expected_vault_id: str):
        self.root = Path(root)
        self.expected_vault_id = _uuid4(expected_vault_id, field="vault_id")
        self.builder_root = self.root / BUILDER_ROOT_NAME
        self.threads_root = self.builder_root / "threads"
        self.entry_claims_root = self.builder_root / "entry-claims"

    @classmethod
    def initialize(
        cls,
        root: Path,
        *,
        vault_id: str,
        created_at: str | None = None,
        adopt_existing: bool = False,
    ) -> BuilderThreadService:
        service = cls(root, expected_vault_id=vault_id)
        service._validate_root(require_genesis=False)
        vault_genesis_path = service.root / ".builderops" / VAULT_GENESIS_NAME
        genesis_path = service.builder_root / GENESIS_NAME
        root_exists = vault_genesis_path.exists()
        subsystem_exists = genesis_path.exists()
        if root_exists != subsystem_exists:
            raise BuilderThreadConflictError(
                "partial vault/subsystem genesis pair; incident disposition required"
            )
        if root_exists:
            root_payload = service._read_genesis_at(vault_genesis_path, label="vault genesis")
            if service._read_genesis() != root_payload:
                raise BuilderThreadConflictError(
                    "vault and Builder Thread genesis envelopes differ"
                )
            service.health()
            return service

        service._validate_pre_genesis_tree()
        if not adopt_existing:
            raise BuilderThreadValidationError(
                "unattested BuilderOps vault; explicit adopt_existing is required"
            )
        payload = {
            "created_at": _validate_timestamp(created_at or _stamp()),
            "privacy_class": PRIVACY_CLASS,
            "schema": GENESIS_SCHEMA,
            "vault_id": service.expected_vault_id,
        }
        if not service.builder_root.exists():
            _safe_mkdir(service.builder_root)
        else:
            _real_directory(service.builder_root, label=BUILDER_ROOT_NAME)
        if not service.threads_root.exists():
            _safe_mkdir(service.threads_root)
        else:
            _real_directory(service.threads_root, label="builder-threads/threads")
        if not service.entry_claims_root.exists():
            _safe_mkdir(service.entry_claims_root)
        else:
            _real_directory(
                service.entry_claims_root,
                label="builder-threads/entry-claims",
            )
        _atomic_publish(vault_genesis_path, _canonical_bytes(payload))
        _atomic_publish(genesis_path, _canonical_bytes(payload))
        service.health()
        return service

    def _validate_pre_genesis_tree(self) -> None:
        if not self.builder_root.exists():
            return
        _real_directory(self.builder_root, label=BUILDER_ROOT_NAME)
        if (self.builder_root / GENESIS_NAME).exists():
            return
        children = list(self.builder_root.iterdir())
        if not children:
            return
        if {child.name for child in children}.issubset({"threads", "entry-claims"}):
            for child in children:
                _real_directory(child, label=f"builder-threads/{child.name}")
                if any(child.iterdir()):
                    break
            else:
                return
        raise BuilderThreadValidationError("unrecognized pre-genesis Builder Thread artifacts")

    def create_thread(
        self,
        *,
        recipient_id: str,
        subject: str,
        content: str,
        actor_id: str,
        source_refs: Iterable[Mapping[str, str]],
        reply_expected: bool = True,
        thread_id: str | None = None,
        entry_id: str | None = None,
        created_at: str | None = None,
    ) -> dict[str, Any]:
        if entry_id is None:
            raise BuilderThreadValidationError(
                "create requires a caller-retained entry_id"
            )
        request_entry_id = _uuid4(entry_id, field="entry_id")
        self._prepare_write()
        recipient = _identity(recipient_id, field="recipient_id")
        actor = _identity(actor_id, field="actor_id")
        if reply_expected is not True:
            raise BuilderThreadValidationError(
                "capture requires reply_expected=true; monologic notes are AgentWorklog"
            )
        normalized_subject = _bounded_text(subject, field="subject", maximum=self.MAX_SUBJECT_CHARS)
        normalized_content = _bounded_text(content, field="content", maximum=self.MAX_CONTENT_CHARS)
        assert isinstance(normalized_subject, str)
        assert isinstance(normalized_content, str)
        _privacy_check(normalized_subject, field="subject")
        _privacy_check(normalized_content, field="content")
        refs = _source_refs(source_refs)
        capture_key = _capture_key(recipient, refs, normalized_subject)
        derived_thread_id = _capture_thread_id(self.expected_vault_id, capture_key)
        if thread_id is not None and _uuid4(thread_id, field="thread_id") != derived_thread_id:
            raise BuilderThreadValidationError(
                "thread_id must match the deterministic capture identity"
            )
        entry = self._entry_payload(
            thread_id=derived_thread_id,
            entry_id=request_entry_id,
            entry_type="open",
            created_at=created_at,
            actor_id=actor,
            recipient_id=recipient,
            reply_expected=True,
            subject=normalized_subject,
            content=normalized_content,
            source_refs=refs,
            capture_key=capture_key,
        )
        self._validate_root()
        destination = self.threads_root / derived_thread_id
        if destination.exists() and destination.is_dir() and not any(destination.iterdir()):
            pending_claim = self._read_entry_claims().get(request_entry_id)
            if pending_claim is None:
                raise BuilderThreadConflictError(
                    f"question destination already exists: {derived_thread_id}"
                )
            if (
                pending_claim["thread_id"] != derived_thread_id
                or pending_claim["request_hash"] != _request_hash(entry)
            ):
                raise BuilderThreadConflictError(
                    f"vault-wide entry_id replay conflict: {request_entry_id}"
                )
        for represented in self._load_all_threads(
            allow_pending_claim_id=request_entry_id
        ):
            for item in represented["entries"]:
                if item["entry"]["entry_id"] == request_entry_id:
                    if _same_idempotent_request(item["entry"], entry):
                        return self._result(
                            represented,
                            entry=item["entry"],
                            entry_hash=item["entry_hash"],
                        )
                    raise BuilderThreadConflictError(
                        f"entry_id replay conflict: {request_entry_id}"
                    )
                if item.get("quarantined") or item["entry"].get("capture_key") != capture_key:
                    continue
                if _same_idempotent_request(item["entry"], entry):
                    return self._result(
                        represented,
                        entry=item["entry"],
                        entry_hash=item["entry_hash"],
                    )
                raise BuilderThreadConflictError(
                    f"question already represented by thread {represented['thread_id']}"
                )
        return self._append(entry)

    def reply(
        self,
        thread_id: str,
        *,
        recipient_id: str,
        content: str,
        actor_id: str,
        parent_hash: str,
        source_refs: Iterable[Mapping[str, str]],
        reply_expected: bool = False,
        entry_id: str | None = None,
        created_at: str | None = None,
    ) -> dict[str, Any]:
        if entry_id is None:
            raise BuilderThreadValidationError(
                "reply requires a caller-retained entry_id"
            )
        request_entry_id = _uuid4(entry_id, field="entry_id")
        exact_thread_id = _uuid4(thread_id, field="thread_id")
        self._prepare_write()
        all_threads = self._load_all_threads(
            allow_pending_claim_id=request_entry_id
        )
        if any(
            item["entry"]["entry_id"] == request_entry_id
            for represented in all_threads
            if represented["thread_id"] != exact_thread_id
            for item in represented["entries"]
        ):
            raise BuilderThreadConflictError(
                f"entry_id replay conflict: {request_entry_id}"
            )
        thread = next(
            (
                item
                for item in all_threads
                if item["thread_id"] == exact_thread_id
            ),
            None,
        )
        if thread is None:
            raise BuilderThreadValidationError(f"thread not found: {exact_thread_id}")
        if not isinstance(reply_expected, bool):
            raise BuilderThreadValidationError("reply_expected must be boolean")
        if parent_hash not in thread["artifact_hashes"]:
            raise BuilderThreadValidationError("reply parent hash is missing")
        parent = next(item for item in thread["entries"] if item["entry_hash"] == parent_hash)
        actor = _identity(actor_id, field="actor_id")
        if parent["entry"].get("recipient_id") != actor:
            raise BuilderThreadValidationError("reply actor must match the named parent recipient")
        entry = self._entry_payload(
            thread_id=thread_id,
            entry_id=request_entry_id,
            entry_type="reply",
            created_at=created_at,
            actor_id=actor,
            recipient_id=_identity(recipient_id, field="recipient_id"),
            reply_expected=reply_expected,
            content=_bounded_text(content, field="content", maximum=self.MAX_CONTENT_CHARS),
            source_refs=_source_refs(source_refs),
            parent_hash=self._hash(parent_hash, field="parent_hash"),
        )
        _privacy_check(entry["content"], field="content")
        return self._append(entry)

    def close_thread(
        self,
        thread_id: str,
        *,
        actor_id: str,
        reason: str,
        source_refs: Iterable[Mapping[str, str]] | None = None,
        entry_id: str | None = None,
        created_at: str | None = None,
    ) -> dict[str, Any]:
        if entry_id is None:
            raise BuilderThreadValidationError(
                "close requires a caller-retained entry_id"
            )
        request_entry_id = _uuid4(entry_id, field="entry_id")
        self._prepare_write()
        thread = self._load_thread(
            _uuid4(thread_id, field="thread_id"),
            allow_pending_claim_id=request_entry_id,
        )
        actor = _identity(actor_id, field="actor_id")
        content = _bounded_text(reason, field="reason", maximum=self.MAX_CONTENT_CHARS)
        _privacy_check(content, field="reason")
        refs = _source_refs(source_refs or thread["source_refs"])
        active_closes = self._active_dispositions(thread, "close")
        active_archives = self._active_dispositions(thread, "archive")
        if thread["state"] in {"closed", "archived"}:
            if len(active_closes) != 1:
                raise BuilderThreadConflictError("current close is ambiguous")
            existing = active_closes[0]["entry"]
            if (
                existing["entry_id"] == request_entry_id
                and existing["actor_id"] == actor
                and existing["content"] == content
                and existing["source_refs"] == refs
            ):
                return self._result(thread)
            raise BuilderThreadConflictError("incompatible close retry")
        basis = thread["artifact_hashes"]
        entry = self._entry_payload(
            thread_id=thread_id,
            entry_id=request_entry_id,
            entry_type="close",
            created_at=created_at,
            actor_id=actor,
            content=content,
            source_refs=refs,
            basis_hashes=basis,
            parent_hash=(active_archives[0]["entry_hash"] if len(active_archives) == 1 else None),
            target_hash=(active_closes[0]["entry_hash"] if len(active_closes) == 1 else None),
        )
        return self._append(entry)

    def archive_thread(
        self,
        thread_id: str,
        *,
        actor_id: str,
        entry_id: str | None = None,
        created_at: str | None = None,
    ) -> dict[str, Any]:
        if entry_id is None:
            raise BuilderThreadValidationError(
                "archive requires a caller-retained entry_id"
            )
        request_entry_id = _uuid4(entry_id, field="entry_id")
        self._prepare_write()
        thread = self._load_thread(
            _uuid4(thread_id, field="thread_id"),
            allow_pending_claim_id=request_entry_id,
        )
        actor = _identity(actor_id, field="actor_id")
        active_archives = self._active_dispositions(thread, "archive")
        if thread["state"] == "archived":
            if (
                len(active_archives) == 1
                and active_archives[0]["entry"]["entry_id"] == request_entry_id
                and active_archives[0]["entry"]["actor_id"] == actor
            ):
                return self._result(thread)
            raise BuilderThreadConflictError("incompatible archive retry")
        close_entries = self._active_dispositions(thread, "close")
        if len(close_entries) != 1:
            raise BuilderThreadValidationError("archive requires one current close entry")
        current_close = close_entries[0]
        if not self._snapshot_is_current(thread["entries"], current_close):
            raise BuilderThreadValidationError("archive requires a current close snapshot")
        entry = self._entry_payload(
            thread_id=thread_id,
            entry_id=request_entry_id,
            entry_type="archive",
            created_at=created_at,
            actor_id=actor,
            source_refs=thread["source_refs"],
            basis_hashes=thread["artifact_hashes"],
            target_hash=close_entries[0]["entry_hash"],
            parent_hash=(active_archives[0]["entry_hash"] if len(active_archives) == 1 else None),
        )
        return self._append(entry)

    def quarantine(
        self,
        thread_id: str,
        *,
        artifact_hash: str,
        actor_id: str,
        reason_code: str,
        entry_id: str | None = None,
        created_at: str | None = None,
    ) -> dict[str, Any]:
        if entry_id is None:
            raise BuilderThreadValidationError(
                "quarantine requires a caller-retained entry_id"
            )
        request_entry_id = _uuid4(entry_id, field="entry_id")
        self._prepare_write()
        target = self._hash(artifact_hash, field="artifact_hash")
        thread = self._load_thread(
            _uuid4(thread_id, field="thread_id"),
            structural_only=True,
            allow_pending_claim_id=request_entry_id,
            allow_claim_mismatch_hash=target,
        )
        if target not in thread["artifact_hashes"]:
            raise BuilderThreadValidationError("quarantine target is missing")
        if not isinstance(reason_code, str) or reason_code not in QUARANTINE_REASONS:
            raise BuilderThreadValidationError("unsupported quarantine reason")
        for item in thread["entries"]:
            if (
                item["entry"]["entry_type"] == "quarantine"
                and item["entry"]["target_hash"] == target
            ):
                existing = item["entry"]
                if (
                    existing["entry_id"] == request_entry_id
                    and existing["actor_id"] == _identity(actor_id, field="actor_id")
                    and existing["reason_code"] == reason_code
                ):
                    return self.read_thread(thread_id)
                raise BuilderThreadConflictError("incompatible quarantine retry")
        target_item = next(
            item for item in thread["entries"] if item["entry_hash"] == target
        )
        target_entry = target_item["entry"]
        if target_entry["entry_type"] == "quarantine" and reason_code != "concurrent_conflict":
            try:
                self._validate_entry_shape(
                    target_entry,
                    thread_id=thread["thread_id"],
                    structural_only=False,
                )
                _privacy_check(target_entry.get("subject"), field="subject")
                _privacy_check(target_entry.get("content"), field="content")
            except BuilderThreadPrivacyError:
                pass
            else:
                raise BuilderThreadValidationError(
                    "quarantine-disposition recovery requires concurrent_conflict"
                )
        if reason_code == "concurrent_conflict":
            target_type = target_entry["entry_type"]
            if target_type == "quarantine":
                original_target = target_entry["target_hash"]
                sibling_decisions = [
                    item
                    for item in thread["entries"]
                    if not item["quarantined"]
                    and item["entry"]["entry_type"] == "quarantine"
                    and item["entry"]["target_hash"] == original_target
                ]
            elif target_type in {"close", "archive"}:
                sibling_decisions = self._active_from_entries(
                    thread["entries"], target_type
                )
            else:
                raise BuilderThreadValidationError(
                    "concurrent_conflict requires a conflicting disposition target"
                )
            if len(sibling_decisions) < 2:
                raise BuilderThreadValidationError(
                    "concurrent_conflict requires active sibling dispositions"
                )
        entry = self._entry_payload(
            thread_id=thread_id,
            entry_id=request_entry_id,
            entry_type="quarantine",
            created_at=created_at,
            actor_id=_identity(actor_id, field="actor_id"),
            source_refs=_source_refs(self.INCIDENT_SOURCE_REFS),
            basis_hashes=thread["artifact_hashes"],
            target_hash=target,
            reason_code=reason_code,
        )
        return self._append(entry)

    def read_thread(self, thread_id: str) -> dict[str, Any]:
        return self._render_thread(self._load_thread(_uuid4(thread_id, field="thread_id")))

    def list_threads(
        self,
        *,
        recipient_id: str | None = None,
        include_archived: bool = False,
        limit: int | None = None,
    ) -> dict[str, Any]:
        exact_recipient = (
            _identity(recipient_id, field="recipient_id") if recipient_id is not None else None
        )
        bounded_limit = self._limit(limit)
        threads = []
        all_threads = self._load_all_threads()
        for thread in all_threads:
            if thread["state"] == "archived" and not include_archived:
                continue
            if exact_recipient is not None and not any(
                item["entry"].get("recipient_id") == exact_recipient and not item["quarantined"]
                for item in thread["entries"]
            ):
                continue
            threads.append(self._summary(thread))
        threads.sort(key=lambda item: (item["last_activity"], item["thread_id"]))
        selected = threads[-bounded_limit:]
        return {
            "count": len(selected),
            "snapshot_hash": _snapshot_hash(item["snapshot_hash"] for item in selected),
            "threads": selected,
            "truncated": len(threads) > len(selected),
            "vault_id": self.expected_vault_id,
        }

    def inbox(self, *, recipient_id: str, limit: int | None = None) -> dict[str, Any]:
        recipient = _identity(recipient_id, field="recipient_id")
        bounded_limit = self._limit(limit)
        items: list[dict[str, Any]] = []
        for thread in self._load_all_threads():
            if thread["state"] == "archived":
                continue
            pending = self._pending_for(thread, recipient)
            if pending:
                summary = self._summary(thread)
                summary["pending_entry_hashes"] = pending
                items.append(summary)
        items.sort(key=lambda item: (item["last_activity"], item["thread_id"]))
        selected = items[-bounded_limit:]
        return {
            "count": len(selected),
            "recipient_id": recipient,
            "snapshot_hash": _snapshot_hash(item["snapshot_hash"] for item in selected),
            "threads": selected,
            "truncated": len(items) > len(selected),
            "vault_id": self.expected_vault_id,
        }

    def health(self) -> dict[str, Any]:
        threads = self._load_all_threads()
        counts: dict[str, int] = {}
        for thread in threads:
            counts[thread["state"]] = counts.get(thread["state"], 0) + 1
        return {
            "artifact_count": sum(len(item["entries"]) for item in threads),
            "ok": True,
            "snapshot_hash": _snapshot_hash(
                hash_value for thread in threads for hash_value in thread["artifact_hashes"]
            ),
            "state_counts": dict(sorted(counts.items())),
            "thread_count": len(threads),
            "vault_id": self.expected_vault_id,
        }

    def _limit(self, value: int | None) -> int:
        selected = self.MAX_LIST_THREADS if value is None else value
        if (
            not isinstance(selected, int)
            or isinstance(selected, bool)
            or selected <= 0
            or selected > self.MAX_LIST_THREADS
        ):
            raise BuilderThreadValidationError(f"limit must be 1..{self.MAX_LIST_THREADS}")
        return selected

    def _validate_root(
        self,
        *,
        require_genesis: bool = True,
        allow_committed_temps: bool = False,
    ) -> None:
        if not self.root.is_absolute():
            raise BuilderThreadValidationError("BUILDEROPS_VAULT_ROOT must be absolute")
        if ".." in self.root.parts:
            raise BuilderThreadValidationError("BuilderOps vault root must be normalized")
        current = Path(self.root.anchor)
        for component in self.root.parts[1:]:
            current /= component
            try:
                component_info = current.lstat()
            except FileNotFoundError as exc:
                raise BuilderThreadValidationError("BuilderOps vault root is missing") from exc
            if stat.S_ISLNK(component_info.st_mode):
                raise BuilderThreadValidationError(
                    "symlinked BuilderOps vault ancestor is forbidden"
                )
        try:
            root_info = self.root.lstat()
        except FileNotFoundError as exc:
            raise BuilderThreadValidationError("BuilderOps vault root is missing") from exc
        if stat.S_ISLNK(root_info.st_mode):
            raise BuilderThreadValidationError("BuilderOps vault root symlink is forbidden")
        if not stat.S_ISDIR(root_info.st_mode):
            raise BuilderThreadValidationError("BuilderOps vault root must be a directory")
        if (self.root / "_heimdal").exists():
            raise BuilderThreadValidationError(
                "Mimer/human vault control tree is forbidden for Builder Threads"
            )
        for ancestor in (self.root, *self.root.parents):
            try:
                (ancestor / ".git").lstat()
            except FileNotFoundError:
                continue
            else:
                raise BuilderThreadValidationError(
                    "repository-nested vault root is forbidden for Builder Threads"
                )
        for relative in SCAFFOLD_DIRS:
            _real_directory(self.root / relative, label=relative)
        self._reject_symlinks_and_sqlite(allow_committed_temps=allow_committed_temps)
        if require_genesis:
            vault_genesis = self._read_genesis_at(
                self.root / ".builderops" / VAULT_GENESIS_NAME,
                label="vault genesis",
            )
            if self._read_genesis() != vault_genesis:
                raise BuilderThreadConflictError(
                    "vault and Builder Thread genesis envelopes differ"
                )

    def _reject_symlinks_and_sqlite(self, *, allow_committed_temps: bool = False) -> None:
        for current, directories, files in os.walk(self.root, followlinks=False):
            current_path = Path(current)
            for name in [*directories, *files]:
                path = current_path / name
                if CONFLICT_COPY_RE.search(name):
                    raise BuilderThreadConflictError("conflict-copy artifact detected")
                try:
                    info = path.lstat()
                except FileNotFoundError as exc:
                    if self._is_recognized_temp_path(path):
                        continue
                    if self._is_slot_reservation_path(path):
                        continue
                    if (
                        current_path == self.entry_claims_root
                        and name.endswith(".json")
                        and UUID_RE.fullmatch(Path(name).stem)
                    ):
                        continue
                    raise BuilderThreadValidationError(
                        "artifact changed during validation"
                    ) from exc
                if stat.S_ISLNK(info.st_mode):
                    raise BuilderThreadValidationError("symlink forbidden beneath BuilderOps vault")
                if name.startswith(".tmp-vault-genesis-"):
                    if not allow_committed_temps:
                        self._reject_conflict_or_temp(path)
                    continue
                if stat.S_ISREG(info.st_mode):
                    lower = name.casefold()
                    if lower.endswith((".sqlite", ".sqlite3", ".db")):
                        raise BuilderThreadValidationError(
                            "SQLite artifact forbidden in shared vault"
                        )
                    if not _content_is_local(info) and not _may_be_sqlite_image(info.st_size):
                        continue
                    try:
                        with path.open("rb") as handle:
                            header = handle.read(16)
                    except OSError as exc:
                        raise BuilderThreadValidationError(
                            "artifact unreadable during validation"
                        ) from exc
                    if header == b"SQLite format 3\x00":
                        raise BuilderThreadValidationError(
                            "SQLite artifact forbidden in shared vault"
                        )

    def _is_recognized_temp_path(self, path: Path) -> bool:
        if path.parent == self.root / ".builderops":
            return re.fullmatch(r"\.tmp-vault-genesis-[0-9a-f]{32}", path.name) is not None
        if path.parent == self.builder_root:
            return re.fullmatch(r"\.tmp-genesis-[0-9a-f]{32}", path.name) is not None
        if path.parent == self.entry_claims_root:
            match = TEMP_FILE_RE.fullmatch(path.name)
            return match is not None and UUID_RE.fullmatch(match.group("stem")) is not None
        if (
            path.parent.parent.name == "entries"
            and re.fullmatch(r"[0-9]{3}", path.parent.name)
        ):
            match = TEMP_FILE_RE.fullmatch(path.name)
            return match is not None and HASH_RE.fullmatch(match.group("stem")) is not None
        return False

    def _is_slot_reservation_path(self, path: Path) -> bool:
        return (
            path.name == SLOT_RESERVATION_NAME
            and re.fullmatch(r"[0-9]{3}", path.parent.name) is not None
            and path.parent.parent.name == "entries"
            and UUID_RE.fullmatch(path.parent.parent.parent.name) is not None
        )

    def _prepare_write(self) -> None:
        self._validate_root(
            require_genesis=True,
            allow_committed_temps=True,
        )
        self._recover_committed_temps()
        self._recover_committed_reservations()
        self._validate_root()

    def _recover_committed_temps(self) -> None:
        """Remove only exact temp twins whose final artifact is already installed."""

        candidates = list((self.root / ".builderops").glob(".tmp-vault-genesis-*"))
        if self.builder_root.exists():
            candidates.extend(self.builder_root.glob(".tmp-genesis-*"))
        if self.entry_claims_root.exists():
            candidates.extend(self.entry_claims_root.glob(".tmp-*"))
        if self.threads_root.exists():
            for thread_dir in self.threads_root.iterdir():
                if not UUID_RE.fullmatch(thread_dir.name) or thread_dir.is_symlink():
                    continue
                entries_dir = thread_dir / "entries"
                if entries_dir.is_dir() and not entries_dir.is_symlink():
                    for slot in entries_dir.iterdir():
                        if slot.is_dir() and not slot.is_symlink():
                            candidates.extend(slot.glob(".tmp-*"))
        for temp in sorted(set(candidates)):
            match = TEMP_FILE_RE.fullmatch(temp.name)
            if match is None:
                continue
            try:
                info = temp.lstat()
            except FileNotFoundError:
                continue
            if not stat.S_ISREG(info.st_mode):
                raise BuilderThreadValidationError(
                    "committed-temp recovery requires a regular file"
                )
            final = temp.parent / f"{match.group('stem')}.json"
            try:
                final_info = final.lstat()
            except FileNotFoundError:
                continue
            if not stat.S_ISREG(final_info.st_mode):
                raise BuilderThreadValidationError(
                    "committed-temp recovery final is not a regular file"
                )
            same_inode = (info.st_dev, info.st_ino) == (
                final_info.st_dev,
                final_info.st_ino,
            )
            try:
                temp_bytes = temp.read_bytes()
            except FileNotFoundError as exc:
                # Another exact cleaner may remove this recognized hard-link
                # twin after lstat but before read. A synchronized separate
                # inode still has to survive long enough for byte comparison.
                if same_inode:
                    continue
                raise BuilderThreadValidationError(
                    "temporary artifact changed before twin validation"
                ) from exc
            if final.read_bytes() != temp_bytes:
                raise BuilderThreadConflictError(
                    "temporary artifact conflicts with installed final"
                )
            if re.fullmatch(r"[0-9]{3}", temp.parent.name) and _sha256(temp_bytes) != final.stem:
                raise BuilderThreadConflictError(
                    "temporary artifact hash does not match installed final"
                )
            try:
                temp.unlink()
            except FileNotFoundError:
                continue
            _fsync_directory(temp.parent)

    def _recover_committed_reservations(self) -> None:
        """Finalize only a reservation whose claimed contribution is installed."""

        if not self.threads_root.exists():
            return
        claims = self._read_entry_claims()
        for marker in self.threads_root.glob(
            f"*/entries/[0-9][0-9][0-9]/{SLOT_RESERVATION_NAME}"
        ):
            try:
                entry_id = self._slot_reservation_entry_id(marker.parent)
            except BuilderThreadValidationError:
                if not marker.exists():
                    continue
                raise
            finals = [
                path
                for path in marker.parent.iterdir()
                if path != marker and path.name.endswith(".json")
            ]
            if not finals:
                continue
            if len(finals) != 1:
                raise BuilderThreadConflictError("entry reservation has ambiguous final artifacts")
            final = finals[0]
            if final.is_symlink() or not final.is_file() or not HASH_RE.fullmatch(final.stem):
                raise BuilderThreadValidationError("invalid reserved entry artifact")
            payload, raw = self._read_canonical_json(final)
            if _sha256(raw) != final.stem or payload.get("entry_id") != entry_id:
                raise BuilderThreadConflictError("entry reservation does not match installed final")
            self._validate_entry_shape(
                payload,
                thread_id=marker.parent.parent.parent.name,
                structural_only=True,
            )
            claim = claims.get(entry_id)
            if (
                claim is None
                or claim["thread_id"] != payload.get("thread_id")
                or claim["request_hash"] != _request_hash(payload)
            ):
                raise BuilderThreadConflictError("entry reservation does not match its claim")
            marker.unlink()
            _fsync_directory(marker.parent)

    def _read_genesis(self) -> dict[str, Any]:
        return self._read_genesis_at(
            self.builder_root / GENESIS_NAME,
            label="Builder Thread genesis",
        )

    def _read_genesis_at(self, path: Path, *, label: str) -> dict[str, Any]:
        payload, raw = self._read_canonical_json(path)
        if set(payload) != GENESIS_KEYS or payload.get("schema") != GENESIS_SCHEMA:
            raise BuilderThreadValidationError(f"invalid {label} schema")
        if payload.get("privacy_class") != PRIVACY_CLASS:
            raise BuilderThreadValidationError("invalid Builder Thread privacy class")
        vault_id = _uuid4(payload.get("vault_id"), field="vault_id")
        _validate_timestamp(payload.get("created_at"))
        if vault_id != self.expected_vault_id:
            raise BuilderThreadValidationError(
                "pinned vault identity does not match Builder Thread genesis"
            )
        if _canonical_bytes(payload) != raw:
            raise BuilderThreadValidationError(f"{label} is not canonical JSON")
        return payload

    def _validate_structure(
        self,
        *,
        allow_pending_claim_id: str | None = None,
        required_pending_claim_ids: set[str] | None = None,
    ) -> list[tuple[str, Path]]:
        self._validate_root()
        pending_claim = (
            self._read_entry_claims().get(allow_pending_claim_id)
            if allow_pending_claim_id is not None
            else None
        )
        allowed_root = {GENESIS_NAME, "entry-claims", "threads"}
        result: list[tuple[str, Path]] = []
        for path in self.builder_root.iterdir():
            if self._reject_conflict_or_temp(path):
                continue
            if path.name not in allowed_root:
                raise BuilderThreadValidationError("unknown artifact beneath builder-threads")
        _real_directory(self.threads_root, label="builder-threads/threads")
        _real_directory(
            self.entry_claims_root,
            label="builder-threads/entry-claims",
        )
        for thread_path in self.threads_root.iterdir():
            if self._reject_conflict_or_temp(thread_path):
                continue
            if not thread_path.is_dir() or not UUID_RE.fullmatch(thread_path.name):
                raise BuilderThreadValidationError("unknown artifact beneath threads")
            children = list(thread_path.iterdir())
            if not children and (
                pending_claim is not None
                and pending_claim["thread_id"] == thread_path.name
            ):
                if required_pending_claim_ids is not None:
                    assert allow_pending_claim_id is not None
                    required_pending_claim_ids.add(allow_pending_claim_id)
                continue
            if len(children) != 1 or children[0].name != "entries":
                raise BuilderThreadValidationError(
                    f"incomplete artifact tree for thread {thread_path.name}"
                )
            entries_dir = children[0]
            _real_directory(entries_dir, label=f"{thread_path.name}/entries")
            entry_paths = self._complete_slot_entry_paths(
                entries_dir,
                allow_pending_claim_id=allow_pending_claim_id,
            )
            result.extend((thread_path.name, path) for path in entry_paths)
        return result

    def _complete_slot_entry_paths(
        self,
        entries_dir: Path,
        *,
        allow_pending_claim_id: str | None = None,
    ) -> list[Path]:
        for attempt in range(RECONCILE_ATTEMPTS):
            complete: list[Path] = []
            incomplete = False
            slots = list(entries_dir.iterdir())
            if len(slots) > self.MAX_ENTRIES_PER_THREAD:
                raise BuilderThreadConflictError("thread entry slot bound exceeded")
            if not slots:
                incomplete = True
            for slot in slots:
                if (
                    slot.is_symlink()
                    or not slot.is_dir()
                    or not re.fullmatch(r"[0-9]{3}", slot.name)
                    or int(slot.name) >= self.MAX_ENTRIES_PER_THREAD
                ):
                    raise BuilderThreadValidationError("unknown artifact beneath entries")
                children = list(slot.iterdir())
                if not children:
                    continue
                if len(children) == 1 and children[0].name == SLOT_RESERVATION_NAME:
                    try:
                        reserved_entry_id = self._slot_reservation_entry_id(slot)
                    except BuilderThreadValidationError:
                        if not children[0].exists():
                            incomplete = True
                            continue
                        raise
                    if reserved_entry_id == allow_pending_claim_id:
                        continue
                    incomplete = True
                    continue
                if len(children) != 1 or children[0].name.startswith(".tmp-"):
                    incomplete = True
                    continue
                entry_path = children[0]
                if (
                    entry_path.is_symlink()
                    or not entry_path.is_file()
                    or not entry_path.name.endswith(".json")
                    or not HASH_RE.fullmatch(entry_path.stem)
                ):
                    raise BuilderThreadValidationError("unknown artifact beneath entry slot")
                complete.append(entry_path)
            if not complete:
                if allow_pending_claim_id is not None:
                    return []
                incomplete = True
            if not incomplete:
                return complete
            if attempt < RECONCILE_ATTEMPTS - 1:
                time.sleep(0.05)
        raise BuilderThreadValidationError("incomplete artifact tree")

    def _reject_conflict_or_temp(self, path: Path) -> bool:
        if CONFLICT_COPY_RE.search(path.name):
            raise BuilderThreadConflictError("conflict-copy artifact detected")
        if path.name.startswith(".tmp-"):
            # A complete writer keeps its temp name only until the final hard
            # link has been read back. Give that bounded active window time to
            # converge; a crash/orphan remains and fails closed.
            for _ in range(20):
                try:
                    path.lstat()
                except FileNotFoundError:
                    return True
                time.sleep(0.05)
            raise BuilderThreadValidationError("incomplete artifact detected")
        return False

    def _validate_all(self) -> None:
        self._load_all_threads()

    def _load_all_threads(
        self,
        *,
        allow_pending_claim_id: str | None = None,
    ) -> list[dict[str, Any]]:
        for attempt in range(RECONCILE_ATTEMPTS):
            try:
                return self._load_all_threads_once(
                    allow_pending_claim_id=allow_pending_claim_id
                )
            except _ActiveEntryClaim as exc:
                if attempt == RECONCILE_ATTEMPTS - 1:
                    raise BuilderThreadValidationError(
                        "incomplete vault-wide entry claim"
                    ) from exc
                time.sleep(0.05)
        raise BuilderThreadValidationError("incomplete vault-wide entry claim")

    def _load_all_threads_once(
        self,
        *,
        allow_pending_claim_id: str | None = None,
    ) -> list[dict[str, Any]]:
        required_pending_claim_ids: set[str] = set()
        paths = self._validate_structure(
            allow_pending_claim_id=allow_pending_claim_id,
            required_pending_claim_ids=required_pending_claim_ids,
        )
        thread_ids = sorted({thread_id for thread_id, _ in paths})
        threads = [self._load_thread_from_paths(thread_id, paths) for thread_id in thread_ids]
        captures: dict[str, str] = {}
        entry_ids: set[str] = set()
        for thread in threads:
            for item in thread["entries"]:
                entry_id = item["entry"]["entry_id"]
                if entry_id in entry_ids:
                    raise BuilderThreadConflictError(
                        f"duplicate entry_id across vault: {entry_id}"
                    )
                entry_ids.add(entry_id)
            open_entry = next(
                item["entry"] for item in thread["entries"] if item["entry"]["entry_type"] == "open"
            )
            capture_key = open_entry["capture_key"]
            if thread["thread_id"] != _capture_thread_id(self.expected_vault_id, capture_key):
                raise BuilderThreadConflictError(
                    "thread path does not match deterministic capture identity"
                )
            previous = captures.get(capture_key)
            if previous is not None and previous != thread["thread_id"]:
                raise BuilderThreadConflictError("duplicate capture identity")
            captures[capture_key] = thread["thread_id"]
        self._validate_entry_claims(
            threads,
            allow_pending_claim_id=allow_pending_claim_id,
            required_pending_claim_ids=required_pending_claim_ids,
        )
        return threads

    def _load_thread(
        self,
        thread_id: str,
        *,
        structural_only: bool = False,
        allow_pending_claim_id: str | None = None,
        allow_claim_mismatch_hash: str | None = None,
    ) -> dict[str, Any]:
        for attempt in range(RECONCILE_ATTEMPTS):
            try:
                return self._load_thread_once(
                    thread_id,
                    structural_only=structural_only,
                    allow_pending_claim_id=allow_pending_claim_id,
                    allow_claim_mismatch_hash=allow_claim_mismatch_hash,
                )
            except _ActiveEntryClaim as exc:
                if attempt == RECONCILE_ATTEMPTS - 1:
                    raise BuilderThreadValidationError(
                        "incomplete vault-wide entry claim"
                    ) from exc
                time.sleep(0.05)
        raise BuilderThreadValidationError("incomplete vault-wide entry claim")

    def _load_thread_once(
        self,
        thread_id: str,
        *,
        structural_only: bool = False,
        allow_pending_claim_id: str | None = None,
        allow_claim_mismatch_hash: str | None = None,
    ) -> dict[str, Any]:
        required_pending_claim_ids: set[str] = set()
        paths = self._validate_structure(
            allow_pending_claim_id=allow_pending_claim_id,
            required_pending_claim_ids=required_pending_claim_ids,
        )
        self._validate_vault_wide_entry_ids(paths)
        thread_ids = sorted({item[0] for item in paths})
        validated_threads = [
            self._load_thread_from_paths(
                item,
                paths,
                structural_only=structural_only and item == thread_id,
            )
            for item in thread_ids
        ]
        self._validate_entry_claims(
            validated_threads,
            allow_pending_claim_id=allow_pending_claim_id,
            allow_claim_mismatch_hash=allow_claim_mismatch_hash,
            required_pending_claim_ids=required_pending_claim_ids,
        )
        if thread_id not in thread_ids:
            raise BuilderThreadValidationError(f"thread not found: {thread_id}")
        return next(item for item in validated_threads if item["thread_id"] == thread_id)

    def _validate_vault_wide_entry_ids(self, paths: list[tuple[str, Path]]) -> None:
        entry_ids: set[str] = set()
        for thread_id, path in paths:
            payload, raw = self._read_canonical_json(path)
            if _sha256(raw) != path.stem:
                raise BuilderThreadValidationError(f"artifact hash mismatch: {path.name}")
            self._validate_entry_shape(
                payload,
                thread_id=thread_id,
                structural_only=True,
            )
            entry_id = payload["entry_id"]
            if entry_id in entry_ids:
                raise BuilderThreadConflictError(
                    f"duplicate entry_id across vault: {entry_id}"
                )
            entry_ids.add(entry_id)

    def _read_entry_claims(self) -> dict[str, dict[str, Any]]:
        claims: dict[str, dict[str, Any]] = {}
        for path in self.entry_claims_root.iterdir():
            if self._reject_conflict_or_temp(path):
                continue
            if path.suffix != ".json" or not UUID_RE.fullmatch(path.stem):
                raise BuilderThreadValidationError(
                    "unknown artifact beneath entry-claims"
                )
            try:
                info = path.lstat()
            except FileNotFoundError:
                # A full-bound loser may remove only its canonical claim after
                # this reader enumerated it.
                continue
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
                raise BuilderThreadValidationError(
                    "unknown artifact beneath entry-claims"
                )
            try:
                payload, _raw = self._read_canonical_json(path)
            except BuilderThreadValidationError:
                try:
                    path.lstat()
                except FileNotFoundError:
                    continue
                raise
            normalized = self._normalize_entry_claim(payload)
            entry_id = normalized["entry_id"]
            if entry_id != path.stem:
                raise BuilderThreadValidationError("entry claim path identity mismatch")
            claims[entry_id] = normalized
        return claims

    def _normalize_entry_claim(self, payload: dict[str, Any]) -> dict[str, Any]:
        if set(payload) != ENTRY_CLAIM_KEYS or payload.get("schema") != ENTRY_CLAIM_SCHEMA:
            raise BuilderThreadValidationError("invalid entry claim schema")
        if payload.get("privacy_class") != PRIVACY_CLASS:
            raise BuilderThreadValidationError("invalid entry claim privacy class")
        if payload.get("vault_id") != self.expected_vault_id:
            raise BuilderThreadValidationError("entry claim vault identity mismatch")
        entry_id = _uuid4(payload.get("entry_id"), field="entry_id")
        thread_id = _uuid4(payload.get("thread_id"), field="thread_id")
        request_hash = payload.get("request_hash")
        if not isinstance(request_hash, str):
            raise BuilderThreadValidationError("request_hash must be a SHA-256 digest")
        self._hash(request_hash, field="request_hash")
        return {**payload, "entry_id": entry_id, "thread_id": thread_id}

    def _slot_reservation_entry_id(self, slot: Path) -> str:
        marker = slot / SLOT_RESERVATION_NAME
        if marker.is_symlink() or not marker.is_file():
            raise BuilderThreadValidationError("invalid entry slot reservation")
        payload, raw = self._read_canonical_json(marker)
        normalized = self._normalize_entry_claim(payload)
        if normalized["thread_id"] != slot.parent.parent.name:
            raise BuilderThreadConflictError("entry reservation thread mismatch")
        claim = self.entry_claims_root / f"{normalized['entry_id']}.json"
        claim_payload, claim_raw = self._read_canonical_json(claim)
        if self._normalize_entry_claim(claim_payload) != normalized or claim_raw != raw:
            raise BuilderThreadConflictError("entry reservation does not match its claim")
        return normalized["entry_id"]

    def _validate_entry_claims(
        self,
        threads: list[dict[str, Any]],
        *,
        allow_pending_claim_id: str | None = None,
        allow_claim_mismatch_hash: str | None = None,
        required_pending_claim_ids: set[str] | None = None,
    ) -> None:
        claims = self._read_entry_claims()
        if required_pending_claim_ids and not required_pending_claim_ids.issubset(claims):
            raise _ActiveEntryClaim("pending empty thread claim changed during validation")
        contributions = {
            item["entry"]["entry_id"]: (thread["thread_id"], item)
            for thread in threads
            for item in thread["entries"]
        }
        for entry_id, (thread_id, item) in contributions.items():
            claim = claims.get(entry_id)
            if claim is None:
                raise BuilderThreadConflictError(
                    f"missing vault-wide entry claim: {entry_id}"
                )
            if claim["thread_id"] != thread_id and not (
                item["quarantined"]
                or item["entry_hash"] == allow_claim_mismatch_hash
            ):
                raise BuilderThreadConflictError(
                    f"entry claim thread mismatch: {entry_id}"
                )
            if claim["request_hash"] != _request_hash(item["entry"]) and not (
                item["quarantined"]
                or item["entry_hash"] == allow_claim_mismatch_hash
            ):
                raise BuilderThreadConflictError(
                    f"entry claim request mismatch: {entry_id}"
                )
        orphaned = set(claims) - set(contributions)
        if allow_pending_claim_id is not None:
            orphaned.discard(allow_pending_claim_id)
        if orphaned:
            raise _ActiveEntryClaim("incomplete vault-wide entry claim")

    def _reserve_entry_claim(self, entry: dict[str, Any]) -> bool:
        payload = {
            "entry_id": entry["entry_id"],
            "privacy_class": PRIVACY_CLASS,
            "request_hash": _request_hash(entry),
            "schema": ENTRY_CLAIM_SCHEMA,
            "thread_id": entry["thread_id"],
            "vault_id": self.expected_vault_id,
        }
        claim_path = self.entry_claims_root / f"{entry['entry_id']}.json"
        try:
            claim_info = claim_path.lstat()
        except FileNotFoundError:
            pass
        else:
            if stat.S_ISLNK(claim_info.st_mode) or not stat.S_ISREG(claim_info.st_mode):
                raise BuilderThreadValidationError("entry claim must be a regular file")
            existing, raw = self._read_canonical_json(claim_path)
            if _canonical_bytes(payload) == raw and existing == payload:
                return False
            raise BuilderThreadConflictError(
                f"vault-wide entry_id replay conflict: {entry['entry_id']}"
            )
        try:
            return _atomic_publish(
                claim_path,
                _canonical_bytes(payload),
            )
        except BuilderThreadConflictError as exc:
            raise BuilderThreadConflictError(
                f"vault-wide entry_id replay conflict: {entry['entry_id']}"
            ) from exc

    def _release_unrepresented_entry_claim(self, entry_id: str) -> None:
        claim = self.entry_claims_root / f"{entry_id}.json"
        try:
            claim.unlink()
        except FileNotFoundError:
            return
        _fsync_directory(self.entry_claims_root)

    def _reconcile_lost_thread_destination_claim(
        self,
        *,
        thread_id: str,
        entry_id: str,
        claim_created: bool,
    ) -> None:
        if not claim_created:
            return
        entries_dir = self.threads_root / thread_id / "entries"
        for attempt in range(RECONCILE_ATTEMPTS):
            try:
                pending = self._pending_entry_slot(entries_dir, entry_id)
                if pending is not None:
                    return
                paths = self._complete_slot_entry_paths(entries_dir)
            except (BuilderThreadError, OSError):
                if not entries_dir.exists() and attempt < RECONCILE_ATTEMPTS - 1:
                    time.sleep(0.05)
                    continue
                return
            for path in paths:
                payload, _raw = self._read_canonical_json(path)
                if payload.get("entry_id") == entry_id:
                    return
            if paths:
                self._release_unrepresented_entry_claim(entry_id)
                return
            if attempt < RECONCILE_ATTEMPTS - 1:
                time.sleep(0.05)

    def _load_thread_from_paths(
        self,
        thread_id: str,
        paths: list[tuple[str, Path]],
        *,
        structural_only: bool = False,
    ) -> dict[str, Any]:
        entries: list[dict[str, Any]] = []
        entry_ids: dict[str, str] = {}
        for candidate_thread, path in paths:
            if candidate_thread != thread_id:
                continue
            payload, raw = self._read_canonical_json(path)
            observed_hash = _sha256(raw)
            if observed_hash != path.stem:
                raise BuilderThreadValidationError(f"artifact hash mismatch: {path.name}")
            self._validate_entry_shape(
                payload,
                thread_id=thread_id,
                structural_only=True,
            )
            entry_id = payload["entry_id"]
            previous = entry_ids.get(entry_id)
            if previous is not None:
                raise BuilderThreadConflictError(f"duplicate entry_id: {entry_id}")
            entry_ids[entry_id] = observed_hash
            entries.append(
                {
                    "entry": payload,
                    "entry_hash": observed_hash,
                    "quarantined": False,
                }
            )
        hashes = {item["entry_hash"] for item in entries}
        quarantine_entries = [
            item for item in entries if item["entry"]["entry_type"] == "quarantine"
        ]
        quarantine_by_hash = {
            item["entry_hash"]: item for item in quarantine_entries
        }
        targeted_quarantine_hashes = {
            item["entry"]["target_hash"]
            for item in quarantine_entries
            if item["entry"]["target_hash"]
            in quarantine_by_hash
        }
        active_quarantines = [
            item
            for item in quarantine_entries
            if item["entry_hash"] not in targeted_quarantine_hashes
        ]
        quarantine_targets: dict[str, list[str]] = {}
        redacted_quarantine_hashes: set[str] = set()
        for item in active_quarantines:
            target_hash = item["entry"]["target_hash"]
            if target_hash is None:
                raise BuilderThreadValidationError("quarantine target is required")
            redacted_quarantine_hashes.add(target_hash)
            seen_targets: set[str] = set()
            while (
                item["entry"]["reason_code"] != "concurrent_conflict"
                and target_hash in quarantine_by_hash
            ):
                if target_hash in seen_targets:
                    raise BuilderThreadValidationError("quarantine target cycle")
                seen_targets.add(target_hash)
                targeted_decision = quarantine_by_hash[target_hash]["entry"]
                target_hash = targeted_decision["target_hash"]
                if target_hash is None:
                    raise BuilderThreadValidationError("quarantine target is required")
            quarantine_targets.setdefault(target_hash, []).append(item["entry_hash"])
        quarantine_conflicts = {
            target: decisions
            for target, decisions in quarantine_targets.items()
            if len(decisions) > 1
        }
        if quarantine_conflicts and not structural_only:
            raise BuilderThreadConflictError("multiple active quarantine decisions for one target")
        quarantined = set(quarantine_targets) | redacted_quarantine_hashes
        if None in quarantined:
            raise BuilderThreadValidationError("quarantine target is required")
        if not quarantined.issubset(hashes):
            raise BuilderThreadValidationError("quarantine target is missing")
        for item in entries:
            item["quarantined"] = item["entry_hash"] in quarantined
        self._validate_lineage(
            entries,
            hashes,
            allow_disposition_conflicts=structural_only,
        )
        if not structural_only:
            for item in entries:
                if item["quarantined"]:
                    continue
                self._validate_entry_shape(
                    item["entry"],
                    thread_id=thread_id,
                    structural_only=False,
                )
                _privacy_check(item["entry"].get("subject"), field="subject")
                _privacy_check(item["entry"].get("content"), field="content")
        opens = [item for item in entries if item["entry"]["entry_type"] == "open"]
        if len(opens) != 1:
            raise BuilderThreadValidationError(
                f"thread requires exactly one structural open entry: {thread_id}"
            )
        open_entry = opens[0]["entry"]
        source_refs = open_entry["source_refs"]
        if open_entry["capture_key"] != _capture_key(
            open_entry["recipient_id"], source_refs, open_entry["subject"]
        ):
            raise BuilderThreadConflictError("open capture key does not match its fields")
        state = (
            "conflicted"
            if structural_only and quarantine_conflicts
            else self._derive_state(entries)
        )
        return {
            "artifact_hashes": sorted(hashes),
            "entries": sorted(
                entries,
                key=lambda item: (
                    item["entry"]["created_at"],
                    item["entry_hash"],
                ),
            ),
            "source_refs": (
                _source_refs(self.INCIDENT_SOURCE_REFS) if opens[0]["quarantined"] else source_refs
            ),
            "state": state,
            "subject": (
                "[quarantined]" if opens[0]["quarantined"] else opens[0]["entry"]["subject"]
            ),
            "thread_id": thread_id,
        }

    def _validate_lineage(
        self,
        entries: list[dict[str, Any]],
        hashes: set[str],
        *,
        allow_disposition_conflicts: bool = False,
    ) -> None:
        closes = []
        archives = []
        by_hash = {item["entry_hash"]: item for item in entries}
        for item in entries:
            entry = item["entry"]
            entry_type = entry["entry_type"]
            parent = entry["parent_hash"]
            target = entry["target_hash"]
            if parent is not None and parent not in hashes:
                raise BuilderThreadValidationError("dangling parent hash")
            basis_hashes = entry["basis_hashes"]
            if any(value not in hashes for value in basis_hashes):
                raise BuilderThreadValidationError("dangling basis hash")
            if entry["basis_hash"] != (_snapshot_hash(basis_hashes) if basis_hashes else None):
                raise BuilderThreadValidationError("basis snapshot hash mismatch")
            if item["entry_hash"] in basis_hashes:
                raise BuilderThreadValidationError("disposition basis contains itself")
            if entry_type == "reply" and parent is None:
                raise BuilderThreadValidationError("reply parent hash is required")
            if entry_type == "reply" and (
                by_hash[parent]["entry"].get("recipient_id") != entry["actor_id"]
            ):
                raise BuilderThreadValidationError(
                    "reply actor does not match the named parent recipient"
                )
            if entry_type == "close":
                closes.append(item)
                if parent is not None:
                    if parent not in basis_hashes:
                        raise BuilderThreadValidationError(
                            "superseding close is missing archive from its basis"
                        )
                    if by_hash[parent]["entry"]["entry_type"] != "archive":
                        raise BuilderThreadValidationError(
                            "close can supersede only an archive parent"
                        )
                if target is not None:
                    if target not in hashes or target not in basis_hashes:
                        raise BuilderThreadValidationError(
                            "superseding close target is missing from its basis"
                        )
                    if by_hash[target]["entry"]["entry_type"] != "close":
                        raise BuilderThreadValidationError("close can supersede only a close")
            if entry_type == "archive":
                archives.append(item)
                if target not in hashes:
                    raise BuilderThreadValidationError("archive target is missing")
                if target not in basis_hashes:
                    raise BuilderThreadValidationError("archive basis does not contain its target")
                if by_hash[target]["entry"]["entry_type"] != "close":
                    raise BuilderThreadValidationError("archive must target a close")
                basis_entries = [
                    candidate for candidate in entries if candidate["entry_hash"] in basis_hashes
                ]
                active_basis_closes = self._active_from_entries(basis_entries, "close")
                if len(active_basis_closes) != 1 or active_basis_closes[0]["entry_hash"] != target:
                    raise BuilderThreadValidationError(
                        "archive must target the active close in its basis"
                    )
                if parent is not None:
                    if parent not in basis_hashes:
                        raise BuilderThreadValidationError(
                            "superseding archive is missing from its basis"
                        )
                    if by_hash[parent]["entry"]["entry_type"] != "archive":
                        raise BuilderThreadValidationError("archive can supersede only an archive")
            if entry_type == "quarantine":
                if target not in hashes:
                    raise BuilderThreadValidationError("quarantine target is missing")
                if target not in basis_hashes:
                    raise BuilderThreadValidationError(
                        "quarantine basis does not contain its target"
                    )
        active_closes = self._active_from_entries(entries, "close")
        active_archives = self._active_from_entries(entries, "archive")
        if allow_disposition_conflicts:
            return
        if len(active_closes) > 1:
            raise BuilderThreadConflictError("multiple active close entries")
        if len(active_archives) > 1:
            raise BuilderThreadConflictError("multiple active archive entries")
        if active_archives and (
            len(active_closes) != 1
            or active_archives[0]["entry"]["target_hash"] != active_closes[0]["entry_hash"]
        ):
            raise BuilderThreadValidationError("active archive must target the active close")

    def _derive_state(self, entries: list[dict[str, Any]]) -> str:
        active = [item for item in entries if not item["quarantined"]]
        archives = self._active_from_entries(entries, "archive")
        if archives:
            return "archived" if self._snapshot_is_current(entries, archives[0]) else "needs_review"
        closes = self._active_from_entries(entries, "close")
        if closes:
            return "closed" if self._snapshot_is_current(entries, closes[0]) else "needs_review"
        if any(item["quarantined"] for item in entries):
            return "quarantined"
        if any(item["entry"]["entry_type"] == "reply" for item in active):
            return "answered"
        return "open"

    def _validate_entry_shape(
        self,
        payload: dict[str, Any],
        *,
        thread_id: str,
        structural_only: bool = False,
    ) -> None:
        if set(payload) != ENTRY_KEYS:
            raise BuilderThreadValidationError("unknown or missing contribution fields")
        if payload["schema"] != ENTRY_SCHEMA:
            raise BuilderThreadValidationError("unknown contribution schema")
        if not isinstance(payload["privacy_class"], str):
            raise BuilderThreadValidationError("privacy_class must be text")
        if not structural_only and payload["privacy_class"] != PRIVACY_CLASS:
            raise BuilderThreadPrivacyError("privacy_class must be shared_non_sensitive")
        if payload["vault_id"] != self.expected_vault_id:
            raise BuilderThreadValidationError("contribution vault identity mismatch")
        if _uuid4(payload["thread_id"], field="thread_id") != thread_id:
            raise BuilderThreadValidationError("cross-thread contribution")
        _uuid4(payload["entry_id"], field="entry_id")
        _validate_timestamp(payload["created_at"])
        _identity(
            payload["actor_id"],
            field="actor_id",
            enforce_privacy=not structural_only,
        )
        entry_type = payload["entry_type"]
        if not isinstance(entry_type, str) or entry_type not in ENTRY_TYPES:
            raise BuilderThreadValidationError("unknown contribution entry_type")
        if not isinstance(payload["reply_expected"], bool):
            raise BuilderThreadValidationError("reply_expected must be boolean")
        refs = _source_refs(payload["source_refs"], enforce_privacy=not structural_only)
        if refs != payload["source_refs"]:
            raise BuilderThreadValidationError("source refs are not canonical")
        for field in ("parent_hash", "basis_hash", "target_hash", "capture_key"):
            value = payload[field]
            if value is not None:
                self._hash(value, field=field)
        basis_hashes = payload["basis_hashes"]
        if not isinstance(basis_hashes, list) or len(basis_hashes) > self.MAX_ENTRIES_PER_THREAD:
            raise BuilderThreadValidationError("basis_hashes must be bounded and sorted")
        for value in basis_hashes:
            self._hash(value, field="basis_hashes")
        if basis_hashes != sorted(set(basis_hashes)):
            raise BuilderThreadValidationError("basis_hashes must be bounded and sorted")
        if entry_type in {"open", "reply"}:
            _identity(
                payload["recipient_id"],
                field="recipient_id",
                enforce_privacy=not structural_only,
            )
        elif payload["recipient_id"] is not None:
            raise BuilderThreadValidationError(f"{entry_type} recipient_id must be null")
        subject = payload["subject"]
        content = payload["content"]
        if entry_type == "open":
            _bounded_text(subject, field="subject", maximum=self.MAX_SUBJECT_CHARS)
            _bounded_text(content, field="content", maximum=self.MAX_CONTENT_CHARS)
            if not payload["reply_expected"] or payload["capture_key"] is None:
                raise BuilderThreadValidationError("open capture gate is incomplete")
            if (
                payload["parent_hash"] is not None
                or payload["target_hash"] is not None
                or payload["reason_code"] is not None
                or basis_hashes
                or payload["basis_hash"] is not None
            ):
                raise BuilderThreadValidationError("open shape is invalid")
        elif entry_type == "reply":
            if (
                subject is not None
                or payload["capture_key"] is not None
                or payload["target_hash"] is not None
                or payload["reason_code"] is not None
                or basis_hashes
                or payload["basis_hash"] is not None
            ):
                raise BuilderThreadValidationError("reply shape is invalid")
            _bounded_text(content, field="content", maximum=self.MAX_CONTENT_CHARS)
        elif entry_type == "close":
            if any(
                payload[field] is not None for field in ("subject", "capture_key", "reason_code")
            ):
                raise BuilderThreadValidationError("close shape is invalid")
            if payload["reply_expected"]:
                raise BuilderThreadValidationError("close shape is invalid")
            _bounded_text(content, field="content", maximum=self.MAX_CONTENT_CHARS)
        elif entry_type == "archive":
            if any(
                payload[field] is not None
                for field in ("subject", "content", "capture_key", "reason_code")
            ):
                raise BuilderThreadValidationError("archive shape is invalid")
            if payload["reply_expected"] or payload["target_hash"] is None:
                raise BuilderThreadValidationError("archive shape is invalid")
        elif entry_type == "quarantine":
            if any(
                payload[field] is not None
                for field in ("subject", "content", "capture_key", "parent_hash")
            ):
                raise BuilderThreadValidationError("quarantine shape is invalid")
            if (
                payload["reply_expected"]
                or not isinstance(payload["reason_code"], str)
                or payload["reason_code"] not in QUARANTINE_REASONS
            ):
                raise BuilderThreadValidationError("unsupported quarantine reason")

    def _entry_payload(
        self,
        *,
        thread_id: str,
        entry_type: str,
        actor_id: str,
        source_refs: list[dict[str, str]],
        entry_id: str | None = None,
        created_at: str | None = None,
        recipient_id: str | None = None,
        reply_expected: bool = False,
        subject: str | None = None,
        content: str | None = None,
        parent_hash: str | None = None,
        basis_hashes: Iterable[str] = (),
        target_hash: str | None = None,
        reason_code: str | None = None,
        capture_key: str | None = None,
    ) -> dict[str, Any]:
        basis = sorted(set(basis_hashes))
        return {
            "actor_id": actor_id,
            "basis_hash": _snapshot_hash(basis) if basis else None,
            "basis_hashes": basis,
            "capture_key": capture_key,
            "content": content,
            "created_at": _validate_timestamp(created_at or _stamp()),
            "entry_id": _uuid4(entry_id or str(uuid.uuid4()), field="entry_id"),
            "entry_type": entry_type,
            "parent_hash": parent_hash,
            "privacy_class": PRIVACY_CLASS,
            "reason_code": reason_code,
            "recipient_id": recipient_id,
            "reply_expected": reply_expected,
            "schema": ENTRY_SCHEMA,
            "source_refs": source_refs,
            "subject": subject,
            "target_hash": target_hash,
            "thread_id": _uuid4(thread_id, field="thread_id"),
            "vault_id": self.expected_vault_id,
        }

    def _append(self, entry: dict[str, Any]) -> dict[str, Any]:
        self._validate_entry_shape(entry, thread_id=entry["thread_id"])
        _privacy_check(entry.get("subject"), field="subject")
        _privacy_check(entry.get("content"), field="content")
        raw = _canonical_bytes(entry)
        entry_hash = _sha256(raw)
        try:
            current = self._load_thread(
                entry["thread_id"],
                structural_only=entry["entry_type"] == "quarantine",
                allow_pending_claim_id=entry["entry_id"],
                allow_claim_mismatch_hash=(
                    entry["target_hash"] if entry["entry_type"] == "quarantine" else None
                ),
            )
        except BuilderThreadValidationError as exc:
            if entry["entry_type"] != "open" or "thread not found" not in str(exc):
                raise
            current = None
        if current is not None:
            for item in current["entries"]:
                if item["entry"]["entry_id"] == entry["entry_id"]:
                    if _same_idempotent_request(item["entry"], entry):
                        return self._result(
                            current,
                            entry=item["entry"],
                            entry_hash=item["entry_hash"],
                        )
                    raise BuilderThreadConflictError(
                        f"entry_id replay conflict: {entry['entry_id']}"
                    )
            if entry["entry_type"] == "open":
                raise BuilderThreadConflictError("thread already has an open entry")
        if current is None:
            claim_created = self._reserve_entry_claim(entry)
            try:
                return self._publish_new_thread(
                    entry,
                    raw,
                    entry_hash,
                    recover_existing=not claim_created,
                )
            except _ExistingThreadDestination as exc:
                self._reconcile_lost_thread_destination_claim(
                    thread_id=entry["thread_id"],
                    entry_id=entry["entry_id"],
                    claim_created=claim_created,
                )
                try:
                    reloaded = self._load_thread(entry["thread_id"])
                except BuilderThreadError:
                    raise exc
                represented = next(
                    (
                        item
                        for item in reloaded["entries"]
                        if item["entry"]["entry_id"] == entry["entry_id"]
                    ),
                    None,
                )
                if represented is not None and _same_idempotent_request(
                    represented["entry"], entry
                ):
                    return self._result(
                        reloaded,
                        entry=represented["entry"],
                        entry_hash=represented["entry_hash"],
                    )
                raise exc
        thread_dir = self.threads_root / entry["thread_id"]
        entries_dir = thread_dir / "entries"
        self._reserve_entry_claim(entry)
        try:
            slot = self._reserve_entry_slot(entries_dir, entry["entry_id"])
        except BuilderThreadConflictError:
            self._release_unrepresented_entry_claim(entry["entry_id"])
            raise
        except _ExistingEntryReservation:
            reloaded = self._load_thread(entry["thread_id"])
            represented = next(
                (
                    item
                    for item in reloaded["entries"]
                    if item["entry"]["entry_id"] == entry["entry_id"]
                ),
                None,
            )
            if represented is None:
                raise BuilderThreadConflictError(
                    "entry reservation changed during reconciliation"
                )
            if _same_idempotent_request(represented["entry"], entry):
                return self._result(
                    reloaded,
                    entry=represented["entry"],
                    entry_hash=represented["entry_hash"],
                )
            raise BuilderThreadConflictError(
                f"entry_id replay conflict: {entry['entry_id']}"
            ) from None
        try:
            _atomic_publish(slot / f"{entry_hash}.json", raw)
            self._finalize_entry_slot(slot, entry["entry_id"])
        except Exception:
            if not any(slot.iterdir()):
                slot.rmdir()
                _fsync_directory(entries_dir)
            raise
        reloaded = self._load_thread(entry["thread_id"])
        return self._result(reloaded, entry=entry, entry_hash=entry_hash)

    def _publish_new_thread(
        self,
        entry: dict[str, Any],
        raw: bytes,
        entry_hash: str,
        *,
        recover_existing: bool = False,
    ) -> dict[str, Any]:
        """Claim the deterministic destination without overwriting any existing tree."""

        thread_dir = self.threads_root / entry["thread_id"]
        try:
            thread_dir.mkdir(mode=0o700, parents=False, exist_ok=False)
        except FileExistsError as exc:
            entries_dir = thread_dir / "entries"
            _real_directory(thread_dir, label="thread destination")
            if recover_existing and not any(thread_dir.iterdir()):
                _safe_mkdir(entries_dir)
            if (
                recover_existing
                and entries_dir.is_dir()
                and not entries_dir.is_symlink()
                and {path.name for path in thread_dir.iterdir()} == {"entries"}
            ):
                slot = self._pending_entry_slot(entries_dir, entry["entry_id"])
                if slot is None:
                    slot = self._reserve_entry_slot(entries_dir, entry["entry_id"])
                _atomic_publish(slot / f"{entry_hash}.json", raw)
                self._finalize_entry_slot(slot, entry["entry_id"])
                reloaded = self._load_thread(entry["thread_id"])
                return self._result(reloaded, entry=entry, entry_hash=entry_hash)
            raise _ExistingThreadDestination(
                f"question destination already exists: {entry['thread_id']}"
            ) from exc
        _fsync_directory(self.threads_root)
        entries_dir = thread_dir / "entries"
        _safe_mkdir(entries_dir)
        slot = self._reserve_entry_slot(entries_dir, entry["entry_id"])
        _atomic_publish(slot / f"{entry_hash}.json", raw)
        self._finalize_entry_slot(slot, entry["entry_id"])
        reloaded = self._load_thread(entry["thread_id"])
        return self._result(reloaded, entry=entry, entry_hash=entry_hash)

    def _reserve_entry_slot(self, entries_dir: Path, entry_id: str) -> Path:
        start = int(hashlib.sha256(entry_id.encode()).hexdigest(), 16) % self.MAX_ENTRIES_PER_THREAD
        for offset in range(self.MAX_ENTRIES_PER_THREAD):
            slot = entries_dir / f"{(start + offset) % self.MAX_ENTRIES_PER_THREAD:03d}"
            try:
                slot.mkdir(mode=0o700, parents=False, exist_ok=False)
            except FileExistsError:
                _real_directory(slot, label="entry slot")
                reserved_entry_id = self._reserved_slot_entry_id(slot)
                if reserved_entry_id == entry_id:
                    return slot
                if reserved_entry_id is not None:
                    continue
            else:
                _fsync_directory(entries_dir)
            reservation = slot / SLOT_RESERVATION_NAME
            claim = self.entry_claims_root / f"{entry_id}.json"
            try:
                os.link(claim, reservation)
            except FileExistsError:
                if self._reserved_slot_entry_id(slot) == entry_id:
                    return slot
                continue
            _fsync_directory(slot)
            return slot
        raise BuilderThreadConflictError(
            f"thread entry bound reached ({self.MAX_ENTRIES_PER_THREAD})"
        )

    def _reserved_slot_entry_id(self, slot: Path) -> str | None:
        for attempt in range(21):
            children = list(slot.iterdir())
            if any(path.name == SLOT_RESERVATION_NAME for path in children):
                marker = slot / SLOT_RESERVATION_NAME
                try:
                    return self._slot_reservation_entry_id(slot)
                except BuilderThreadValidationError:
                    if not marker.exists() and attempt < 20:
                        time.sleep(0.05)
                        continue
                    raise
            finals = [
                path
                for path in children
                if path.is_file()
                and not path.is_symlink()
                and path.name.endswith(".json")
                and HASH_RE.fullmatch(path.stem)
            ]
            if len(finals) == 1:
                payload, raw = self._read_canonical_json(finals[0])
                if _sha256(raw) != finals[0].stem:
                    raise BuilderThreadValidationError("artifact hash mismatch")
                self._validate_entry_shape(
                    payload,
                    thread_id=slot.parent.parent.name,
                    structural_only=True,
                )
                return payload["entry_id"]
            if not children:
                return None
            if attempt < 20 and (
                not children or all(path.name.startswith(".tmp-") for path in children)
            ):
                time.sleep(0.05)
                continue
            raise BuilderThreadValidationError("incomplete artifact tree")
        raise BuilderThreadValidationError("incomplete artifact tree")

    def _finalize_entry_slot(self, slot: Path, entry_id: str) -> None:
        reservation = slot / SLOT_RESERVATION_NAME
        try:
            reserved_entry_id = self._slot_reservation_entry_id(slot)
        except BuilderThreadValidationError as exc:
            if not reservation.exists():
                return
            raise exc
        if reserved_entry_id != entry_id:
            raise BuilderThreadConflictError("entry reservation changed before finalization")
        try:
            reservation.unlink()
        except FileNotFoundError:
            pass
        _fsync_directory(slot)

    def _pending_entry_slot(self, entries_dir: Path, entry_id: str) -> Path | None:
        for slot in entries_dir.iterdir():
            if not slot.is_dir() or slot.is_symlink():
                continue
            marker = slot / SLOT_RESERVATION_NAME
            if marker.exists():
                try:
                    reserved_entry_id = self._slot_reservation_entry_id(slot)
                except BuilderThreadValidationError:
                    if not marker.exists():
                        continue
                    raise
                if reserved_entry_id == entry_id:
                    return slot
        return None

    def _read_canonical_json(self, path: Path) -> tuple[dict[str, Any], bytes]:
        try:
            raw = path.read_bytes()
        except FileNotFoundError as exc:
            raise BuilderThreadValidationError("required artifact is missing") from exc
        if not raw.endswith(b"\n") or b"\x00" in raw or len(raw) > 128_000:
            raise BuilderThreadValidationError("partial or oversized artifact")
        try:
            payload = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BuilderThreadValidationError("invalid JSON artifact") from exc
        if not isinstance(payload, dict):
            raise BuilderThreadValidationError("JSON artifact must be an object")
        if _canonical_bytes(payload) != raw:
            raise BuilderThreadValidationError("non-canonical JSON artifact")
        return payload, raw

    def _hash(self, value: str, *, field: str) -> str:
        if not isinstance(value, str) or not HASH_RE.fullmatch(value):
            raise BuilderThreadValidationError(f"{field} must be lowercase SHA-256")
        return value

    def _active_from_entries(
        self, entries: list[dict[str, Any]], entry_type: str
    ) -> list[dict[str, Any]]:
        candidates = [
            item
            for item in entries
            if not item["quarantined"] and item["entry"]["entry_type"] == entry_type
        ]
        superseded = {
            item["entry"]["target_hash" if entry_type == "close" else "parent_hash"]
            for item in candidates
            if item["entry"]["target_hash" if entry_type == "close" else "parent_hash"] is not None
        }
        if entry_type == "archive":
            superseded.update(
                item["entry"]["parent_hash"]
                for item in entries
                if not item["quarantined"]
                and item["entry"]["entry_type"] == "close"
                and item["entry"]["parent_hash"] is not None
            )
        return [item for item in candidates if item["entry_hash"] not in superseded]

    def _active_dispositions(self, thread: dict[str, Any], entry_type: str) -> list[dict[str, Any]]:
        return self._active_from_entries(thread["entries"], entry_type)

    def _snapshot_is_current(
        self, entries: list[dict[str, Any]], disposition: dict[str, Any]
    ) -> bool:
        ignored_hashes = {
            item["entry_hash"]
            for item in entries
            if item["quarantined"] or item["entry"]["entry_type"] == "quarantine"
        }
        state_hashes = {
            item["entry_hash"]
            for item in entries
            if not item["quarantined"] and item["entry"]["entry_type"] != "quarantine"
        }
        expected = state_hashes - {disposition["entry_hash"]}
        effective_basis = set(disposition["entry"]["basis_hashes"]) - ignored_hashes
        return effective_basis == expected

    def _pending_for(self, thread: dict[str, Any], recipient: str) -> list[str]:
        active = [item for item in thread["entries"] if not item["quarantined"]]
        answered = {
            item["entry"]["parent_hash"]
            for item in active
            if item["entry"]["entry_type"] == "reply"
            and any(
                parent["entry_hash"] == item["entry"]["parent_hash"]
                and parent["entry"].get("recipient_id") == item["entry"]["actor_id"]
                for parent in active
            )
        }
        return sorted(
            item["entry_hash"]
            for item in active
            if item["entry"].get("recipient_id") == recipient
            and item["entry"].get("reply_expected") is True
            and item["entry_hash"] not in answered
        )

    def _summary(self, thread: dict[str, Any]) -> dict[str, Any]:
        active = [item for item in thread["entries"] if not item["quarantined"]]
        return {
            "entry_count": len(thread["entries"]),
            "last_activity": max(item["entry"]["created_at"] for item in thread["entries"]),
            "snapshot_hash": _snapshot_hash(thread["artifact_hashes"]),
            "source_refs": thread["source_refs"],
            "state": thread["state"],
            "subject": thread["subject"],
            "thread_id": thread["thread_id"],
            "quarantined_count": len(thread["entries"]) - len(active),
        }

    def _render_thread(self, thread: dict[str, Any]) -> dict[str, Any]:
        entries = []
        selected = thread["entries"][-self.MAX_ENTRIES_PER_THREAD :]
        for item in selected:
            if item["quarantined"]:
                entries.append(
                    {
                        "entry_hash": item["entry_hash"],
                        "entry_id": item["entry"]["entry_id"],
                        "entry_type": item["entry"]["entry_type"],
                        "quarantined": True,
                    }
                )
            else:
                entries.append(
                    {
                        "entry": item["entry"],
                        "entry_hash": item["entry_hash"],
                        "quarantined": False,
                    }
                )
        return {
            **self._summary(thread),
            "entries": entries,
            "entries_truncated": len(thread["entries"]) > len(selected),
        }

    def _result(
        self,
        thread: dict[str, Any],
        *,
        entry: dict[str, Any] | None = None,
        entry_hash: str | None = None,
    ) -> dict[str, Any]:
        payload = self._render_thread(thread)
        if entry is not None:
            payload["entry"] = entry
            payload["entry_hash"] = entry_hash
        return payload
