from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import uuid4

import yaml

from app.agent_memory.candidate import MemoryType
from app.agent_memory.review_decision_store import ReviewDecisionStore
from app.agent_memory.review_queue import ReviewDecision, ReviewEntry, ReviewStatus
from app.events.types import PROMOTION_TRANSITION_APPLIED
from app.knowledge.write_ops import write_note_relative
from app.receipts.promotion_receipts import query_promotion_receipts
from app.vault.manager import VaultContext
from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard

MEMORY_MATERIALIZATION_ACTION = "memory.materialize"
MEMORY_MATERIALIZATION_SOURCE = "agent_memory.materialization"
DEFAULT_MEMORY_DIR = "Agent Memory"


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
        )
        return MemoryMaterializationResult(
            status="not_semantic",
            artifact_path=None,
            receipt_id=None,
            terminal=True,
        )

    vault_root = _vault_root(vault_context)
    artifact_uuid = uuid4().hex
    artifact_path = _unique_memory_path(
        vault_root=vault_root,
        memory_dir=memory_dir,
        title=entry.title,
        candidate_id=entry.candidate_id,
    )
    trace_id = uuid4().hex
    try:
        write_guard.assert_writes_allowed(MEMORY_MATERIALIZATION_ACTION)
        write_note_relative(
            artifact_path,
            _render_memory_note(entry, artifact_uuid=artifact_uuid),
            vault_root=vault_root,
        )
    except Exception as exc:
        receipt_id = _append_promotion_receipt(
            outbox_path,
            entry=entry,
            vault_context=vault_context,
            channel=channel,
            artifact_uuid=artifact_uuid,
            artifact_path=artifact_path,
            trace_id=trace_id,
            status="failed",
            error=str(exc),
        )
        raise MemoryMaterializationError(
            f"memory materialization failed; receipt={receipt_id}"
        ) from exc

    receipt_id = _append_promotion_receipt(
        outbox_path,
        entry=entry,
        vault_context=vault_context,
        channel=channel,
        artifact_uuid=artifact_uuid,
        artifact_path=artifact_path,
        trace_id=trace_id,
        status="applied",
    )
    result = query_promotion_receipts(
        vault_root=vault_root,
        outbox_path=outbox_path,
    )
    if not any(row.receipt_id == receipt_id for row in result.rows):
        raise MemoryMaterializationError("materialization receipt was not queryable")
    decision_store.mark_terminal(
        entry.candidate_id,
        vault_context=vault_context,
        channel=channel,
    )
    return MemoryMaterializationResult(
        status="materialized",
        artifact_path=artifact_path,
        receipt_id=receipt_id,
        terminal=True,
    )


def _require_promoted(entry: ReviewEntry) -> None:
    if entry.status is not ReviewStatus.PROMOTED or entry.decision is not ReviewDecision.PROMOTE:
        raise MemoryMaterializationError("entry must carry a promote decision")


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


def _render_memory_note(entry: ReviewEntry, *, artifact_uuid: str) -> str:
    candidate = entry.candidate
    frontmatter = {
        "uuid": artifact_uuid,
        "artifact_class": "agentic_memory",
        "artifact_type": "semantic_memory",
        "agent_promoted": True,
        "labels": ["agent-promoted-memory"],
        "promoted_from_candidate_id": candidate.candidate_id,
        "source_refs": list(candidate.source_refs),
        "generated_by": candidate.generated_by,
        "derived_from": candidate.derived_from,
        "decided_by": entry.decided_by,
        "decided_at": _iso(entry.decided_at),
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
    status: str,
    error: str | None = None,
) -> str:
    receipt_id = uuid4().hex
    timestamp = _iso(datetime.now(timezone.utc))
    payload: dict[str, Any] = {
        "receipt_id": receipt_id,
        "intent_event_id": f"memory-promote:{entry.candidate_id}",
        "source_event": f"memory-promote:{entry.candidate_id}",
        "trace_id": trace_id,
        "vault_id": vault_context.active_vault_id,
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
            "requested_by": entry.decided_by,
        },
        "basis": {
            "source_event": f"memory-promote:{entry.candidate_id}",
            "intent_type": "agent_memory_materialization",
            "candidate_id": entry.candidate_id,
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
    path = outbox_path or Path("runtime/agent_memory/materialization_receipts.jsonl")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
    return receipt_id


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


__all__ = [
    "MemoryMaterializationError",
    "MemoryMaterializationResult",
    "materialize_promoted_memory",
]
