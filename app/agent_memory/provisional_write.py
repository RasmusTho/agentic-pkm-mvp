"""Governed producer for provisional, direct-write memory.

This module owns the only provisional write seam. It writes meaning-bearing
content to Vault Markdown and persists only content-free lifecycle receipts.
It deliberately imports no promotion or materialization path.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import fcntl
import json
import logging
import os
from pathlib import Path
import tempfile
from typing import Annotated, Callable, Iterator, Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
import yaml
from yaml.constructor import ConstructorError
from yaml.nodes import MappingNode

from app.agent_memory.candidate import MemoryType
from app.agent_memory.provisional_memory import (
    ProvisionalEvidenceRole,
    ProvisionalFailureCode,
    ProvisionalLifecycleReceipt,
    ProvisionalLifecycleTransition,
    ProvisionalMarkdownArtifact,
    ProvisionalMemoryReconciliation,
    ProvisionalSensitivity,
    rebuild_provisional_memory,
)
from app.knowledge.write_ops import write_note_relative
from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard

PROVISIONAL_MEMORY_WRITE_ACTION = "memory.provisional.write"
PROVISIONAL_MEMORY_DIR = "Memory/Provisional"
DEFAULT_PROVISIONAL_RECEIPTS_PATH = Path(
    "runtime/agent_memory/provisional_memory_receipts.jsonl"
)
_VISIBLE_PREFIX = (
    "# Provisional memory\n\n"
    "> [!warning] Provisional / low trust — not authority\n"
    "> This memory may support reading or a cited proposal, but never APPLY or tool use.\n\n"
)
_PROVISIONAL_FRONTMATTER_KEYS = frozenset(
    {
        "uuid",
        "artifact_class",
        "artifact_type",
        "source_role",
        "authority_state",
        "evidence_role",
        "review_state",
        "scope_id",
        "principal_id",
        "memory_type",
        "sensitivity",
        "created_by",
        "created_at",
        "provenance_event_ids",
        "labels",
    }
)
logger = logging.getLogger(__name__)
ProvenanceRef = Annotated[str, Field(min_length=1, max_length=128)]


class _UniqueKeySafeLoader(yaml.SafeLoader):
    """Safe YAML loader that refuses ambiguous duplicate mapping keys."""


def _construct_unique_mapping(
    loader: yaml.SafeLoader,
    node: MappingNode,
    deep: bool = False,
) -> dict[object, object]:
    loader.flatten_mapping(node)
    mapping: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as exc:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "found an unhashable mapping key",
                key_node.start_mark,
            ) from exc
        if duplicate:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeySafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


class ProvisionalWriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    scope_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
    principal_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
    memory_type: MemoryType
    sensitivity: ProvisionalSensitivity
    content: str = Field(min_length=1)
    provenance_event_ids: tuple[ProvenanceRef, ...] = Field(min_length=1)

    @field_validator("content")
    @classmethod
    def _require_meaningful_content(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("content must contain non-whitespace characters")
        return stripped

    @field_validator("provenance_event_ids")
    @classmethod
    def _require_meaningful_provenance(
        cls, value: tuple[str, ...]
    ) -> tuple[str, ...]:
        if any(not item.strip() for item in value):
            raise ValueError("provenance references must not be blank")
        return tuple(item.strip() for item in value)


class ProvisionalWriteResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    reconciliation: ProvisionalMemoryReconciliation
    lifecycle_receipt: ProvisionalLifecycleReceipt


class ProvisionalReceiptWriter(Protocol):
    def append(self, receipt: ProvisionalLifecycleReceipt) -> None: ...

    def list_for(self, memory_id: UUID) -> tuple[ProvisionalLifecycleReceipt, ...]: ...


class ProvisionalMemoryWriteError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        reconciliation: ProvisionalMemoryReconciliation,
        lifecycle_receipt: ProvisionalLifecycleReceipt | None = None,
    ) -> None:
        super().__init__(message)
        self.reconciliation = reconciliation
        self.lifecycle_receipt = lifecycle_receipt


class ProvisionalReceiptStoreError(RuntimeError):
    """Receipt ledger is unreadable or failed to persist atomically enough."""


class ProvisionalReceiptStore:
    """Append-only, content-free lifecycle receipt JSONL store."""

    def __init__(self, path: Path | None = None) -> None:
        configured = os.getenv("PROVISIONAL_MEMORY_RECEIPTS_PATH")
        self.path = path or (Path(configured).expanduser() if configured else DEFAULT_PROVISIONAL_RECEIPTS_PATH)

    def append(self, receipt: ProvisionalLifecycleReceipt) -> None:
        payload = receipt.content_free_payload()
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with _receipt_ledger_lock(self.path, shared=False):
            existing = self.path.read_bytes() if self.path.exists() else b""
            _validate_ledger_bytes(existing)
            descriptor, staged_name = tempfile.mkstemp(
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
            )
            staged_path = Path(staged_name)
            try:
                try:
                    os.fchmod(descriptor, 0o600)
                except Exception:
                    os.close(descriptor)
                    raise
                with os.fdopen(descriptor, "wb", closefd=True) as handle:
                    handle.write(existing)
                    handle.write(encoded.encode("utf-8"))
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(staged_path, self.path)
                try:
                    _fsync_directory(self.path.parent)
                except Exception:
                    expected = existing + encoded.encode("utf-8")
                    if self.path.read_bytes() == expected:
                        logger.warning(
                            "receipt ledger directory fsync failed after a visible "
                            "atomic replace; treating the append as committed"
                        )
                    else:
                        raise
            except Exception:
                staged_path.unlink(missing_ok=True)
                raise

    def list_for(self, memory_id: UUID) -> tuple[ProvisionalLifecycleReceipt, ...]:
        if not self.path.exists():
            return ()
        with _receipt_ledger_lock(self.path, shared=True):
            raw = self.path.read_bytes()
        return tuple(
            receipt
            for receipt in _receipts_from_ledger(raw)
            if receipt.memory_id == memory_id
        )


@contextmanager
def _receipt_ledger_lock(path: Path, *, shared: bool) -> Iterator[None]:
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as lock_handle:
        os.chmod(lock_path, 0o600)
        fcntl.flock(
            lock_handle.fileno(),
            fcntl.LOCK_SH if shared else fcntl.LOCK_EX,
        )
        try:
            yield
        finally:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


def _validate_ledger_bytes(raw: bytes) -> None:
    _receipts_from_ledger(raw)


def _receipts_from_ledger(raw: bytes) -> tuple[ProvisionalLifecycleReceipt, ...]:
    if not raw:
        return ()
    if not raw.endswith(b"\n"):
        raise ProvisionalReceiptStoreError(
            "provisional receipt ledger ends with an incomplete line"
        )
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProvisionalReceiptStoreError(
            "provisional receipt ledger is not valid UTF-8"
        ) from exc
    receipts: list[ProvisionalLifecycleReceipt] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            receipt = ProvisionalLifecycleReceipt.model_validate_json(line)
        except ValidationError as exc:
            raise ProvisionalReceiptStoreError(
                "provisional receipt ledger contains an invalid line"
            ) from exc
        receipts.append(receipt)
    return tuple(receipts)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def assert_provisional_trust_tier(artifact: ProvisionalMarkdownArtifact) -> None:
    """Production trust ceiling: direct writes are always low-trust and inert."""
    if (
        artifact.source_role != "agent_memory"
        or artifact.authority_state != "noncanonical"
        or artifact.review_state != "unreviewed"
        or artifact.evidence_role not in set(ProvisionalEvidenceRole)
    ):
        raise ValueError("provisional memory trust ceiling violated")


def write_provisional_memory(
    request: ProvisionalWriteRequest,
    *,
    vault_root: Path,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
    receipt_store: ProvisionalReceiptWriter | None = None,
    trust_tier_guard: Callable[[ProvisionalMarkdownArtifact], None] | None = None,
    now: Callable[[], datetime] | None = None,
) -> ProvisionalWriteResult:
    """Write one provisional Markdown artifact and its lifecycle receipts."""
    store = receipt_store or ProvisionalReceiptStore()
    clock = now or (lambda: datetime.now(timezone.utc))
    memory_id = uuid4()
    artifact_ref = f"vault://{PROVISIONAL_MEMORY_DIR}/{memory_id}.md"
    artifact = ProvisionalMarkdownArtifact(
        memory_id=memory_id,
        artifact_ref=artifact_ref,
        scope_id=request.scope_id,
        principal_id=request.principal_id,
        memory_type=request.memory_type,
        sensitivity=request.sensitivity,
        content=request.content,
        created_by="agent://companion",
        created_at=_aware_utc(clock()),
        provenance_event_ids=request.provenance_event_ids,
    )

    (trust_tier_guard or assert_provisional_trust_tier)(artifact)
    write_guard.assert_writes_allowed(PROVISIONAL_MEMORY_WRITE_ACTION)

    staged_at = _aware_utc(clock())
    staged = ProvisionalLifecycleReceipt(
        receipt_id=uuid4(),
        memory_id=memory_id,
        artifact_ref=artifact_ref,
        transition=ProvisionalLifecycleTransition.WRITE_STAGED,
        actor_ref="agent",
        occurred_at=staged_at,
    )
    try:
        store.append(staged)
    except Exception as exc:
        reconciliation = rebuild_provisional_memory(
            memory_id=memory_id,
            artifact_ref=artifact_ref,
            artifact=None,
            receipts=(),
        )
        raise ProvisionalMemoryWriteError(
            "provisional staged receipt persistence failed",
            reconciliation=reconciliation,
        ) from exc

    note_rel = f"{PROVISIONAL_MEMORY_DIR}/{memory_id}.md"
    try:
        write_note_relative(
            note_rel,
            render_provisional_markdown(artifact),
            vault_root=vault_root,
            action=PROVISIONAL_MEMORY_WRITE_ACTION,
            write_guard=write_guard,
            writer_identity="agent_memory.provisional_write",
        )
    except Exception as exc:
        failed = ProvisionalLifecycleReceipt(
            receipt_id=uuid4(),
            memory_id=memory_id,
            artifact_ref=artifact_ref,
            transition=ProvisionalLifecycleTransition.WRITE_FAILED,
            actor_ref="agent",
            occurred_at=_after(staged_at, clock()),
            error_code=_failure_code(exc),
        )
        try:
            store.append(failed)
        except Exception as receipt_exc:
            logger.warning("failed to persist provisional write failure: %s", receipt_exc)
        receipts = _safe_receipts(store, memory_id)
        reconciliation = rebuild_provisional_memory(
            memory_id=memory_id,
            artifact_ref=artifact_ref,
            artifact=None,
            receipts=receipts,
        )
        raise ProvisionalMemoryWriteError(
            "provisional Markdown write failed",
            reconciliation=reconciliation,
            lifecycle_receipt=failed,
        ) from exc

    created = ProvisionalLifecycleReceipt(
        receipt_id=uuid4(),
        memory_id=memory_id,
        artifact_ref=artifact_ref,
        transition=ProvisionalLifecycleTransition.CREATED,
        actor_ref="agent",
        occurred_at=_after(staged_at, clock()),
        artifact_digest=artifact.artifact_digest,
    )
    try:
        store.append(created)
    except Exception as exc:
        receipts = tuple(
            receipt
            for receipt in _safe_receipts(store, memory_id)
            if receipt.receipt_id != created.receipt_id
        )
        reconciliation = rebuild_provisional_memory(
            memory_id=memory_id,
            artifact_ref=artifact_ref,
            artifact=_safe_artifact(vault_root / note_rel, vault_root=vault_root),
            receipts=receipts,
        )
        raise ProvisionalMemoryWriteError(
            "provisional lifecycle receipt persistence failed",
            reconciliation=reconciliation,
        ) from exc

    persisted_artifact = _safe_artifact(vault_root / note_rel, vault_root=vault_root)
    receipts = _safe_receipts(store, memory_id)
    reconciliation = rebuild_provisional_memory(
        memory_id=memory_id,
        artifact_ref=artifact_ref,
        artifact=persisted_artifact,
        receipts=receipts,
    )
    if reconciliation.record is None:
        raise ProvisionalMemoryWriteError(
            "provisional write did not reconcile to a readable record",
            reconciliation=reconciliation,
            lifecycle_receipt=created,
        )
    return ProvisionalWriteResult(
        reconciliation=reconciliation,
        lifecycle_receipt=created,
    )


def _safe_receipts(
    store: ProvisionalReceiptWriter,
    memory_id: UUID,
) -> tuple[ProvisionalLifecycleReceipt, ...]:
    try:
        return store.list_for(memory_id)
    except Exception as exc:
        logger.warning("provisional receipt ledger could not be read: %s", exc)
        return ()


def _safe_artifact(
    path: Path,
    *,
    vault_root: Path,
) -> ProvisionalMarkdownArtifact | None:
    try:
        return load_provisional_markdown(path, vault_root=vault_root)
    except Exception as exc:
        logger.warning("provisional Markdown could not be read back: %s", exc)
        return None


def render_provisional_markdown(artifact: ProvisionalMarkdownArtifact) -> str:
    frontmatter = {
        "uuid": str(artifact.memory_id),
        "artifact_class": "agentic_memory",
        "artifact_type": "provisional_memory",
        "source_role": artifact.source_role,
        "authority_state": artifact.authority_state,
        "evidence_role": artifact.evidence_role.value,
        "review_state": artifact.review_state.value,
        "scope_id": artifact.scope_id,
        "principal_id": artifact.principal_id,
        "memory_type": artifact.memory_type.value,
        "sensitivity": artifact.sensitivity.value,
        "created_by": artifact.created_by,
        "created_at": artifact.created_at.isoformat().replace("+00:00", "Z"),
        "provenance_event_ids": list(artifact.provenance_event_ids),
        "labels": ["provisional-memory", "low-trust", "not-authority"],
    }
    yaml_block = yaml.safe_dump(frontmatter, sort_keys=True, allow_unicode=True).strip()
    return f"---\n{yaml_block}\n---\n\n{_VISIBLE_PREFIX}{artifact.content}\n"


def load_provisional_markdown(
    path: Path,
    *,
    vault_root: Path,
) -> ProvisionalMarkdownArtifact:
    if ".." in path.parts:
        raise ValueError("provisional Markdown path must be lexical-canonical")
    if path.is_symlink():
        raise ValueError("provisional Markdown path must not be a symlink")
    resolved_root = vault_root.expanduser().resolve()
    resolved_path = path.expanduser().resolve()
    relative_path = resolved_path.relative_to(resolved_root)
    if relative_path.parent.as_posix() != PROVISIONAL_MEMORY_DIR:
        raise ValueError("physical provisional Markdown directory is not canonical")
    try:
        path_memory_id = UUID(relative_path.stem)
    except ValueError as exc:
        raise ValueError("physical provisional Markdown filename is not a UUID") from exc
    if path_memory_id.version != 4 or relative_path.suffix != ".md":
        raise ValueError("physical provisional Markdown filename is not canonical")
    if relative_path.name != f"{path_memory_id}.md":
        raise ValueError("physical provisional Markdown filename is not canonical")
    raw = path.read_text(encoding="utf-8")
    if not raw.startswith("---\n") or "\n---\n" not in raw[4:]:
        raise ValueError("provisional Markdown requires YAML frontmatter")
    yaml_text, body = raw[4:].split("\n---\n", 1)
    metadata = yaml.load(yaml_text, Loader=_UniqueKeySafeLoader)
    if not isinstance(metadata, dict):
        raise ValueError("provisional Markdown frontmatter must be a mapping")
    if set(metadata) != _PROVISIONAL_FRONTMATTER_KEYS:
        raise ValueError("provisional Markdown frontmatter keys must match the schema exactly")
    if metadata.get("artifact_class") != "agentic_memory" or metadata.get("artifact_type") != "provisional_memory":
        raise ValueError("not a provisional-memory artifact")
    labels = metadata.get("labels")
    if labels != ["provisional-memory", "low-trust", "not-authority"]:
        raise ValueError("provisional-memory visibility labels are required")
    provenance_event_ids = metadata["provenance_event_ids"]
    if (
        not isinstance(provenance_event_ids, list)
        or not provenance_event_ids
        or any(
            not isinstance(item, str) or not item.strip()
            for item in provenance_event_ids
        )
    ):
        raise ValueError(
            "provisional-memory provenance_event_ids must be a non-empty string sequence"
        )
    normalized_body = body.lstrip("\n")
    if not normalized_body.startswith(_VISIBLE_PREFIX):
        raise ValueError("provisional-memory low-trust warning is required")
    content = normalized_body.removeprefix(_VISIBLE_PREFIX).rstrip("\n")
    memory_id = UUID(str(metadata["uuid"]))
    if memory_id != path_memory_id:
        raise ValueError("physical provisional Markdown path does not match its UUID")
    return ProvisionalMarkdownArtifact(
        memory_id=memory_id,
        artifact_ref=f"vault://{PROVISIONAL_MEMORY_DIR}/{memory_id}.md",
        scope_id=metadata["scope_id"],
        principal_id=metadata["principal_id"],
        memory_type=metadata["memory_type"],
        evidence_role=metadata["evidence_role"],
        sensitivity=metadata["sensitivity"],
        content=content,
        created_by=metadata["created_by"],
        created_at=metadata["created_at"],
        provenance_event_ids=tuple(provenance_event_ids),
        source_role=metadata["source_role"],
        authority_state=metadata["authority_state"],
        review_state=metadata["review_state"],
    )


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("clock must return a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _after(previous: datetime, value: datetime) -> datetime:
    current = _aware_utc(value)
    return current if current > previous else previous + timedelta(microseconds=1)


def _failure_code(exc: Exception) -> ProvisionalFailureCode:
    name = type(exc).__name__.lower()
    if "permission" in name:
        return ProvisionalFailureCode.PERMISSION_DENIED
    if "conflict" in name:
        return ProvisionalFailureCode.WRITE_CONFLICT
    return ProvisionalFailureCode.VAULT_WRITE_FAILED


__all__ = [
    "DEFAULT_PROVISIONAL_RECEIPTS_PATH",
    "PROVISIONAL_MEMORY_WRITE_ACTION",
    "ProvisionalMemoryWriteError",
    "ProvisionalReceiptStoreError",
    "ProvisionalReceiptStore",
    "ProvisionalWriteRequest",
    "ProvisionalWriteResult",
    "assert_provisional_trust_tier",
    "load_provisional_markdown",
    "render_provisional_markdown",
    "write_provisional_memory",
]
