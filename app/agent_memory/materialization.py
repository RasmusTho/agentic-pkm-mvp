from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterator, cast
from uuid import NAMESPACE_URL, uuid4, uuid5

import yaml

from app.agent_memory.candidate import MemoryType, validated_memory_scope_id
from app.agent_memory.review_decision_store import (
    ReviewDecisionRecord,
    ReviewDecisionStore,
    ReviewDecisionStoreError,
    review_candidate_digest,
)
from app.agent_memory.review_queue import ReviewDecision, ReviewEntry, ReviewStatus
from app.events.types import PROMOTION_TRANSITION_APPLIED
from app.governance.governed_write import (
    CONTRACT_VERSION as GOVERNED_WRITE_CONTRACT_VERSION,
    AuthorityReceipt,
    DecisionToken,
    GovernedWriteAdapter,
    GovernedWriteGrant,
    PolicyDecision,
)
from app.knowledge.contracts import WriteReceipt
from app.knowledge.errors import KnowledgeWriteConflict
from app.knowledge.locators import make_note_locator
from app.knowledge.vault_identity import resolve_obsidian_vault_name
from app.knowledge.write_ops import read_create_once_winner_relative, write_note_relative
from app.knowledge.multiwriter import NoteClass
from app.receipts.promotion_receipts import (
    PromotionReceiptQuery,
    PromotionReceiptRow,
    query_promotion_receipts,
)
from app.receipts.outbox_sources import (
    ReceiptSourceSnapshot,
    read_receipt_source_snapshot,
    record_event,
    record_payload,
)
from app.services.outbox import (
    JsonlOutboxCorruptionError,
    append_jsonl_record,
    jsonl_outbox_append_lock,
    loads_json_without_duplicate_keys,
    read_jsonl_outbox_records,
)
from app.vault.manager import VaultContext
from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard

MEMORY_MATERIALIZATION_ACTION = "memory.materialize"
MEMORY_MATERIALIZATION_WRITE_CLASS = "semantic_memory_materialization"
MEMORY_MATERIALIZATION_SOURCE = "agent_memory.materialization"
MEMORY_MATERIALIZATION_STATE_OWNER = "HKA"
MEMORY_MATERIALIZATION_AUTHORITY_EVENT = "governance.authority_receipt.recorded"
DEFAULT_MEMORY_DIR = "Agent Memory"
DEFAULT_MATERIALIZATION_RECEIPTS_PATH = Path(
    "runtime/agent_memory/materialization_receipts.jsonl"
)
_MATERIALIZATION_SOURCE_MARKER_SUFFIX = ".materialization-source"
_LEGACY_MATERIALIZATION_SOURCE_MARKER_CONTRACT = (
    "materialization-source-continuity.v1"
)
_MATERIALIZATION_SOURCE_MARKER_CONTRACT = "materialization-source-continuity.v2"
_GOVERNED_WRITE_ADAPTER = GovernedWriteAdapter()


@dataclass(frozen=True)
class MemoryMaterializationResult:
    status: str
    artifact_path: str | None
    receipt_id: str | None
    terminal: bool


@dataclass(frozen=True)
class _GovernedMaterializationFacts:
    grant: GovernedWriteGrant
    mutation_receipt: WriteReceipt


@dataclass(frozen=True)
class _MaterializationSourceMarkerState:
    source_binding: str
    source_device: int
    source_inode: int
    committed_size: int
    committed_sha256: str
    target_reservations: dict[str, str]
    target_reservations_authoritative: bool


class MemoryMaterializationError(RuntimeError):
    """Raised when promoted memory cannot be materialized through governance."""


def materialize_promoted_memory(
    entry: ReviewEntry,
    *,
    vault_context: VaultContext,
    channel: str,
    decision_store: ReviewDecisionStore,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
    outbox_path: Path | None = None,
    memory_dir: str = DEFAULT_MEMORY_DIR,
) -> MemoryMaterializationResult:
    _require_promoted(entry)
    if entry.candidate.memory_type is not MemoryType.SEMANTIC_MEMORY:
        decision_store.mark_terminal(
            entry.candidate_id,
            vault_context=vault_context,
            channel=channel,
            expected_outcome=ReviewDecision.PROMOTE,
        )
        return MemoryMaterializationResult(
            status="not_semantic",
            artifact_path=None,
            receipt_id=None,
            terminal=True,
        )
    requested_scope_id = _require_scope_binding(entry)

    vault_root = _vault_root(vault_context)
    receipt_id = _stable_materialization_id(
        "receipt",
        entry=entry,
        vault_context=vault_context,
        channel=channel,
    )
    trace_id = _stable_materialization_id(
        "trace",
        entry=entry,
        vault_context=vault_context,
        channel=channel,
    )
    candidate_digest = review_candidate_digest(entry)
    artifact_path: str | None = None
    governed_facts: _GovernedMaterializationFacts | None = None
    try:
        with decision_store.promotion_materialization_transaction(
            entry.candidate_id,
            vault_context=vault_context,
            channel=channel,
            expected_scope_id=requested_scope_id,
            expected_candidate_digest=candidate_digest,
            initialize_first_attempt=lambda history: _initialize_materialization_receipt_source(
                outbox_path,
                required_history=_required_materialization_receipt_history(history),
                expected_source_binding=_materialization_source_binding_required(
                    history
                ),
            ),
            terminal_guard=lambda persisted: _materialization_terminal_guard(
                receipt_id=receipt_id,
                outbox_path=outbox_path,
                entry=entry,
                artifact_path=artifact_path,
                trace_id=trace_id,
                persisted=persisted,
                governed_facts=governed_facts,
            ),
        ) as persisted:
            _require_owned_materialization_receipt_source(
                outbox_path,
                expected_source_binding=persisted.materialization_source_binding,
            )
            persisted_scope_id = persisted.scope_id
            if persisted_scope_id is None:
                raise MemoryMaterializationError(
                    "persisted promote decision has no scope binding"
                )
            _preflight_materialization_receipt_identities(
                receipt_id,
                outbox_path=outbox_path,
                entry=entry,
                vault_id=persisted.vault_id,
                channel=persisted.channel,
            )
            recovered_receipt = _recover_applied_receipt(
                receipt_id,
                entry=entry,
                vault_root=vault_root,
                outbox_path=outbox_path,
                scope_id=persisted_scope_id,
                persisted=persisted,
                vault_id=_materialization_vault_identity(vault_context),
            )
            if recovered_receipt is not None:
                artifact_path = recovered_receipt.artifact_path
                if artifact_path is None:
                    raise MemoryMaterializationError(
                        "materialization receipt has no artifact path"
                    )
                governed_facts = _recover_governed_materialization_facts(
                    receipt_id,
                    outbox_path=outbox_path,
                    entry=entry,
                    persisted=persisted,
                    artifact_path=artifact_path,
                    trace_id=trace_id,
                )
                if governed_facts is None:
                    raise MemoryMaterializationError(
                        "applied memory receipt predates the governed write chain; "
                        "explicit remediation is required"
                    )
            else:
                reserved_target = _materialization_target_reservation(
                    outbox_path,
                    receipt_id=receipt_id,
                    expected_source_binding=persisted.materialization_source_binding,
                )
                if reserved_target is not None:
                    raise MemoryMaterializationError(
                        "reserved memory materialization target requires explicit remediation"
                    )
                recovered_note = _find_materialized_note(
                    vault_root=vault_root,
                    entry=entry,
                    scope_id=persisted_scope_id,
                    persisted=persisted,
                )
                if recovered_note is None:
                    artifact_uuid = _stable_materialization_id(
                        "artifact",
                        entry=entry,
                        vault_context=vault_context,
                        channel=channel,
                    )
                    artifact_path = _unique_memory_path(
                        vault_root=vault_root,
                        memory_dir=memory_dir,
                        title=entry.title,
                        candidate_id=entry.candidate_id,
                    )
                    with _materialization_mutation_guard(
                        receipt_id=receipt_id,
                        outbox_path=outbox_path,
                        entry=entry,
                        persisted=persisted,
                        artifact_path=artifact_path,
                    ) as locked_outbox_path:
                        grant = _materialization_grant(
                            receipt_id=receipt_id,
                            persisted=persisted,
                            artifact_path=artifact_path,
                        )
                        try:
                            write_guard.assert_writes_allowed(
                                MEMORY_MATERIALIZATION_ACTION
                            )
                            _reserve_materialization_target(
                                locked_outbox_path,
                                receipt_id=receipt_id,
                                artifact_path=artifact_path,
                                source_binding=persisted.materialization_source_binding,
                            )
                            observed_write_receipt = write_note_relative(
                                artifact_path,
                                _render_memory_note(
                                    entry,
                                    artifact_uuid=artifact_uuid,
                                    scope_id=persisted_scope_id,
                                    persisted=persisted,
                                ),
                                vault_root=vault_root,
                                action=MEMORY_MATERIALIZATION_ACTION,
                                write_guard=write_guard,
                                writer_identity=MEMORY_MATERIALIZATION_SOURCE,
                                create_once=True,
                            )
                            if observed_write_receipt.outcome == "already_exists":
                                raise MemoryMaterializationError(
                                    "memory materialization target was already occupied "
                                    "without a durable governed mutation receipt"
                                )
                            mutation_receipt = _materialization_mutation_receipt(
                                artifact_path=artifact_path,
                                trace_id=trace_id,
                                observed=observed_write_receipt,
                            )
                        except Exception as exc:
                            failed_receipt_id = _append_promotion_receipt(
                                locked_outbox_path,
                                entry=entry,
                                vault_context=vault_context,
                                channel=channel,
                                artifact_uuid=artifact_uuid,
                                artifact_path=artifact_path,
                                trace_id=trace_id,
                                scope_id=persisted_scope_id,
                                status="failed",
                                error=str(exc),
                                decided_by=persisted.decided_by,
                                _jsonl_lock_held=True,
                            )
                            raise MemoryMaterializationError(
                                f"memory materialization failed; receipt={failed_receipt_id}"
                            ) from exc

                        governed_facts = _GovernedMaterializationFacts(
                            grant=grant,
                            mutation_receipt=mutation_receipt,
                        )

                        _append_promotion_receipt(
                            locked_outbox_path,
                            entry=entry,
                            vault_context=vault_context,
                            channel=channel,
                            artifact_uuid=artifact_uuid,
                            artifact_path=artifact_path,
                            trace_id=trace_id,
                            scope_id=persisted_scope_id,
                            status="applied",
                            receipt_id=receipt_id,
                            decided_by=persisted.decided_by,
                            governed_facts=governed_facts,
                            _jsonl_lock_held=True,
                        )
                else:
                    raise MemoryMaterializationError(
                        "memory artifact has no durable governed mutation receipt; "
                        "explicit remediation is required"
                    )
                recovered_receipt = _recover_applied_receipt(
                    receipt_id,
                    entry=entry,
                    vault_root=vault_root,
                    outbox_path=outbox_path,
                    scope_id=persisted_scope_id,
                    persisted=persisted,
                    vault_id=_materialization_vault_identity(vault_context),
                )
                if recovered_receipt is None:
                    raise MemoryMaterializationError(
                        "materialization receipt was not queryable"
                    )
                persisted_facts = _recover_governed_materialization_facts(
                    receipt_id,
                    outbox_path=outbox_path,
                    entry=entry,
                    persisted=persisted,
                    artifact_path=artifact_path,
                    trace_id=trace_id,
                )
                if persisted_facts is None:
                    raise MemoryMaterializationError(
                        "applied memory receipt predates the governed write chain; "
                        "explicit remediation is required"
                    )
                governed_facts = persisted_facts

            if artifact_path is None or governed_facts is None:
                raise MemoryMaterializationError(
                    "materialization cannot terminalize without governed facts"
                )
            _ensure_materialization_authority_receipt(
                receipt_id,
                outbox_path=outbox_path,
                entry=entry,
                artifact_path=artifact_path,
                trace_id=trace_id,
                persisted=persisted,
                governed_facts=governed_facts,
            )
    except ReviewDecisionStoreError as exc:
        raise MemoryMaterializationError(str(exc)) from exc
    except MemoryMaterializationError:
        raise
    except Exception as exc:
        raise MemoryMaterializationError(
            "memory materialization interrupted; retry will reconcile durable effects"
        ) from exc

    return MemoryMaterializationResult(
        status="materialized",
        artifact_path=artifact_path,
        receipt_id=receipt_id,
        terminal=True,
    )


def _require_promoted(entry: ReviewEntry) -> None:
    if entry.status is not ReviewStatus.PROMOTED or entry.decision is not ReviewDecision.PROMOTE:
        raise MemoryMaterializationError("entry must carry a promote decision")


def _require_scope_binding(entry: ReviewEntry) -> str:
    scope_id = validated_memory_scope_id(entry.scope_id)
    if scope_id is None:
        raise MemoryMaterializationError(
            "semantic memory materialization requires a valid candidate.scope_id"
        )
    return scope_id


def _vault_root(context: VaultContext) -> Path:
    if not context.active_vault_path:
        raise MemoryMaterializationError("vault_context.active_vault_path is required")
    return Path(context.active_vault_path).expanduser().resolve()


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-").lower()
    return slug or "memory"


def _safe_rel_path(value: str) -> str:
    path = PurePosixPath(value)
    if value.startswith("/") or ".." in path.parts:
        raise MemoryMaterializationError("memory artifact path must stay vault-relative")
    return path.as_posix()


def _unique_memory_path(
    *,
    vault_root: Path,
    memory_dir: str,
    title: str,
    candidate_id: str,
) -> str:
    base = PurePosixPath(_safe_rel_path(memory_dir)) / f"{_slug(title)}-{candidate_id[:8]}.md"
    candidate = base
    counter = 2
    while (vault_root / candidate.as_posix()).exists():
        candidate = base.with_name(f"{base.stem}-{counter}{base.suffix}")
        counter += 1
    return candidate.as_posix()


def _stable_materialization_id(
    kind: str,
    *,
    entry: ReviewEntry,
    vault_context: VaultContext,
    channel: str,
) -> str:
    return _stable_materialization_id_from_fields(
        kind,
        vault_id=_materialization_vault_identity(vault_context),
        channel=channel,
        candidate_id=entry.candidate_id,
    )


def _stable_materialization_id_from_fields(
    kind: str,
    *,
    vault_id: str,
    channel: str,
    candidate_id: str,
) -> str:
    identity = (
        f"agent-memory-materialization:{kind}:"
        f"{vault_id}:{channel}:{candidate_id}"
    )
    return uuid5(NAMESPACE_URL, identity).hex


def _materialization_vault_identity(vault_context: VaultContext) -> str:
    if vault_context.active_vault_id:
        return vault_context.active_vault_id
    if not vault_context.active_vault_path:
        raise MemoryMaterializationError(
            "vault identity is required for stable materialization"
        )
    return f"path:{Path(vault_context.active_vault_path).expanduser().resolve()}"


def _fsync_materialization_file(path: Path) -> None:
    descriptor = os.open(
        path,
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0),
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_materialization_directory(path: Path) -> None:
    descriptor = os.open(
        path,
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0),
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _ensure_durable_materialization_directory(path: Path) -> None:
    """Create and durably link every missing receipt-directory component."""

    missing: list[Path] = []
    cursor = path
    while not cursor.exists():
        missing.append(cursor)
        if cursor.parent == cursor:
            raise OSError("materialization receipt directory has no existing parent")
        cursor = cursor.parent
    if not cursor.is_dir():
        raise NotADirectoryError(cursor)
    for directory in reversed(missing):
        try:
            directory.mkdir(mode=0o700)
        except FileExistsError:
            if not directory.is_dir():
                raise
        _fsync_materialization_directory(directory)
        _fsync_materialization_directory(directory.parent)
    # ``cursor`` can itself be a directory left behind by an interrupted prior
    # invocation: mkdir may have succeeded before syncing its parent failed.
    # Re-fence that existing anchor and its link on every retry before any
    # authority-bearing mutation is allowed to proceed.
    _fsync_materialization_directory(cursor)
    if cursor.parent != cursor:
        _fsync_materialization_directory(cursor.parent)


def _durably_touch_materialization_file(path: Path) -> None:
    """Create an empty owned file and fence both its data and directory link."""

    path.touch(exist_ok=False)
    _fsync_materialization_file(path)
    _fsync_materialization_directory(path.parent)


def _materialization_source_marker_path(source_path: Path) -> Path:
    return source_path.with_name(
        f".{source_path.name}{_MATERIALIZATION_SOURCE_MARKER_SUFFIX}"
    )


def _materialization_source_state(
    source_path: Path,
    *,
    committed_size: int | None = None,
) -> tuple[int, int, int, str]:
    """Hash one stable source prefix and return its filesystem identity."""

    descriptor = os.open(
        source_path,
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0),
    )
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise MemoryMaterializationError(
                "memory materialization receipt source is not a regular file"
            )
        size = before.st_size if committed_size is None else committed_size
        if type(size) is not int or size < 0 or before.st_size < size:
            raise MemoryMaterializationError(
                "materialization receipt source continuity is broken"
            )
        remaining = size
        digest = hashlib.sha256()
        while remaining:
            block = os.read(descriptor, min(remaining, 1024 * 1024))
            if not block:
                raise MemoryMaterializationError(
                    "materialization receipt source continuity is broken"
                )
            digest.update(block)
            remaining -= len(block)
        after = os.fstat(descriptor)
        if (
            after.st_dev != before.st_dev
            or after.st_ino != before.st_ino
            or after.st_size < size
        ):
            raise MemoryMaterializationError(
                "materialization receipt source continuity is broken"
            )
        return before.st_dev, before.st_ino, size, digest.hexdigest()
    finally:
        os.close(descriptor)


def _read_materialization_source_marker(marker_path: Path) -> dict[str, Any]:
    descriptor = os.open(
        marker_path,
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0),
    )
    try:
        marker_stat = os.fstat(descriptor)
        if not stat.S_ISREG(marker_stat.st_mode) or marker_stat.st_size > 64 * 1024:
            raise MemoryMaterializationError(
                "materialization receipt source continuity marker is invalid"
            )
        raw = b""
        while len(raw) <= 64 * 1024:
            block = os.read(descriptor, 8192)
            if not block:
                break
            raw += block
    finally:
        os.close(descriptor)
    try:
        payload = loads_json_without_duplicate_keys(raw)
    except (JsonlOutboxCorruptionError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise MemoryMaterializationError(
            "materialization receipt source continuity marker is invalid"
        ) from exc
    if not isinstance(payload, dict):
        raise MemoryMaterializationError(
            "materialization receipt source continuity marker is invalid"
        )
    return payload


def _validated_materialization_source_marker(
    source_path: Path,
    *,
    expected_source_binding: str | None = None,
) -> _MaterializationSourceMarkerState:
    marker_path = _materialization_source_marker_path(source_path)
    try:
        payload = _read_materialization_source_marker(marker_path)
        device = payload.get("source_device")
        inode = payload.get("source_inode")
        source_binding = payload.get("source_binding")
        committed_size = payload.get("committed_size")
        committed_sha256 = payload.get("committed_sha256")
        marker_contract = payload.get("contract")
        target_reservations_authoritative = "target_reservations" in payload
        raw_target_reservations = payload.get("target_reservations", {})
        if (
            marker_contract
            not in {
                _LEGACY_MATERIALIZATION_SOURCE_MARKER_CONTRACT,
                _MATERIALIZATION_SOURCE_MARKER_CONTRACT,
            }
            or (
                marker_contract == _MATERIALIZATION_SOURCE_MARKER_CONTRACT
                and not target_reservations_authoritative
            )
            or type(device) is not int
            or type(inode) is not int
            or not isinstance(source_binding, str)
            or not re.fullmatch(r"[0-9a-f]{32}", source_binding)
            or type(committed_size) is not int
            or committed_size < 0
            or not isinstance(committed_sha256, str)
            or not re.fullmatch(r"[0-9a-f]{64}", committed_sha256)
            or not isinstance(raw_target_reservations, dict)
            or len(raw_target_reservations) > 256
        ):
            raise MemoryMaterializationError(
                "materialization receipt source continuity marker is invalid"
            )
        target_reservations: dict[str, str] = {}
        for reservation_id, target_path in raw_target_reservations.items():
            if (
                not isinstance(reservation_id, str)
                or not re.fullmatch(r"[0-9a-f]{32}", reservation_id)
                or not isinstance(target_path, str)
                or len(target_path) > 4096
                or _safe_rel_path(target_path) != target_path
            ):
                raise MemoryMaterializationError(
                    "materialization receipt source continuity marker is invalid"
                )
            target_reservations[reservation_id] = target_path
        observed_device, observed_inode, _, observed_sha256 = (
            _materialization_source_state(
                source_path,
                committed_size=committed_size,
            )
        )
    except MemoryMaterializationError:
        raise
    except OSError as exc:
        raise MemoryMaterializationError(
            "materialization receipt source continuity is unavailable"
        ) from exc
    if (
        observed_device != device
        or observed_inode != inode
        or observed_sha256 != committed_sha256
    ):
        raise MemoryMaterializationError(
            "materialization receipt source continuity is broken"
        )
    if (
        expected_source_binding is not None
        and source_binding != expected_source_binding
    ):
        raise MemoryMaterializationError(
            "materialization receipt source binding changed"
        )
    return _MaterializationSourceMarkerState(
        source_binding=source_binding,
        source_device=device,
        source_inode=inode,
        committed_size=committed_size,
        committed_sha256=committed_sha256,
        target_reservations=target_reservations,
        target_reservations_authoritative=target_reservations_authoritative,
    )


def _validate_materialization_source_marker(
    source_path: Path,
    *,
    expected_source_binding: str | None = None,
) -> str:
    return _validated_materialization_source_marker(
        source_path,
        expected_source_binding=expected_source_binding,
    ).source_binding


def _write_materialization_source_marker(
    source_path: Path,
    *,
    source_binding: str | None = None,
    expected_source_state: tuple[int, int, int, str] | None = None,
    target_reservations: dict[str, str] | None = None,
    clear_target_reservation: str | None = None,
    allow_legacy_target_reservation_upgrade: bool = False,
) -> str:
    marker_path = _materialization_source_marker_path(source_path)
    prior_marker: _MaterializationSourceMarkerState | None = None
    if marker_path.exists() and marker_path.stat().st_size > 0:
        prior_marker = _validated_materialization_source_marker(
            source_path,
            expected_source_binding=source_binding,
        )
        if (
            not prior_marker.target_reservations_authoritative
            and not allow_legacy_target_reservation_upgrade
        ):
            raise MemoryMaterializationError(
                "legacy materialization target reservation evidence is unavailable; "
                "explicit remediation is required"
            )
        source_binding = prior_marker.source_binding
    elif source_binding is None:
        source_binding = uuid4().hex
    if not re.fullmatch(r"[0-9a-f]{32}", source_binding):
        raise MemoryMaterializationError(
            "materialization receipt source binding is invalid"
        )
    if target_reservations is None:
        target_reservations = (
            dict(prior_marker.target_reservations) if prior_marker is not None else {}
        )
    else:
        target_reservations = dict(target_reservations)
    if clear_target_reservation is not None:
        target_reservations.pop(clear_target_reservation, None)
    device, inode, committed_size, committed_sha256 = (
        _materialization_source_state(source_path)
    )
    observed_source_state = (device, inode, committed_size, committed_sha256)
    if (
        expected_source_state is not None
        and observed_source_state != expected_source_state
    ):
        raise MemoryMaterializationError(
            "materialization receipt source continuity is broken"
        )
    if prior_marker is not None and (
        device != prior_marker.source_device or inode != prior_marker.source_inode
    ):
        raise MemoryMaterializationError(
            "materialization receipt source continuity is broken"
        )
    payload = {
        "contract": _MATERIALIZATION_SOURCE_MARKER_CONTRACT,
        "source_device": device,
        "source_inode": inode,
        "source_binding": source_binding,
        "committed_size": committed_size,
        "committed_sha256": committed_sha256,
        "target_reservations": target_reservations,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    temporary = marker_path.with_name(f".{marker_path.name}.{uuid4().hex}.tmp")
    descriptor: int | None = None
    try:
        descriptor = os.open(
            temporary,
            os.O_CREAT
            | os.O_EXCL
            | os.O_WRONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            0o600,
        )
        offset = 0
        while offset < len(raw):
            offset += os.write(descriptor, raw[offset:])
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        os.replace(temporary, marker_path)
        _fsync_materialization_file(marker_path)
        _fsync_materialization_directory(marker_path.parent)
        validated = _validated_materialization_source_marker(
            source_path,
            expected_source_binding=source_binding,
        )
        if (
            validated.source_device != device
            or validated.source_inode != inode
            or validated.committed_size != committed_size
            or validated.committed_sha256 != committed_sha256
            or validated.target_reservations != target_reservations
            or not validated.target_reservations_authoritative
        ):
            raise MemoryMaterializationError(
                "materialization receipt source continuity is broken"
            )
    finally:
        if descriptor is not None:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)
    return source_binding


def _materialization_target_reservation(
    outbox_path: Path | None,
    *,
    receipt_id: str,
    expected_source_binding: str | None,
) -> str | None:
    """Read an exact pre-HKA target reservation under the receipt-source lock."""

    path = _materialization_receipt_path(outbox_path)
    with jsonl_outbox_append_lock(path) as canonical_path:
        marker = _validated_materialization_source_marker(
            canonical_path,
            expected_source_binding=expected_source_binding,
        )
        if not marker.target_reservations_authoritative:
            raise MemoryMaterializationError(
                "legacy materialization target reservation evidence is unavailable; "
                "explicit remediation is required"
            )
        return marker.target_reservations.get(receipt_id)


def _reserve_materialization_target(
    source_path: Path,
    *,
    receipt_id: str,
    artifact_path: str,
    source_binding: str | None,
) -> None:
    """Durably bind one exact target before any authority-bearing HKA call."""

    marker = _validated_materialization_source_marker(
        source_path,
        expected_source_binding=source_binding,
    )
    if not marker.target_reservations_authoritative:
        raise MemoryMaterializationError(
            "legacy materialization target reservation evidence is unavailable; "
            "explicit remediation is required"
        )
    if receipt_id in marker.target_reservations:
        raise MemoryMaterializationError(
            "reserved memory materialization target requires explicit remediation"
        )
    reservations = dict(marker.target_reservations)
    reservations[receipt_id] = _safe_rel_path(artifact_path)
    _write_materialization_source_marker(
        source_path,
        source_binding=source_binding,
        target_reservations=reservations,
    )


def _source_contains_materialization_history(
    source_path: Path,
    *,
    required_history: tuple[ReviewDecisionRecord, ...],
) -> bool:
    try:
        records = tuple(
            read_jsonl_outbox_records(source_path, _lock_held=True)
        )
    except (JsonlOutboxCorruptionError, OSError, ValueError):
        return False
    return bool(required_history) and all(
        _owned_jsonl_contains_complete_materialization_chain(
            records,
            decision=decision,
        )
        for decision in required_history
    )


def _materialization_receipt_path(outbox_path: Path | None) -> Path:
    """Return the one canonical filesystem identity for the owned receipt source."""

    path = outbox_path or DEFAULT_MATERIALIZATION_RECEIPTS_PATH
    return path.expanduser().resolve(strict=False)


def _initialize_materialization_receipt_source(
    outbox_path: Path | None,
    *,
    required_history: tuple[ReviewDecisionRecord, ...] = (),
    expected_source_binding: str | None = None,
) -> str:
    """Create the owned JSONL sink before the first authority-bearing attempt."""
    path = _materialization_receipt_path(outbox_path)
    try:
        _ensure_durable_materialization_directory(path.parent)
        with jsonl_outbox_append_lock(path) as canonical_path:
            marker = _materialization_source_marker_path(canonical_path)
            if canonical_path.exists():
                if not canonical_path.is_file():
                    raise MemoryMaterializationError(
                        "memory materialization receipt source is not a file"
                    )
                _fsync_materialization_file(canonical_path)
                _fsync_materialization_directory(canonical_path.parent)
                if marker.exists() and marker.stat().st_size > 0:
                    marker_state = _validated_materialization_source_marker(
                        canonical_path,
                        expected_source_binding=expected_source_binding,
                    )
                    binding = marker_state.source_binding
                    if (
                        required_history
                        and (
                            expected_source_binding is None
                            or not marker_state.target_reservations_authoritative
                        )
                        and not _source_contains_materialization_history(
                            canonical_path,
                            required_history=required_history,
                        )
                    ):
                        raise MemoryMaterializationError(
                            "historical materialization receipt source continuity "
                            "is unavailable; explicit remediation is required"
                        )
                    if not marker_state.target_reservations_authoritative:
                        if expected_source_binding is not None and not required_history:
                            raise MemoryMaterializationError(
                                "legacy materialization target reservation evidence is "
                                "unavailable; explicit remediation is required"
                            )
                        return _write_materialization_source_marker(
                            canonical_path,
                            source_binding=binding,
                            allow_legacy_target_reservation_upgrade=True,
                        )
                    return binding
                else:
                    if expected_source_binding is not None:
                        raise MemoryMaterializationError(
                            "persisted materialization receipt source continuity marker "
                            "is unavailable"
                        )
                    if required_history and not (
                        canonical_path.stat().st_size > 0
                        and _source_contains_materialization_history(
                            canonical_path,
                            required_history=required_history,
                        )
                    ):
                        raise MemoryMaterializationError(
                            "historical materialization receipt source continuity "
                            "is unavailable; explicit remediation is required"
                        )
                    return _write_materialization_source_marker(
                        canonical_path,
                        source_binding=expected_source_binding,
                    )
            if marker.exists():
                raise MemoryMaterializationError(
                    "shared materialization receipt history is unavailable"
                )
            if required_history:
                raise MemoryMaterializationError(
                    "historical materialization receipt source is unavailable; "
                    "explicit remediation is required"
                )
            _durably_touch_materialization_file(canonical_path)
            return _write_materialization_source_marker(
                canonical_path,
                source_binding=expected_source_binding,
            )
    except MemoryMaterializationError:
        raise
    except OSError as exc:
        raise MemoryMaterializationError(
            "memory materialization receipt source could not be initialized"
        ) from exc


def _required_materialization_receipt_history(
    decisions: tuple[ReviewDecisionRecord, ...],
) -> tuple[ReviewDecisionRecord, ...]:
    """Return decisions whose exact receipts must survive pre-marker migration."""

    return tuple(
        record
        for record in decisions
        if record.outcome is ReviewDecision.PROMOTE
        and (
            record.materializing
            or (
                record.terminal
                and record.memory_type
                in {None, MemoryType.SEMANTIC_MEMORY}
            )
        )
    )


def _materialization_source_binding_required(
    decisions: tuple[ReviewDecisionRecord, ...],
) -> str | None:
    bindings = {
        record.materialization_source_binding
        for record in decisions
        if record.materialization_source_binding is not None
        and record.outcome is ReviewDecision.PROMOTE
    }
    if len(bindings) > 1:
        raise MemoryMaterializationError(
            "persisted materialization receipt source bindings conflict"
        )
    return next(iter(bindings), None)


def _require_owned_materialization_receipt_source(
    outbox_path: Path | None,
    *,
    expected_source_binding: str | None = None,
    _jsonl_lock_held: bool = False,
) -> None:
    """Require the JSONL history owned by an already-started materialization."""
    path = _materialization_receipt_path(outbox_path)
    try:
        if not path.exists() or not path.is_file():
            raise MemoryMaterializationError(
                "owned materialization receipt source is unavailable during reconciliation"
            )
        if expected_source_binding is None:
            raise MemoryMaterializationError(
                "persisted materialization receipt source binding is unavailable"
            )
        _validate_materialization_source_marker(
            path,
            expected_source_binding=expected_source_binding,
        )
        snapshot = read_receipt_source_snapshot(
            outbox_path=path,
            _jsonl_lock_held=_jsonl_lock_held,
        )
    except MemoryMaterializationError:
        raise
    except Exception as exc:
        raise MemoryMaterializationError(
            "owned materialization receipt source is unavailable during reconciliation"
        ) from exc
    if "JSONL" in snapshot.unavailable_sources:
        raise MemoryMaterializationError(
            "owned materialization receipt source is unavailable during reconciliation"
        )


def _materialization_source_event(candidate_id: str) -> str:
    return f"memory-promote:{candidate_id}"


def _promotion_record_failed(record: dict[str, Any]) -> bool:
    outcome = record_payload(record).get("outcome")
    return isinstance(outcome, dict) and outcome.get("status") == "failed"


def _linked_promotion_record(
    record: dict[str, Any],
    receipt_id: str,
    *,
    candidate_id: str,
    vault_id: str,
    channel: str,
    decision_id: str | None = None,
    token_id: str | None = None,
) -> bool:
    payload = record_payload(record)
    if (
        record.get("event_id") == receipt_id
        or payload.get("receipt_id") == receipt_id
    ):
        return True
    policy = payload.get("policy_decision")
    token = payload.get("decision_token")
    governed_linked = (
        decision_id is not None
        and (
            isinstance(policy, dict)
            and policy.get("decision_id") == decision_id
            or isinstance(token, dict)
            and token.get("decision_id") == decision_id
        )
    ) or (
        token_id is not None
        and isinstance(token, dict)
        and token.get("token_id") == token_id
    )
    if governed_linked:
        return True
    if record_event(record) != PROMOTION_TRANSITION_APPLIED:
        return False
    # Failed attempts intentionally share the candidate source and trace with a
    # later retry; only their random attempt receipt identifies them. Exact GOV
    # identities are handled above because they must never be hidden by an
    # outer event or outcome classification.
    if _promotion_record_failed(record):
        return False
    basis = payload.get("basis")
    source_event = _materialization_source_event(candidate_id)
    return (
        payload.get("vault_id") == vault_id
        and payload.get("channel") == channel
        and (
            payload.get("intent_event_id") == source_event
            or payload.get("source_event") == source_event
            or (
                isinstance(basis, dict)
                and basis.get("source_event") == source_event
            )
        )
    )


def _linked_authority_record(
    record: dict[str, Any],
    receipt_id: str,
    *,
    authority_receipt_id: str | None = None,
    decision_id: str | None = None,
    token_id: str | None = None,
) -> bool:
    payload = record_payload(record)
    raw_authority = payload.get("authority_receipt")
    return (
        record.get("event_id") == _materialization_authority_event_id(receipt_id)
        or payload.get("materialization_id") == receipt_id
        or payload.get("promotion_receipt_id") == receipt_id
        or (
            isinstance(raw_authority, dict)
            and raw_authority.get("effect_id") == receipt_id
        )
        or (
            authority_receipt_id is not None
            and isinstance(raw_authority, dict)
            and raw_authority.get("receipt_id") == authority_receipt_id
        )
        or (
            decision_id is not None
            and isinstance(raw_authority, dict)
            and raw_authority.get("decision_id") == decision_id
        )
        or (
            token_id is not None
            and isinstance(raw_authority, dict)
            and raw_authority.get("decision_token_id") == token_id
        )
    )


def _preflight_materialization_receipt_identities(
    receipt_id: str,
    *,
    outbox_path: Path | None,
    entry: ReviewEntry,
    vault_id: str,
    channel: str,
    _jsonl_lock_held: bool = False,
    require_unoccupied: bool = False,
    persisted: ReviewDecisionRecord | None = None,
    artifact_path: str | None = None,
) -> None:
    """Reject conflicting deterministic receipt identities before HKA can mutate."""
    snapshot = read_receipt_source_snapshot(
        outbox_path=_materialization_receipt_path(outbox_path),
        _jsonl_lock_held=_jsonl_lock_held,
    )
    if snapshot.unavailable_sources:
        raise MemoryMaterializationError(
            "configured receipt source is unavailable during pre-mutation reconciliation"
        )
    authority_event_id = _materialization_authority_event_id(receipt_id)
    governed_ids = (
        _materialization_governed_ids(
            receipt_id=receipt_id,
            persisted=persisted,
            artifact_path=artifact_path,
        )
        if persisted is not None and artifact_path is not None
        else (None, None)
    )
    decision_id, token_id = governed_ids
    promotion_records = [
        record
        for record in snapshot.records
        if _linked_promotion_record(
            record,
            receipt_id,
            candidate_id=entry.candidate_id,
            vault_id=vault_id,
            channel=channel,
            decision_id=decision_id,
            token_id=token_id,
        )
    ]
    authority_records = [
        record
        for record in snapshot.records
        if _linked_authority_record(
            record,
            receipt_id,
            authority_receipt_id=_materialization_authority_receipt_id(receipt_id),
            decision_id=decision_id,
            token_id=token_id,
        )
    ]
    _require_canonical_receipt_records(promotion_records)
    _require_canonical_receipt_records(authority_records)
    if any(
        record.get("event_id") != receipt_id
        or record_event(record) != PROMOTION_TRANSITION_APPLIED
        for record in promotion_records
    ):
        raise MemoryMaterializationError(
            "conflicting event shares the memory promotion receipt identity"
        )
    if any(
        record.get("event_id") != authority_event_id
        or record_event(record) != MEMORY_MATERIALIZATION_AUTHORITY_EVENT
        for record in authority_records
    ):
        raise MemoryMaterializationError(
            "memory AuthorityReceipt event is invalid; conflicting event occupies identity"
        )
    if require_unoccupied and (promotion_records or authority_records):
        raise MemoryMaterializationError(
            "materialization receipt identity changed during pre-mutation reconciliation"
        )
    if authority_records:
        if not promotion_records or any(
            not _receipt_records_match(record, promotion_records[0])
            for record in promotion_records[1:]
        ) or any(
            not _receipt_records_match(record, authority_records[0])
            for record in authority_records[1:]
        ):
            raise MemoryMaterializationError(
                "conflicting event occupies the memory AuthorityReceipt identity"
            )
        payload = record_payload(authority_records[0])
        if (
            not isinstance(payload.get("authority_receipt"), dict)
            or payload.get("materialization_id") != receipt_id
            or payload.get("promotion_receipt_id") != receipt_id
            or payload.get("candidate_id") != entry.candidate_id
        ):
            raise MemoryMaterializationError(
                "conflicting event occupies the memory AuthorityReceipt identity"
            )


@contextmanager
def _materialization_mutation_guard(
    *,
    receipt_id: str,
    outbox_path: Path | None,
    entry: ReviewEntry,
    persisted: ReviewDecisionRecord,
    artifact_path: str,
) -> Iterator[Path]:
    """Fence receipt-source continuity from the last preflight through HKA append."""

    path = _materialization_receipt_path(outbox_path)
    with jsonl_outbox_append_lock(path) as canonical_path:
        _require_owned_materialization_receipt_source(
            canonical_path,
            expected_source_binding=persisted.materialization_source_binding,
            _jsonl_lock_held=True,
        )
        _preflight_materialization_receipt_identities(
            receipt_id,
            outbox_path=canonical_path,
            entry=entry,
            vault_id=persisted.vault_id,
            channel=persisted.channel,
            _jsonl_lock_held=True,
            require_unoccupied=True,
            persisted=persisted,
            artifact_path=artifact_path,
        )
        yield canonical_path


def _materialization_governed_ids(
    *,
    receipt_id: str,
    persisted: ReviewDecisionRecord,
    artifact_path: str,
) -> tuple[str, str]:
    identity = (
        f"{receipt_id}\x00{persisted.decided_by}\x00"
        f"{_iso(persisted.decided_at)}\x00{artifact_path}"
    ).encode("utf-8")
    decision_digest = hashlib.sha256(b"policy\x00" + identity).hexdigest()
    token_digest = hashlib.sha256(b"token\x00" + identity).hexdigest()
    return f"policy_decision_{decision_digest}", f"decision_token_{token_digest}"


def _materialization_grant(
    *,
    receipt_id: str,
    persisted: ReviewDecisionRecord,
    artifact_path: str,
) -> GovernedWriteGrant:
    """Issue the replay-stable GOV grant derived from one persisted review."""
    issued = _GOVERNED_WRITE_ADAPTER.issue_human_decision_token(
        action=MEMORY_MATERIALIZATION_ACTION,
        write_class=MEMORY_MATERIALIZATION_WRITE_CLASS,
        actor=persisted.decided_by,
        resource=artifact_path,
    )
    decision_id, token_id = _materialization_governed_ids(
        receipt_id=receipt_id,
        persisted=persisted,
        artifact_path=artifact_path,
    )
    decision = replace(
        issued.policy_decision,
        decision_id=decision_id,
    )
    token = replace(
        issued.decision_token,
        token_id=token_id,
        decision_id=decision_id,
    )
    validated = _GOVERNED_WRITE_ADAPTER.validate_decision_token(
        decision_token=token,
        action=MEMORY_MATERIALIZATION_ACTION,
        write_class=MEMORY_MATERIALIZATION_WRITE_CLASS,
        actor=persisted.decided_by,
        resource=artifact_path,
    )
    if (
        decision.resource != artifact_path
        or token.resource != artifact_path
        or validated.resource != artifact_path
    ):
        raise MemoryMaterializationError(
            "GOV authorization does not preserve the exact HKA target"
        )
    return GovernedWriteGrant(policy_decision=decision, decision_token=validated)


def _materialization_mutation_receipt(
    *,
    artifact_path: str,
    trace_id: str,
    observed: WriteReceipt,
) -> WriteReceipt:
    if (
        observed.operation != "write_note"
        or observed.locator.vault != resolve_obsidian_vault_name()
        or observed.locator.path != artifact_path
        or observed.adapter != "fs_vault"
        or observed.note_class != NoteClass.CREATE_ONCE
        or observed.writer_identity != MEMORY_MATERIALIZATION_SOURCE
        or observed.outcome != "written"
        or observed.fallback_used
        or observed.conflict_artifact is not None
    ):
        raise MemoryMaterializationError(
            "HKA mutation receipt does not match memory materialization"
        )
    return replace(observed, trace_id=trace_id)


def _parse_policy_decision(value: object) -> PolicyDecision:
    if not isinstance(value, dict):
        raise MemoryMaterializationError(
            "materialization receipt omitted its GOV PolicyDecision"
        )
    required_fields = {
        "decision_id",
        "status",
        "action",
        "write_class",
        "actor",
        "resource",
        "reason",
        "issued_at",
        "source",
        "contract_version",
    }
    if not required_fields.issubset(value):
        raise MemoryMaterializationError(
            "persisted GOV authorization is missing PolicyDecision fields"
        )
    try:
        return PolicyDecision(**value)
    except (TypeError, ValueError) as exc:
        raise MemoryMaterializationError(
            "materialization receipt contains an invalid GOV PolicyDecision"
        ) from exc


def _parse_decision_token(value: object) -> DecisionToken:
    if not isinstance(value, dict):
        raise MemoryMaterializationError(
            "materialization receipt omitted its GOV DecisionToken"
        )
    required_fields = {
        "token_id",
        "decision_id",
        "action",
        "write_class",
        "actor",
        "resource",
        "issued_at",
        "valid",
        "contract_version",
    }
    if not required_fields.issubset(value):
        raise MemoryMaterializationError(
            "persisted GOV authorization is missing DecisionToken fields"
        )
    try:
        return DecisionToken(**value)
    except (TypeError, ValueError) as exc:
        raise MemoryMaterializationError(
            "materialization receipt contains an invalid GOV DecisionToken"
        ) from exc


def _parse_write_receipt(
    value: object,
    *,
    expected_artifact_path: str,
) -> WriteReceipt:
    if not isinstance(value, dict) or not isinstance(value.get("locator"), dict):
        raise MemoryMaterializationError(
            "materialization receipt omitted its HKA mutation receipt"
        )
    required_fields = {
        "operation",
        "locator",
        "adapter",
        "trace_id",
        "fallback_used",
        "note_class",
        "writer_identity",
        "written_at",
        "outcome",
        "conflict_artifact",
    }
    locator = value["locator"]
    if (
        not required_fields.issubset(value)
        or not {"vault", "path"}.issubset(locator)
        or locator.get("vault") != resolve_obsidian_vault_name()
        or not _is_nonempty_string(locator.get("path"))
        or locator.get("path") != expected_artifact_path
        or not _is_nonempty_string(value.get("trace_id"))
        or value.get("fallback_used") is not False
        or not _is_nonempty_string(value.get("written_at"))
        or value.get("conflict_artifact") is not None
    ):
        raise MemoryMaterializationError(
            "persisted HKA mutation receipt is incomplete or malformed"
        )
    raw = dict(value)
    try:
        raw["locator"] = make_note_locator(
            raw["locator"]["path"], vault=raw["locator"]["vault"]
        )
        return WriteReceipt(**raw)
    except (TypeError, ValueError) as exc:
        raise MemoryMaterializationError(
            "materialization receipt contains an invalid HKA mutation receipt"
        ) from exc


def _is_nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_iso_timestamp(value: object) -> bool:
    return _parse_iso_timestamp(value) is not None


def _parse_iso_timestamp(value: object) -> datetime | None:
    if not _is_nonempty_string(value):
        return None
    assert isinstance(value, str)
    raw = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _typed_evidence_matches(observed: object, expected: object) -> bool:
    if type(observed) is not type(expected):
        return False
    if isinstance(expected, dict):
        assert isinstance(observed, dict)
        return observed.keys() == expected.keys() and all(
            _typed_evidence_matches(observed[key], value)
            for key, value in expected.items()
        )
    if isinstance(expected, list):
        assert isinstance(observed, list)
        return len(observed) == len(expected) and all(
            _typed_evidence_matches(observed_value, expected_value)
            for observed_value, expected_value in zip(observed, expected, strict=True)
        )
    return observed == expected


def _canonical_receipt_record(record: dict[str, Any]) -> dict[str, Any] | None:
    """Remove only consistent transport projection fields from receipt evidence."""

    canonical = dict(record)
    event = canonical.get("event")
    if not isinstance(event, str) or not event.strip():
        return None
    for alias in ("event_type", "topic"):
        if alias not in canonical:
            continue
        alias_value = canonical.pop(alias)
        if type(alias_value) is not type(event) or alias_value != event:
            return None
    # ``created_at`` belongs to the DB row, not the authority-bearing event
    # envelope. The canonical event timestamp remains exact-typed and compared.
    canonical.pop("created_at", None)
    return canonical


def _require_canonical_receipt_records(records: list[dict[str, Any]]) -> None:
    if any(_canonical_receipt_record(record) is None for record in records):
        raise MemoryMaterializationError("receipt envelope is invalid")


def _receipt_records_match(
    observed: dict[str, Any], expected: dict[str, Any]
) -> bool:
    """Compare canonical receipt envelopes with recursive exact-type equality."""

    observed_canonical = _canonical_receipt_record(observed)
    expected_canonical = _canonical_receipt_record(expected)
    return (
        observed_canonical is not None
        and expected_canonical is not None
        and _typed_evidence_matches(observed_canonical, expected_canonical)
    )


def _governed_materialization_facts_from_payload(
    payload: dict[str, Any],
    *,
    receipt_id: str,
    persisted: ReviewDecisionRecord,
    artifact_path: str,
    trace_id: str,
) -> _GovernedMaterializationFacts | None:
    governed_values = (
        payload.get("policy_decision"),
        payload.get("decision_token"),
        payload.get("state_owner_receipt"),
    )
    if governed_values == (None, None, None):
        return None
    policy = _parse_policy_decision(governed_values[0])
    token = _parse_decision_token(governed_values[1])
    mutation_receipt = _parse_write_receipt(
        governed_values[2],
        expected_artifact_path=artifact_path,
    )
    policy_strings = (
        policy.decision_id,
        policy.status,
        policy.action,
        policy.write_class,
        policy.actor,
        policy.resource,
        policy.reason,
        policy.issued_at,
        policy.source,
        policy.contract_version,
    )
    token_strings = (
        token.token_id,
        token.decision_id,
        token.action,
        token.write_class,
        token.actor,
        token.resource,
        token.issued_at,
        token.contract_version,
    )
    policy_issued_at = _parse_iso_timestamp(policy.issued_at)
    mutation_written_at = _parse_iso_timestamp(mutation_receipt.written_at)
    expected_decision_id, expected_token_id = _materialization_governed_ids(
        receipt_id=receipt_id,
        persisted=persisted,
        artifact_path=artifact_path,
    )
    if (
        not all(_is_nonempty_string(value) for value in policy_strings)
        or not all(_is_nonempty_string(value) for value in token_strings)
        or token.valid is not True
        or policy.status != "approved"
        or policy.source != "human_review"
        or policy.reason
        != "Explicit human reviewer decision authorized by GOV."
        or policy.contract_version != GOVERNED_WRITE_CONTRACT_VERSION
        or policy.decision_id != expected_decision_id
        or token.token_id != expected_token_id
        or policy.decision_id != token.decision_id
        or policy.issued_at != token.issued_at
        or policy.actor != persisted.decided_by
        or policy.action != MEMORY_MATERIALIZATION_ACTION
        or policy.write_class != MEMORY_MATERIALIZATION_WRITE_CLASS
        or policy.resource != artifact_path
        or token.resource != artifact_path
        or policy_issued_at is None
        or policy_issued_at
        < persisted.decided_at.astimezone(timezone.utc).replace(microsecond=0)
        or token.contract_version != GOVERNED_WRITE_CONTRACT_VERSION
        or mutation_receipt.trace_id != trace_id
        or mutation_written_at is None
        or mutation_written_at < policy_issued_at
    ):
        raise MemoryMaterializationError(
            "persisted GOV authorization does not match memory materialization"
        )
    try:
        validated_token = _GOVERNED_WRITE_ADAPTER.validate_decision_token(
            decision_token=token,
            action=MEMORY_MATERIALIZATION_ACTION,
            write_class=MEMORY_MATERIALIZATION_WRITE_CLASS,
            actor=persisted.decided_by,
            resource=artifact_path,
        )
    except Exception as exc:
        raise MemoryMaterializationError(
            f"GOV refused memory materialization reconciliation: {exc}"
        ) from exc
    try:
        validated_mutation = _materialization_mutation_receipt(
            artifact_path=artifact_path,
            trace_id=trace_id,
            observed=mutation_receipt,
        )
    except MemoryMaterializationError as exc:
        raise MemoryMaterializationError(
            "persisted HKA mutation receipt does not match memory materialization"
        ) from exc
    return _GovernedMaterializationFacts(
        grant=GovernedWriteGrant(
            policy_decision=policy,
            decision_token=validated_token,
        ),
        mutation_receipt=validated_mutation,
    )


def _validated_promotion_recorded_at(
    record: dict[str, Any],
    governed_facts: _GovernedMaterializationFacts,
) -> str:
    """Bind promotion evidence after HKA mutation for every reconciliation path."""

    raw_promotion_at = record.get("timestamp")
    promotion_at = _parse_iso_timestamp(raw_promotion_at)
    mutation_at = _parse_iso_timestamp(
        governed_facts.mutation_receipt.written_at
    )
    if (
        not isinstance(raw_promotion_at, str)
        or promotion_at is None
        or mutation_at is None
        or promotion_at < mutation_at
    ):
        raise MemoryMaterializationError(
            "persisted promotion evidence conflicts with governed mutation chronology"
        )
    return raw_promotion_at


def _promotion_recorded_at_from_snapshot(
    snapshot: ReceiptSourceSnapshot,
    *,
    receipt_id: str,
    governed_facts: _GovernedMaterializationFacts,
) -> str:
    matching = [
        record
        for record in snapshot.records
        if record.get("event_id") == receipt_id
        and record_event(record) == PROMOTION_TRANSITION_APPLIED
    ]
    if not matching:
        raise MemoryMaterializationError(
            "complete governed materialization receipt chain was not queryable"
        )
    _require_canonical_receipt_records(matching)
    if any(
        not _receipt_records_match(record, matching[0])
        for record in matching[1:]
    ):
        raise MemoryMaterializationError("conflicting memory promotion receipts")
    return _validated_promotion_recorded_at(matching[0], governed_facts)


def _recover_governed_materialization_facts(
    receipt_id: str,
    *,
    outbox_path: Path | None,
    entry: ReviewEntry,
    persisted: ReviewDecisionRecord,
    artifact_path: str,
    trace_id: str,
    snapshot: ReceiptSourceSnapshot | None = None,
) -> _GovernedMaterializationFacts | None:
    if snapshot is None:
        snapshot = read_receipt_source_snapshot(
            outbox_path=_materialization_receipt_path(outbox_path)
        )
    decision_id, token_id = _materialization_governed_ids(
        receipt_id=receipt_id,
        persisted=persisted,
        artifact_path=artifact_path,
    )
    matching = [
        record
        for record in snapshot.records
        if _linked_promotion_record(
            record,
            receipt_id,
            candidate_id=entry.candidate_id,
            vault_id=persisted.vault_id,
            channel=persisted.channel,
            decision_id=decision_id,
            token_id=token_id,
        )
    ]
    _require_canonical_receipt_records(matching)
    if any(
        record.get("event_id") != receipt_id
        or record_event(record) != PROMOTION_TRANSITION_APPLIED
        for record in matching
    ):
        raise MemoryMaterializationError(
            "conflicting event shares the memory promotion receipt identity"
        )
    if not matching:
        if snapshot.unavailable_sources:
            raise MemoryMaterializationError(
                "configured receipt source is unavailable during memory reconciliation"
            )
        return None
    if any(
        not _receipt_records_match(record, matching[0])
        for record in matching[1:]
    ):
        raise MemoryMaterializationError(
            "conflicting memory promotion receipts share one identity"
        )
    payload = record_payload(matching[0])
    artifact_uuid = payload.get("artifact_uuid")
    source_event = f"memory-promote:{entry.candidate_id}"
    expected_authority = {
        "mode": "governed_execution",
        "component": MEMORY_MATERIALIZATION_SOURCE,
        "executor": MEMORY_MATERIALIZATION_SOURCE,
        "requested_by": persisted.decided_by,
    }
    expected_basis = {
        "source_event": source_event,
        "intent_type": "agent_memory_materialization",
        "candidate_id": entry.candidate_id,
        "scope_id": persisted.scope_id,
        "inferred": entry.inferred,
        "source_refs": list(entry.source_refs),
    }
    expected_outcome = {
        "status": "applied",
        "review_state": "accepted",
        "maturity": "semantic_memory",
    }
    expected_linkage = {
        "artifact_uuid": artifact_uuid,
        "artifact_path": artifact_path,
        "candidate_id": entry.candidate_id,
    }
    if (
        not _is_nonempty_string(artifact_uuid)
        or payload.get("receipt_id") != receipt_id
        or payload.get("intent_event_id") != source_event
        or payload.get("source_event") != source_event
        or payload.get("trace_id") != trace_id
        or payload.get("vault_id") != persisted.vault_id
        or payload.get("channel") != persisted.channel
        or payload.get("artifact_path") != artifact_path
        or payload.get("transition_family") != "agent_memory_materialization"
        or payload.get("target_maturity") != "semantic_memory"
        or payload.get("executor") != MEMORY_MATERIALIZATION_SOURCE
        or not _typed_evidence_matches(payload.get("authority"), expected_authority)
        or not _typed_evidence_matches(payload.get("basis"), expected_basis)
        or not _typed_evidence_matches(payload.get("outcome"), expected_outcome)
        or not _typed_evidence_matches(
            payload.get("artifact_linkage"), expected_linkage
        )
        or any(
            record.get("trace_id") != trace_id
            or record.get("source") != MEMORY_MATERIALIZATION_SOURCE
            or not _is_iso_timestamp(record.get("timestamp"))
            for record in matching
        )
    ):
        raise MemoryMaterializationError(
            "persisted promotion evidence conflicts with review authority"
        )
    governed_facts = _governed_materialization_facts_from_payload(
        payload,
        receipt_id=receipt_id,
        persisted=persisted,
        artifact_path=artifact_path,
        trace_id=trace_id,
    )
    if governed_facts is None:
        return None
    _validated_promotion_recorded_at(matching[0], governed_facts)
    return governed_facts


def _materialization_authority_receipt(
    *,
    receipt_id: str,
    artifact_path: str,
    trace_id: str,
    governed_facts: _GovernedMaterializationFacts,
) -> AuthorityReceipt:
    authority = _GOVERNED_WRITE_ADAPTER.record_authority_receipt(
        decision_token=governed_facts.grant.decision_token,
        mutation_receipt=cast(Any, governed_facts.mutation_receipt),
        state_owner=MEMORY_MATERIALIZATION_STATE_OWNER,
        resource=artifact_path,
        trace_id=trace_id,
        effect_id=receipt_id,
    )
    return replace(
        authority,
        receipt_id=_materialization_authority_receipt_id(receipt_id),
        recorded_at=cast(str, _iso(datetime.now(timezone.utc))),
    )


def _materialization_authority_receipt_id(receipt_id: str) -> str:
    stable_id = hashlib.sha256(
        f"{MEMORY_MATERIALIZATION_AUTHORITY_EVENT}\x00{receipt_id}".encode("utf-8")
    ).hexdigest()
    return f"authority_receipt_{stable_id}"


def _materialization_authority_event_id(receipt_id: str) -> str:
    return hashlib.sha256(
        f"{receipt_id}\x00{MEMORY_MATERIALIZATION_AUTHORITY_EVENT}".encode("utf-8")
    ).hexdigest()


def _append_materialization_authority_receipt(
    outbox_path: Path | None,
    *,
    receipt_id: str,
    entry: ReviewEntry,
    trace_id: str,
    authority_receipt: AuthorityReceipt,
) -> None:
    record = {
        "event": MEMORY_MATERIALIZATION_AUTHORITY_EVENT,
        "event_id": _materialization_authority_event_id(receipt_id),
        "trace_id": trace_id,
        "source": MEMORY_MATERIALIZATION_SOURCE,
        "timestamp": authority_receipt.recorded_at,
        "payload": {
            "materialization_id": receipt_id,
            "promotion_receipt_id": receipt_id,
            "candidate_id": entry.candidate_id,
            "authority_receipt": asdict(authority_receipt),
        },
    }
    _append_owned_materialization_record(
        _materialization_receipt_path(outbox_path),
        record,
    )


def _read_materialization_authority_receipt(
    *,
    receipt_id: str,
    outbox_path: Path | None,
    candidate_id: str,
    expected: AuthorityReceipt,
    recorded_not_before: str | None,
    snapshot: ReceiptSourceSnapshot | None = None,
) -> AuthorityReceipt | None:
    event_id = _materialization_authority_event_id(receipt_id)
    if snapshot is None:
        snapshot = read_receipt_source_snapshot(
            outbox_path=_materialization_receipt_path(outbox_path)
        )
    matching = [
        record
        for record in snapshot.records
        if _linked_authority_record(
            record,
            receipt_id,
            authority_receipt_id=expected.receipt_id,
            decision_id=expected.decision_id,
            token_id=expected.decision_token_id,
        )
    ]
    _require_canonical_receipt_records(matching)
    if any(
        record.get("event_id") != event_id
        or record_event(record) != MEMORY_MATERIALIZATION_AUTHORITY_EVENT
        for record in matching
    ):
        raise MemoryMaterializationError(
            "memory AuthorityReceipt event is invalid"
        )
    if not matching:
        if snapshot.unavailable_sources:
            raise MemoryMaterializationError(
                "configured receipt source is unavailable during AuthorityReceipt reconciliation"
            )
        return None
    payloads = [record_payload(record) for record in matching]
    if any(
        not _typed_evidence_matches(payload, payloads[0])
        for payload in payloads[1:]
    ):
        raise MemoryMaterializationError(
            "conflicting memory AuthorityReceipts share one identity"
        )
    payload = payloads[0]
    raw_authority = payload.get("authority_receipt")
    if not isinstance(raw_authority, dict):
        raise MemoryMaterializationError(
            "memory AuthorityReceipt event is malformed"
        )
    raw_recorded_at = raw_authority.get("recorded_at")
    if not isinstance(raw_recorded_at, str):
        raise MemoryMaterializationError(
            "memory AuthorityReceipt event is invalid"
        )
    authority_recorded_at = _parse_iso_timestamp(raw_recorded_at)
    recorded_not_before_at = _parse_iso_timestamp(recorded_not_before)
    expected_authority = asdict(expected)
    expected_authority["recorded_at"] = raw_recorded_at
    if not _typed_evidence_matches(raw_authority, expected_authority):
        raise MemoryMaterializationError(
            "memory AuthorityReceipt event is invalid"
        )
    if any(
        record.get("trace_id") != expected.trace_id
        or record.get("source") != MEMORY_MATERIALIZATION_SOURCE
        or record.get("timestamp") != raw_recorded_at
        or not _is_iso_timestamp(record.get("timestamp"))
        for record in matching
    ) or (
        authority_recorded_at is None
        or recorded_not_before_at is None
        or authority_recorded_at < recorded_not_before_at
    ):
        raise MemoryMaterializationError(
            "memory AuthorityReceipt event is invalid"
        )
    try:
        authority = AuthorityReceipt(**raw_authority)
    except (TypeError, ValueError) as exc:
        raise MemoryMaterializationError(
            "memory AuthorityReceipt event is invalid"
        ) from exc
    if (
        payload.get("materialization_id") != receipt_id
        or payload.get("promotion_receipt_id") != receipt_id
        or payload.get("candidate_id") != candidate_id
        or authority != replace(expected, recorded_at=raw_recorded_at)
    ):
        raise MemoryMaterializationError(
            "persisted AuthorityReceipt does not match memory materialization"
        )
    return authority


def _owned_jsonl_contains_complete_materialization_chain(
    records: tuple[dict[str, Any], ...],
    *,
    decision: ReviewDecisionRecord,
) -> bool:
    """Validate one historical materialization from the owned JSONL bytes only."""

    try:
        receipt_id = _stable_materialization_id_from_fields(
            "receipt",
            vault_id=decision.vault_id,
            channel=decision.channel,
            candidate_id=decision.candidate_id,
        )
        trace_id = _stable_materialization_id_from_fields(
            "trace",
            vault_id=decision.vault_id,
            channel=decision.channel,
            candidate_id=decision.candidate_id,
        )
        promotion_matches = [
            record
            for record in records
            if record.get("event_id") == receipt_id
            or record_payload(record).get("receipt_id") == receipt_id
        ]
        if len(promotion_matches) != 1:
            return False
        promotion = promotion_matches[0]
        payload = record_payload(promotion)
        artifact_path = payload.get("artifact_path")
        artifact_uuid = payload.get("artifact_uuid")
        basis = payload.get("basis")
        source_event = f"memory-promote:{decision.candidate_id}"
        expected_artifact_uuid = _stable_materialization_id_from_fields(
            "artifact",
            vault_id=decision.vault_id,
            channel=decision.channel,
            candidate_id=decision.candidate_id,
        )
        expected_authority = {
            "mode": "governed_execution",
            "component": MEMORY_MATERIALIZATION_SOURCE,
            "executor": MEMORY_MATERIALIZATION_SOURCE,
            "requested_by": decision.decided_by,
        }
        expected_outcome = {
            "status": "applied",
            "review_state": "accepted",
            "maturity": "semantic_memory",
        }
        promotion_keys = {
            "receipt_id",
            "intent_event_id",
            "source_event",
            "trace_id",
            "vault_id",
            "channel",
            "artifact_uuid",
            "artifact_path",
            "transition_family",
            "target_maturity",
            "executor",
            "authority",
            "basis",
            "outcome",
            "artifact_linkage",
            "policy_decision",
            "decision_token",
            "state_owner_receipt",
        }
        if (
            promotion.keys()
            != {"event", "event_id", "trace_id", "source", "timestamp", "payload"}
            or payload.keys() != promotion_keys
            or record_event(promotion) != PROMOTION_TRANSITION_APPLIED
            or promotion.get("event_id") != receipt_id
            or promotion.get("trace_id") != trace_id
            or promotion.get("source") != MEMORY_MATERIALIZATION_SOURCE
            or not _is_iso_timestamp(promotion.get("timestamp"))
            or not _is_nonempty_string(artifact_path)
            or PurePosixPath(cast(str, artifact_path)).is_absolute()
            or ".." in PurePosixPath(cast(str, artifact_path)).parts
            or artifact_uuid != expected_artifact_uuid
            or payload.get("receipt_id") != receipt_id
            or payload.get("intent_event_id") != source_event
            or payload.get("source_event") != source_event
            or payload.get("trace_id") != trace_id
            or payload.get("vault_id") != decision.vault_id
            or payload.get("channel") != decision.channel
            or payload.get("transition_family") != "agent_memory_materialization"
            or payload.get("target_maturity") != "semantic_memory"
            or payload.get("executor") != MEMORY_MATERIALIZATION_SOURCE
            or not _typed_evidence_matches(
                payload.get("authority"), expected_authority
            )
            or not isinstance(basis, dict)
            or type(basis.get("inferred")) is not bool
            or not _typed_evidence_matches(
                basis,
                {
                    "source_event": source_event,
                    "intent_type": "agent_memory_materialization",
                    "candidate_id": decision.candidate_id,
                    "scope_id": decision.scope_id,
                    "inferred": basis.get("inferred"),
                    "source_refs": list(decision.source_refs),
                },
            )
            or not _typed_evidence_matches(payload.get("outcome"), expected_outcome)
            or not _typed_evidence_matches(
                payload.get("artifact_linkage"),
                {
                    "artifact_uuid": artifact_uuid,
                    "artifact_path": artifact_path,
                    "candidate_id": decision.candidate_id,
                },
            )
        ):
            return False
        governed_facts = _governed_materialization_facts_from_payload(
            payload,
            receipt_id=receipt_id,
            persisted=decision,
            artifact_path=cast(str, artifact_path),
            trace_id=trace_id,
        )
        if governed_facts is None:
            return False
        promotion_recorded_at = _validated_promotion_recorded_at(
            promotion,
            governed_facts,
        )
        decision_id, token_id = _materialization_governed_ids(
            receipt_id=receipt_id,
            persisted=decision,
            artifact_path=cast(str, artifact_path),
        )
        linked_promotions = [
            record
            for record in records
            if _linked_promotion_record(
                record,
                receipt_id,
                candidate_id=decision.candidate_id,
                vault_id=decision.vault_id,
                channel=decision.channel,
                decision_id=decision_id,
                token_id=token_id,
            )
        ]
        if len(linked_promotions) != 1 or linked_promotions[0] is not promotion:
            return False
        expected_receipt = _materialization_authority_receipt(
            receipt_id=receipt_id,
            artifact_path=cast(str, artifact_path),
            trace_id=trace_id,
            governed_facts=governed_facts,
        )
        authority_matches = [
            record
            for record in records
            if _linked_authority_record(
                record,
                receipt_id,
                authority_receipt_id=expected_receipt.receipt_id,
                decision_id=decision_id,
                token_id=token_id,
            )
        ]
        if len(authority_matches) != 1 or authority_matches[0].keys() != {
            "event",
            "event_id",
            "trace_id",
            "source",
            "timestamp",
            "payload",
        }:
            return False
        authority_payload = record_payload(authority_matches[0])
        if authority_payload.keys() != {
            "materialization_id",
            "promotion_receipt_id",
            "candidate_id",
            "authority_receipt",
        }:
            return False
        return (
            _read_materialization_authority_receipt(
                receipt_id=receipt_id,
                outbox_path=None,
                candidate_id=decision.candidate_id,
                expected=expected_receipt,
                recorded_not_before=promotion_recorded_at,
                snapshot=ReceiptSourceSnapshot(
                    records=records,
                    unavailable_sources=(),
                ),
            )
            is not None
        )
    except (MemoryMaterializationError, TypeError, ValueError):
        return False


def _validate_materialization_receipt_chain(
    *,
    receipt_id: str,
    outbox_path: Path | None,
    entry: ReviewEntry,
    artifact_path: str,
    trace_id: str,
    persisted: ReviewDecisionRecord,
    governed_facts: _GovernedMaterializationFacts,
    expected: AuthorityReceipt,
    snapshot: ReceiptSourceSnapshot,
) -> AuthorityReceipt:
    persisted_facts = _recover_governed_materialization_facts(
        receipt_id,
        outbox_path=outbox_path,
        entry=entry,
        persisted=persisted,
        artifact_path=artifact_path,
        trace_id=trace_id,
        snapshot=snapshot,
    )
    if persisted_facts is None or persisted_facts != governed_facts:
        raise MemoryMaterializationError(
            "complete governed materialization receipt chain was not queryable"
        )
    promotion_recorded_at = _promotion_recorded_at_from_snapshot(
        snapshot,
        receipt_id=receipt_id,
        governed_facts=governed_facts,
    )
    persisted_receipt = _read_materialization_authority_receipt(
        receipt_id=receipt_id,
        outbox_path=outbox_path,
        candidate_id=entry.candidate_id,
        expected=expected,
        recorded_not_before=promotion_recorded_at,
        snapshot=snapshot,
    )
    if persisted_receipt is None:
        raise MemoryMaterializationError(
            "memory materialization AuthorityReceipt was not queryable"
        )
    return persisted_receipt


@contextmanager
def _materialization_terminal_guard(
    *,
    receipt_id: str,
    outbox_path: Path | None,
    entry: ReviewEntry,
    artifact_path: str | None,
    trace_id: str,
    persisted: ReviewDecisionRecord,
    governed_facts: _GovernedMaterializationFacts | None,
) -> Iterator[None]:
    """Fence one coherent authority-chain snapshot through terminal commit."""

    if artifact_path is None or governed_facts is None:
        raise MemoryMaterializationError(
            "materialization cannot terminalize without governed facts"
        )
    path = _materialization_receipt_path(outbox_path)
    expected = _materialization_authority_receipt(
        receipt_id=receipt_id,
        artifact_path=artifact_path,
        trace_id=trace_id,
        governed_facts=governed_facts,
    )
    with jsonl_outbox_append_lock(path) as canonical_path:
        if not canonical_path.exists() or not canonical_path.is_file():
            raise MemoryMaterializationError(
                "owned materialization receipt source is unavailable during reconciliation"
            )
        _validate_materialization_source_marker(
            canonical_path,
            expected_source_binding=persisted.materialization_source_binding,
        )
        # A prior append may have written a complete, readable JSONL record and
        # then failed its fsync. Visibility is not durability: retry must
        # re-establish the source-file barrier under the same append lock before
        # those bytes can authorize the terminal decision-store commit.
        _fsync_materialization_file(canonical_path)
        validated_source_state = _materialization_source_state(canonical_path)
        snapshot = read_receipt_source_snapshot(
            outbox_path=canonical_path,
            _jsonl_lock_held=True,
        )
        if "JSONL" in snapshot.unavailable_sources:
            raise MemoryMaterializationError(
                "owned materialization receipt source is unavailable during reconciliation"
            )
        if snapshot.unavailable_sources:
            raise MemoryMaterializationError(
                "configured receipt source is unavailable during terminal reconciliation"
            )
        if _materialization_source_state(canonical_path) != validated_source_state:
            raise MemoryMaterializationError(
                "materialization receipt source continuity is broken"
            )
        _validate_materialization_receipt_chain(
            receipt_id=receipt_id,
            outbox_path=canonical_path,
            entry=entry,
            artifact_path=artifact_path,
            trace_id=trace_id,
            persisted=persisted,
            governed_facts=governed_facts,
            expected=expected,
            snapshot=snapshot,
        )
        _write_materialization_source_marker(
            canonical_path,
            source_binding=persisted.materialization_source_binding,
            expected_source_state=validated_source_state,
        )
        final_snapshot = read_receipt_source_snapshot(
            outbox_path=canonical_path,
            _jsonl_lock_held=True,
        )
        if final_snapshot.unavailable_sources:
            raise MemoryMaterializationError(
                "configured receipt source is unavailable during terminal reconciliation"
            )
        _validate_materialization_source_marker(
            canonical_path,
            expected_source_binding=persisted.materialization_source_binding,
        )
        _validate_materialization_receipt_chain(
            receipt_id=receipt_id,
            outbox_path=canonical_path,
            entry=entry,
            artifact_path=artifact_path,
            trace_id=trace_id,
            persisted=persisted,
            governed_facts=governed_facts,
            expected=expected,
            snapshot=final_snapshot,
        )
        yield


def _ensure_materialization_authority_receipt(
    receipt_id: str,
    *,
    outbox_path: Path | None,
    entry: ReviewEntry,
    artifact_path: str,
    trace_id: str,
    persisted: ReviewDecisionRecord,
    governed_facts: _GovernedMaterializationFacts,
) -> AuthorityReceipt:
    _require_owned_materialization_receipt_source(
        outbox_path,
        expected_source_binding=persisted.materialization_source_binding,
    )
    expected = _materialization_authority_receipt(
        receipt_id=receipt_id,
        artifact_path=artifact_path,
        trace_id=trace_id,
        governed_facts=governed_facts,
    )
    snapshot = read_receipt_source_snapshot(
        outbox_path=_materialization_receipt_path(outbox_path)
    )
    promotion_recorded_at = _promotion_recorded_at_from_snapshot(
        snapshot,
        receipt_id=receipt_id,
        governed_facts=governed_facts,
    )
    existing = _read_materialization_authority_receipt(
        receipt_id=receipt_id,
        outbox_path=outbox_path,
        candidate_id=entry.candidate_id,
        expected=expected,
        recorded_not_before=promotion_recorded_at,
        snapshot=snapshot,
    )
    if existing is None:
        _append_materialization_authority_receipt(
            outbox_path,
            receipt_id=receipt_id,
            entry=entry,
            trace_id=trace_id,
            authority_receipt=expected,
        )
    _require_owned_materialization_receipt_source(
        outbox_path,
        expected_source_binding=persisted.materialization_source_binding,
    )
    snapshot = read_receipt_source_snapshot(
        outbox_path=_materialization_receipt_path(outbox_path)
    )
    return _validate_materialization_receipt_chain(
        receipt_id=receipt_id,
        outbox_path=outbox_path,
        entry=entry,
        artifact_path=artifact_path,
        trace_id=trace_id,
        persisted=persisted,
        governed_facts=governed_facts,
        expected=expected,
        snapshot=snapshot,
    )


def _append_owned_materialization_record(
    path: Path,
    record: dict[str, Any],
    *,
    _jsonl_lock_held: bool = False,
    clear_target_reservation: str | None = None,
) -> None:
    """Append without recreating the owned source after its first reservation."""

    def append_locked(canonical_path: Path) -> None:
        if not canonical_path.exists() or not canonical_path.is_file():
            raise MemoryMaterializationError(
                "owned materialization receipt source is unavailable during reconciliation"
            )
        append_jsonl_record(
            canonical_path,
            record,
            require_event_id=True,
            _lock_held=True,
        )
        _write_materialization_source_marker(
            canonical_path,
            clear_target_reservation=clear_target_reservation,
        )

    if _jsonl_lock_held:
        append_locked(path.expanduser().resolve(strict=False))
        return
    with jsonl_outbox_append_lock(path) as canonical_path:
        append_locked(canonical_path)


def _recover_applied_receipt(
    receipt_id: str,
    *,
    entry: ReviewEntry,
    vault_root: Path,
    outbox_path: Path | None,
    scope_id: str,
    persisted: ReviewDecisionRecord,
    vault_id: str,
) -> PromotionReceiptRow | None:
    snapshot = read_receipt_source_snapshot(
        outbox_path=_materialization_receipt_path(outbox_path)
    )
    raw_matches = [
        record
        for record in snapshot.records
        if _linked_promotion_record(
            record,
            receipt_id,
            candidate_id=entry.candidate_id,
            vault_id=vault_id,
            channel=persisted.channel,
        )
    ]
    _require_canonical_receipt_records(raw_matches)
    if any(
        record.get("event_id") != receipt_id
        or record_event(record) != PROMOTION_TRANSITION_APPLIED
        for record in raw_matches
    ):
        raise MemoryMaterializationError(
            "persisted memory promotion receipt identity is not queryable"
        )
    if raw_matches and any(
        not _receipt_records_match(record, raw_matches[0])
        for record in raw_matches[1:]
    ):
        raise MemoryMaterializationError(
            "multiple conflicting applied receipts exist for one memory materialization"
        )
    result = query_promotion_receipts(
        PromotionReceiptQuery(receipt_or_source_event_id=receipt_id),
        vault_root=vault_root,
        outbox_path=_materialization_receipt_path(outbox_path),
    )
    if not result.source_available:
        raise MemoryMaterializationError(
            "configured promotion receipt source is unavailable during reconciliation"
        )
    matches = [row for row in result.rows if row.receipt_id == receipt_id]
    if not matches:
        if raw_matches:
            raise MemoryMaterializationError(
                "persisted memory promotion receipt identity is not queryable"
            )
        return None
    if any(
        not _typed_evidence_matches(asdict(row), asdict(matches[0]))
        for row in matches[1:]
    ):
        raise MemoryMaterializationError(
            "multiple conflicting applied receipts exist for one memory materialization"
        )
    row = matches[0]
    if (
        row.outcome_status != "applied"
        or row.vault_id != vault_id
        or row.basis.get("candidate_id") != entry.candidate_id
        or row.basis.get("scope_id") != scope_id
        or row.artifact_uuid is None
        or row.artifact_path is None
    ):
        raise MemoryMaterializationError(
            "persisted memory materialization receipt conflicts with review authority"
        )
    recovered = _read_materialized_note(row.artifact_path, vault_root=vault_root)
    if recovered is None or recovered[:3] != (
        entry.candidate_id,
        scope_id,
        row.artifact_uuid,
    ):
        raise MemoryMaterializationError(
            "persisted memory materialization receipt does not match its artifact"
        )
    if recovered[3] != _render_memory_note(
        entry,
        artifact_uuid=row.artifact_uuid,
        scope_id=scope_id,
        persisted=persisted,
    ):
        raise MemoryMaterializationError(
            "persisted memory materialization artifact content changed"
        )
    return row


def _find_materialized_note(
    *,
    vault_root: Path,
    entry: ReviewEntry,
    scope_id: str,
    persisted: ReviewDecisionRecord,
) -> tuple[str, str] | None:
    matches: list[tuple[str, str]] = []
    for path in vault_root.rglob("*.md"):
        relative_path = path.relative_to(vault_root).as_posix()
        recovered = _read_materialized_note(relative_path, vault_root=vault_root)
        if recovered is None:
            document = _read_materialized_note_document(
                relative_path,
                vault_root=vault_root,
            )
            if document is not None:
                frontmatter, _ = document
                if (
                    frontmatter.get("promoted_from_candidate_id"),
                    frontmatter.get("scope_id"),
                ) == (entry.candidate_id, scope_id):
                    raise MemoryMaterializationError(
                        "candidate-bound recovery artifact content changed"
                    )
            continue
        if recovered[:2] != (entry.candidate_id, scope_id):
            continue
        if recovered[3] != _render_memory_note(
            entry,
            artifact_uuid=recovered[2],
            scope_id=scope_id,
            persisted=persisted,
        ):
            raise MemoryMaterializationError(
                "candidate-bound recovery artifact content changed"
            )
        matches.append((recovered[2], relative_path))
    if len(matches) > 1:
        raise MemoryMaterializationError(
            "multiple vault artifacts exist for one memory candidate"
        )
    return matches[0] if matches else None


def _resolve_existing_vault_path(vault_root: Path, relative_path: str) -> Path:
    safe_relative = _safe_rel_path(relative_path)
    lexical_root = vault_root.resolve()
    lexical_path = lexical_root / safe_relative
    current = lexical_root
    for part in PurePosixPath(safe_relative).parts:
        current = current / part
        if current.is_symlink():
            raise MemoryMaterializationError(
                "materialization recovery artifact may not traverse a symlink"
            )
    try:
        resolved = lexical_path.resolve(strict=True)
    except OSError as exc:
        raise MemoryMaterializationError(
            "materialization recovery artifact is missing"
        ) from exc
    if not resolved.is_relative_to(lexical_root):
        raise MemoryMaterializationError(
            "materialization recovery artifact must stay inside the vault"
        )
    return resolved


def _read_materialized_note(
    relative_path: str,
    *,
    vault_root: Path,
) -> tuple[str, str, str, str] | None:
    document = _read_materialized_note_document(
        relative_path,
        vault_root=vault_root,
    )
    if document is None:
        return None
    frontmatter, body = document
    candidate_id = frontmatter.get("promoted_from_candidate_id")
    scope_id = frontmatter.get("scope_id")
    artifact_uuid = frontmatter.get("uuid")
    if (
        frontmatter.get("agent_promoted") is not True
        or frontmatter.get("artifact_type") != "semantic_memory"
        or not isinstance(candidate_id, str)
        or not isinstance(scope_id, str)
        or not isinstance(artifact_uuid, str)
    ):
        return None
    return candidate_id, scope_id, artifact_uuid, body


def _read_materialized_note_document(
    relative_path: str,
    *,
    vault_root: Path,
) -> tuple[dict[str, Any], str] | None:
    try:
        body = read_create_once_winner_relative(relative_path, vault_root=vault_root)
    except (OSError, UnicodeError, KnowledgeWriteConflict):
        return None
    if not body.startswith("---\n"):
        return None
    try:
        _, raw_frontmatter, _ = body.split("---\n", 2)
        frontmatter = yaml.safe_load(raw_frontmatter)
    except (ValueError, yaml.YAMLError):
        return None
    if not isinstance(frontmatter, dict):
        return None
    return frontmatter, body


def _render_memory_note(
    entry: ReviewEntry,
    *,
    artifact_uuid: str,
    scope_id: str,
    persisted: ReviewDecisionRecord,
) -> str:
    candidate = entry.candidate
    frontmatter = {
        "uuid": artifact_uuid,
        "artifact_class": "agentic_memory",
        "artifact_type": "semantic_memory",
        "agent_promoted": True,
        "labels": ["agent-promoted-memory"],
        "promoted_from_candidate_id": candidate.candidate_id,
        "scope_id": scope_id,
        "source_refs": list(candidate.source_refs),
        "inferred": candidate.inferred,
        "generated_by": candidate.generated_by,
        "derived_from": candidate.derived_from,
        "decided_by": persisted.decided_by,
        "decided_at": _iso(persisted.decided_at),
    }
    body = candidate.content or candidate.title
    yaml_block = yaml.safe_dump(frontmatter, sort_keys=True, allow_unicode=False).strip()
    return f"---\n{yaml_block}\n---\n\n# {candidate.title}\n\n{body}\n"


def _append_promotion_receipt(
    outbox_path: Path | None,
    *,
    entry: ReviewEntry,
    vault_context: VaultContext,
    channel: str,
    artifact_uuid: str,
    artifact_path: str,
    trace_id: str,
    scope_id: str,
    status: str,
    error: str | None = None,
    receipt_id: str | None = None,
    decided_by: str | None = None,
    governed_facts: _GovernedMaterializationFacts | None = None,
    _jsonl_lock_held: bool = False,
) -> str:
    receipt_id = receipt_id or uuid4().hex
    timestamp = _iso(datetime.now(timezone.utc))
    payload: dict[str, Any] = {
        "receipt_id": receipt_id,
        "intent_event_id": f"memory-promote:{entry.candidate_id}",
        "source_event": f"memory-promote:{entry.candidate_id}",
        "trace_id": trace_id,
        "vault_id": _materialization_vault_identity(vault_context),
        "channel": channel,
        "artifact_uuid": artifact_uuid,
        "artifact_path": artifact_path,
        "transition_family": "agent_memory_materialization",
        "target_maturity": "semantic_memory",
        "executor": MEMORY_MATERIALIZATION_SOURCE,
        "authority": {
            "mode": "governed_execution",
            "component": MEMORY_MATERIALIZATION_SOURCE,
            "executor": MEMORY_MATERIALIZATION_SOURCE,
            "requested_by": decided_by or entry.decided_by,
        },
        "basis": {
            "source_event": f"memory-promote:{entry.candidate_id}",
            "intent_type": "agent_memory_materialization",
            "candidate_id": entry.candidate_id,
            "scope_id": scope_id,
            "inferred": entry.inferred,
            "source_refs": list(entry.source_refs),
        },
        "outcome": {
            "status": status,
            "review_state": "accepted",
            "maturity": "semantic_memory",
        },
        "artifact_linkage": {
            "artifact_uuid": artifact_uuid,
            "artifact_path": artifact_path,
            "candidate_id": entry.candidate_id,
        },
    }
    if error:
        payload["outcome"]["error"] = error
    if governed_facts is not None:
        payload.update(
            {
                "policy_decision": asdict(governed_facts.grant.policy_decision),
                "decision_token": asdict(governed_facts.grant.decision_token),
                "state_owner_receipt": asdict(governed_facts.mutation_receipt),
            }
        )
    record = {
        "event": PROMOTION_TRANSITION_APPLIED,
        "event_id": receipt_id,
        "trace_id": trace_id,
        "source": MEMORY_MATERIALIZATION_SOURCE,
        "timestamp": timestamp,
        "payload": payload,
    }
    path = _materialization_receipt_path(outbox_path)
    _append_owned_materialization_record(
        path,
        record,
        _jsonl_lock_held=_jsonl_lock_held,
        clear_target_reservation=receipt_id if status == "applied" else None,
    )
    return receipt_id


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


__all__ = [
    "MemoryMaterializationError",
    "MemoryMaterializationResult",
    "DEFAULT_MATERIALIZATION_RECEIPTS_PATH",
    "materialize_promoted_memory",
]
