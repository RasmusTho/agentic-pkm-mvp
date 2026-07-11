"""Append-only, WriteGuard-gated outcome receipts for decision calibration.

The vault JSONL log is canonical.  ``decision_outcomes`` is a rebuildable
Postgres projection, deliberately written only after the receipt is durable.
This module never reads or rewrites the owner's ``decision_record`` note.
"""
from __future__ import annotations

import fcntl
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.config.paths import resolve_optional_vault_root
from app.store.outcome_receipt_projection import (
    insert_outcome_receipt_projection as _insert_projection,
)
from app.vault.paths import NoVaultSelectedError, resolve_vault_system_dir_rel_or_default
from app.write_guard import DEFAULT_WRITE_GUARD

SCHEMA_VERSION = 1
OUTCOME_RECEIPT_WRITE_ACTION = "decision.outcome_receipt"
_RECEIPTS_SUBDIR = Path("receipts") / "decision_outcomes"
_APPEND_LOCK_NAME = ".append.lock"
OutcomeValue = Literal["held", "partly_held", "did_not_hold", "unknown_yet"]


class OutcomeReceipt(BaseModel):
    """The stable, schema-versioned outcome receipt record."""

    schema_version: int = SCHEMA_VERSION
    decision_object_id: UUID
    decision_uuid: UUID
    rung_index: int = Field(ge=0)
    outcome: OutcomeValue
    note: str | None = None
    created_at: datetime


class OutcomeReceiptWriteError(RuntimeError):
    """The canonical receipt could not be appended."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _shard_name(created_at: datetime) -> str:
    return f"decision_outcomes-{created_at.strftime('%Y%m')}.jsonl"


def outcome_receipts_dir(vault_root: Path | None = None) -> Path:
    """Return the selected vault's canonical outcome-receipt directory."""
    root = vault_root if vault_root is not None else resolve_optional_vault_root()
    if root is None:
        raise NoVaultSelectedError(
            "decision outcome receipt log requires a selected vault; VAULT_ROOT is unset"
        )
    root = root.expanduser()
    return root / resolve_vault_system_dir_rel_or_default(root) / _RECEIPTS_SUBDIR


def build_receipt(
    *,
    decision_object_id: str | UUID,
    decision_uuid: str | UUID,
    rung_index: int,
    outcome: OutcomeValue,
    note: str | None = None,
    created_at: datetime | None = None,
) -> dict[str, Any]:
    """Validate and build one JSON-serializable outcome receipt."""
    receipt = OutcomeReceipt(
        decision_object_id=decision_object_id,
        decision_uuid=decision_uuid,
        rung_index=rung_index,
        outcome=outcome,
        note=note,
        created_at=created_at or _now(),
    )
    return receipt.model_dump(mode="json")


def iter_outcome_receipts(vault_root: Path | None = None) -> list[dict[str, Any]]:
    """Read valid canonical receipts without ever modifying existing shards."""
    try:
        receipts_dir = outcome_receipts_dir(vault_root)
    except NoVaultSelectedError:
        return []
    if not receipts_dir.exists():
        return []

    records: list[dict[str, Any]] = []
    for shard in sorted(receipts_dir.glob("decision_outcomes-*.jsonl")):
        try:
            lines = shard.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                records.append(record)
    records.sort(key=lambda record: str(record.get("created_at") or ""))
    return records


def _existing_receipt(
    records: list[dict[str, Any]], decision_uuid: str, rung_index: int
) -> dict[str, Any] | None:
    return next(
        (
            record
            for record in records
            if record.get("decision_uuid") == decision_uuid
            and record.get("rung_index") == rung_index
        ),
        None,
    )


def append_outcome_receipt(
    *,
    decision_object_id: str | UUID,
    decision_uuid: str | UUID,
    rung_index: int,
    outcome: OutcomeValue,
    note: str | None = None,
    created_at: datetime | None = None,
    vault_root: Path | None = None,
) -> dict[str, Any]:
    """Durably append an outcome, then write its derived Postgres projection.

    The guard is asserted before path resolution or any file I/O.  A retry uses
    the canonical existing record and re-attempts the projection insert, making
    the pair idempotent even when a prior projection write failed after append.
    """
    # This is the sole production write seam for outcome receipts.  Keep the
    # assertion before all path resolution/file I/O; do not bootstrap-allow it.
    DEFAULT_WRITE_GUARD.assert_writes_allowed(OUTCOME_RECEIPT_WRITE_ACTION)

    receipt = build_receipt(
        decision_object_id=decision_object_id,
        decision_uuid=decision_uuid,
        rung_index=rung_index,
        outcome=outcome,
        note=note,
        created_at=created_at,
    )
    try:
        target_dir = outcome_receipts_dir(vault_root)
        target_dir.mkdir(parents=True, exist_ok=True)
        # The canonical idempotency key spans all monthly shards.  Serialize
        # check-and-append under one vault-local advisory lock so concurrent
        # retries cannot both observe an absent receipt and append duplicates.
        with (target_dir / _APPEND_LOCK_NAME).open("a+", encoding="utf-8") as lock_handle:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
            existing = _existing_receipt(
                iter_outcome_receipts(vault_root), receipt["decision_uuid"], receipt["rung_index"]
            )
            if existing is not None:
                receipt = existing
            else:
                shard = target_dir / _shard_name(
                    datetime.fromisoformat(receipt["created_at"])
                )
                with shard.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(receipt, ensure_ascii=False, sort_keys=True) + "\n")
    except OSError as exc:
        raise OutcomeReceiptWriteError(
            "decision outcome receipt append failed for "
            f"decision_uuid={decision_uuid} rung_index={rung_index}: {exc}"
        ) from exc

    # Receipt-before-ack: this happens strictly after the append.  A projection
    # failure is visible to the caller; CAL-04 rebuild tooling can repair it.
    _insert_projection(receipt)
    return receipt


__all__ = [
    "SCHEMA_VERSION",
    "OUTCOME_RECEIPT_WRITE_ACTION",
    "OutcomeReceipt",
    "OutcomeReceiptWriteError",
    "OutcomeValue",
    "append_outcome_receipt",
    "build_receipt",
    "iter_outcome_receipts",
    "outcome_receipts_dir",
]
