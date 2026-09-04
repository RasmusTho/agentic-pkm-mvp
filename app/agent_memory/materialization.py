from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any
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
from app.knowledge.errors import KnowledgeWriteConflict
from app.knowledge.write_ops import read_create_once_winner_relative, write_note_relative
from app.receipts.promotion_receipts import (
    PromotionReceiptQuery,
    PromotionReceiptRow,
    query_promotion_receipts,
)
from app.services.outbox import append_jsonl_record
from app.vault.manager import VaultContext
from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard

MEMORY_MATERIALIZATION_ACTION = "memory.materialize"
MEMORY_MATERIALIZATION_SOURCE = "agent_memory.materialization"
DEFAULT_MEMORY_DIR = "Agent Memory"
DEFAULT_MATERIALIZATION_RECEIPTS_PATH = Path(
    "runtime/agent_memory/materialization_receipts.jsonl"
)


@dataclass(frozen=True)
class MemoryMaterializationResult:
    status: str
    artifact_path: str | None
    receipt_id: str | None
    terminal: bool


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
    artifact_path: str | None = None
    try:
        with decision_store.promotion_materialization_transaction(
            entry.candidate_id,
            vault_context=vault_context,
            channel=channel,
            expected_scope_id=requested_scope_id,
            expected_candidate_digest=review_candidate_digest(entry),
        ) as persisted:
            persisted_scope_id = persisted.scope_id
            if persisted_scope_id is None:
                raise MemoryMaterializationError(
                    "persisted promote decision has no scope binding"
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
            else:
                recovered_note = _find_materialized_note(
                    vault_root=vault_root,
                    memory_dir=memory_dir,
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
                    try:
                        write_guard.assert_writes_allowed(MEMORY_MATERIALIZATION_ACTION)
                        write_receipt = write_note_relative(
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
                        if write_receipt.outcome == "already_exists":
                            raced_note = _find_materialized_note(
                                vault_root=vault_root,
                                memory_dir=memory_dir,
                                entry=entry,
                                scope_id=persisted_scope_id,
                                persisted=persisted,
                            )
                            if raced_note is None:
                                raise MemoryMaterializationError(
                                    "memory materialization target was won by a different artifact"
                                )
                            artifact_uuid, artifact_path = raced_note
                    except Exception as exc:
                        failed_receipt_id = _append_promotion_receipt(
                            outbox_path,
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
                        )
                        raise MemoryMaterializationError(
                            f"memory materialization failed; receipt={failed_receipt_id}"
                        ) from exc
                else:
                    artifact_uuid, artifact_path = recovered_note

                _append_promotion_receipt(
                    outbox_path,
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
    vault_identity = _materialization_vault_identity(vault_context)
    identity = (
        f"agent-memory-materialization:{kind}:"
        f"{vault_identity}:{channel}:{entry.candidate_id}"
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
    result = query_promotion_receipts(
        PromotionReceiptQuery(receipt_or_source_event_id=receipt_id),
        vault_root=vault_root,
        outbox_path=outbox_path or DEFAULT_MATERIALIZATION_RECEIPTS_PATH,
    )
    matches = [row for row in result.rows if row.receipt_id == receipt_id]
    if not matches:
        return None
    if len(matches) != 1:
        raise MemoryMaterializationError(
            "multiple applied receipts exist for one memory materialization"
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
    memory_dir: str,
    entry: ReviewEntry,
    scope_id: str,
    persisted: ReviewDecisionRecord,
) -> tuple[str, str] | None:
    root = vault_root / _safe_rel_path(memory_dir)
    if not root.exists():
        return None
    _resolve_existing_vault_path(vault_root, root.relative_to(vault_root).as_posix())
    matches: list[tuple[str, str]] = []
    for path in root.rglob("*.md"):
        relative_path = path.relative_to(vault_root).as_posix()
        recovered = _read_materialized_note(relative_path, vault_root=vault_root)
        if recovered is None or recovered[:2] != (entry.candidate_id, scope_id):
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
    record = {
        "event": PROMOTION_TRANSITION_APPLIED,
        "event_id": receipt_id,
        "trace_id": trace_id,
        "source": MEMORY_MATERIALIZATION_SOURCE,
        "timestamp": timestamp,
        "payload": payload,
    }
    path = outbox_path or DEFAULT_MATERIALIZATION_RECEIPTS_PATH
    append_jsonl_record(path, record, require_event_id=True)
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
