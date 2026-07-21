"""Append-only, WriteGuard-gated dismissal receipts for decision revisits."""
from __future__ import annotations

import fcntl
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.config.paths import resolve_optional_vault_root
from app.vault.paths import NoVaultSelectedError, resolve_vault_system_dir_rel_or_default
from app.write_guard import DEFAULT_WRITE_GUARD

SCHEMA_VERSION = 1
REVISIT_DISMISSAL_WRITE_ACTION = "decision.revisit_dismissal"
_DISMISSALS_SUBDIR = Path("receipts") / "decision_revisit_dismissals"
_APPEND_LOCK_NAME = ".append.lock"


class RevisitDismissal(BaseModel):
    """A durable marker that a shown revisit rung was set aside."""

    schema_version: int = SCHEMA_VERSION
    decision_object_id: UUID
    decision_uuid: UUID
    rung_index: int = Field(ge=0)
    created_at: datetime


class RevisitDismissalWriteError(RuntimeError):
    """Raised when a dismissal cannot be durably appended."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _shard_name(created_at: datetime) -> str:
    return f"decision_revisit_dismissals-{created_at.strftime('%Y%m')}.jsonl"


def revisit_dismissals_dir(vault_root: Path | None = None) -> Path:
    """Return the selected vault's canonical revisit-dismissal directory."""
    root = vault_root if vault_root is not None else resolve_optional_vault_root()
    if root is None:
        raise NoVaultSelectedError(
            "decision revisit dismissal log requires a selected vault; VAULT_ROOT is unset"
        )
    root = root.expanduser()
    return root / resolve_vault_system_dir_rel_or_default(root) / _DISMISSALS_SUBDIR


def build_dismissal(
    *,
    decision_object_id: str | UUID,
    decision_uuid: str | UUID,
    rung_index: int,
    created_at: datetime | None = None,
) -> dict[str, Any]:
    """Validate and build one JSON-serializable dismissal receipt."""
    dismissal = RevisitDismissal(
        decision_object_id=decision_object_id,
        decision_uuid=decision_uuid,
        rung_index=rung_index,
        created_at=created_at or _now(),
    )
    return dismissal.model_dump(mode="json")


def iter_revisit_dismissals(vault_root: Path | None = None) -> list[dict[str, Any]]:
    """Read canonical dismissal receipts without modifying existing shards."""
    try:
        dismissals_dir = revisit_dismissals_dir(vault_root)
    except NoVaultSelectedError:
        return []
    if not dismissals_dir.exists():
        return []

    records: list[dict[str, Any]] = []
    for shard in sorted(dismissals_dir.glob("decision_revisit_dismissals-*.jsonl")):
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


def _existing_dismissal(
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


def append_revisit_dismissal(
    *,
    decision_object_id: str | UUID,
    decision_uuid: str | UUID,
    rung_index: int,
    created_at: datetime | None = None,
    vault_root: Path | None = None,
) -> dict[str, Any]:
    """Durably append one dismissal marker, idempotently per decision/rung."""
    # The only production dismissal write seam. Keep this before path resolution
    # and I/O so a blocked runtime cannot produce a partial ledger write.
    DEFAULT_WRITE_GUARD.assert_writes_allowed(REVISIT_DISMISSAL_WRITE_ACTION)

    dismissal = build_dismissal(
        decision_object_id=decision_object_id,
        decision_uuid=decision_uuid,
        rung_index=rung_index,
        created_at=created_at,
    )
    try:
        target_dir = revisit_dismissals_dir(vault_root)
        target_dir.mkdir(parents=True, exist_ok=True)
        with (target_dir / _APPEND_LOCK_NAME).open("a+", encoding="utf-8") as lock_handle:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
            existing = _existing_dismissal(
                iter_revisit_dismissals(vault_root),
                dismissal["decision_uuid"],
                dismissal["rung_index"],
            )
            if existing is not None:
                return existing
            shard = target_dir / _shard_name(datetime.fromisoformat(dismissal["created_at"]))
            with shard.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(dismissal, ensure_ascii=False, sort_keys=True) + "\n")
    except OSError as exc:
        raise RevisitDismissalWriteError(
            "decision revisit dismissal append failed for "
            f"decision_uuid={decision_uuid} rung_index={rung_index}: {exc}"
        ) from exc
    return dismissal


__all__ = [
    "SCHEMA_VERSION",
    "REVISIT_DISMISSAL_WRITE_ACTION",
    "RevisitDismissal",
    "RevisitDismissalWriteError",
    "append_revisit_dismissal",
    "build_dismissal",
    "iter_revisit_dismissals",
    "revisit_dismissals_dir",
]
