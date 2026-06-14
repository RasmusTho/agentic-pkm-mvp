"""Materialize a moment as a governed, vault-native artifact with a receipt.

Mirrors the governed-write pattern of ``app/agent_memory/materialization.py``:
the only durable effect (writing the moment artifact) routes through the write
guard and emits a human-legible accountability receipt. There are no hidden
writes, and no external side-effects. Materialization is ``Act`` tier per #1881.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.knowledge.write_ops import write_note_relative
from app.relevance.schema import Moment
from app.vault.manager import VaultContext
from app.vault.markdown_settings import render_markdown_settings
from app.vault.paths import get_vault_system_dir_rel
from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard, WritesBlockedError

MOMENT_MATERIALIZE_ACTION = "moment.materialize"
MOMENT_SOURCE = "relevance.materialization"
MOMENT_MATERIALIZED_EVENT = "moment.materialized"
DEFAULT_MOMENT_RECEIPTS_PATH = Path("runtime/relevance/moment_receipts.jsonl")


class MomentMaterializationError(RuntimeError):
    """Raised when a moment cannot be materialized through governance."""


@dataclass(frozen=True)
class MomentMaterializationResult:
    status: str
    moment_uuid: str
    artifact_path: str | None
    receipt_id: str | None
    reason: str | None = None


def materialize_moment(
    moment: Moment,
    *,
    vault_context: VaultContext,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
    outbox_path: Path | None = None,
) -> MomentMaterializationResult:
    """Write the moment artifact via the write guard and emit a receipt."""

    vault_root = _vault_root(vault_context)
    system_dir = get_vault_system_dir_rel(vault_root)
    artifact_path = f"{system_dir}/moments/{moment.uuid}.md"
    receipt_id = uuid4().hex
    trace_id = uuid4().hex
    moment.receipt_ref = receipt_id
    content = render_markdown_settings(moment.to_frontmatter(), moment.to_markdown_body())

    try:
        write_guard.assert_writes_allowed(MOMENT_MATERIALIZE_ACTION)
        write_note_relative(artifact_path, content, vault_root=vault_root)
    except WritesBlockedError as exc:
        _append_moment_receipt(
            outbox_path,
            moment=moment,
            vault_context=vault_context,
            artifact_path=artifact_path,
            receipt_id=receipt_id,
            trace_id=trace_id,
            status="blocked",
            error=str(exc),
        )
        return MomentMaterializationResult(
            status="blocked",
            moment_uuid=moment.uuid,
            artifact_path=None,
            receipt_id=receipt_id,
            reason=str(exc),
        )
    except Exception as exc:  # pragma: no cover - defensive failure receipt
        _append_moment_receipt(
            outbox_path,
            moment=moment,
            vault_context=vault_context,
            artifact_path=artifact_path,
            receipt_id=receipt_id,
            trace_id=trace_id,
            status="failed",
            error=str(exc),
        )
        raise MomentMaterializationError(
            f"moment materialization failed; receipt={receipt_id}"
        ) from exc

    _append_moment_receipt(
        outbox_path,
        moment=moment,
        vault_context=vault_context,
        artifact_path=artifact_path,
        receipt_id=receipt_id,
        trace_id=trace_id,
        status="applied",
    )
    return MomentMaterializationResult(
        status="materialized",
        moment_uuid=moment.uuid,
        artifact_path=artifact_path,
        receipt_id=receipt_id,
    )


def query_moment_receipts(
    *,
    outbox_path: Path | None = None,
    artifact_path: str | None = None,
) -> list[dict]:
    """Read back the moment materialization receipts (accountability projection)."""

    path = outbox_path or DEFAULT_MOMENT_RECEIPTS_PATH
    if not path.exists():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("event") != MOMENT_MATERIALIZED_EVENT:
            continue
        payload = record.get("payload") or {}
        if artifact_path is not None and payload.get("artifact_path") != artifact_path:
            continue
        rows.append(record)
    return rows


def _append_moment_receipt(
    outbox_path: Path | None,
    *,
    moment: Moment,
    vault_context: VaultContext,
    artifact_path: str,
    receipt_id: str,
    trace_id: str,
    status: str,
    error: str | None = None,
) -> None:
    timestamp = _iso(datetime.now(timezone.utc))
    receipt: dict[str, Any] = {
        "action_taken": MOMENT_MATERIALIZE_ACTION,
        "outcome": status,
        "timestamp": timestamp,
        "message": f"moment '{moment.need.summary}' ({moment.urgency.band})",
        "inverse_action": None,
    }
    outcome: dict[str, Any] = {"status": status, "lifecycle": moment.lifecycle}
    if error:
        outcome["error"] = error
    payload: dict[str, Any] = {
        "receipt_id": receipt_id,
        "trace_id": trace_id,
        "vault_id": vault_context.active_vault_id,
        "artifact_uuid": moment.uuid,
        "artifact_path": artifact_path,
        "governance_tier": "act",
        "authority": {
            "mode": "governed_execution",
            "component": MOMENT_SOURCE,
            "executor": MOMENT_SOURCE,
        },
        "basis": {
            "trigger": moment.trigger.model_dump(exclude_none=True),
            "need": moment.need.model_dump(),
            "urgency": moment.urgency.model_dump(),
            "produced_by": moment.provenance.produced_by,
        },
        "outcome": outcome,
        "receipt": receipt,
    }
    record: dict[str, Any] = {
        "event": MOMENT_MATERIALIZED_EVENT,
        "event_id": receipt_id,
        "trace_id": trace_id,
        "source": MOMENT_SOURCE,
        "timestamp": timestamp,
        "payload": payload,
    }
    path = outbox_path or DEFAULT_MOMENT_RECEIPTS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")


def _vault_root(context: VaultContext) -> Path:
    if not context.active_vault_path:
        raise MomentMaterializationError("vault_context.active_vault_path is required")
    return Path(context.active_vault_path).expanduser().resolve()


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


__all__ = [
    "materialize_moment",
    "query_moment_receipts",
    "MomentMaterializationResult",
    "MomentMaterializationError",
    "MOMENT_MATERIALIZE_ACTION",
    "MOMENT_MATERIALIZED_EVENT",
]
