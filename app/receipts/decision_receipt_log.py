"""Durable, WriteGuard-gated decision-receipt log (canonical judgment record).

Spec: ``docs/DECISION_RECEIPT_LOG/README.md`` (feature #2969).

The judgment log (``decisions`` — the ``review`` / ``evaluate`` / ``classification``
verdicts the governance pipeline records per object) used to live *only* in Postgres,
one of three non-rebuildable stores. This module makes the readable vault surface the
canonical record and leaves Postgres as a rebuildable projection index over it.

Design (from the spec):

- Location: ``vault/<system_dir>/receipts/decisions/decisions-YYYYMM.jsonl`` — dated,
  append-only JSONL shards. One ``schema_version``-stamped JSON object per decision.
- WriteGuard-gated at the seam (C-6): the append asserts
  ``assert_writes_allowed("decision.receipt")`` first. A blocked guard raises loudly
  (``WritesBlockedError``); the governance action never silently proceeds DB-only (C-8).
- Receipt-before-ack (C-5/P-5): the durable log append is the commit point;
  ``insert_decision`` writes the log *first*, then the DB projection.
- ``vault_uuid`` resolution: best-effort at write time. ``decisions.object_id`` is the
  canonical ``store_objects.object_id``. Retained rows may still carry an older continuity UUID
  in ``objects.uuid``. Fresh canonical-only rows have no proven frontmatter continuity identity,
  so they use ``vault_uuid: null``; the same honest null is used when no row resolves or the
  durable lookup is unavailable. Historical receipts that already contain the former canonical-id
  fallback remain replay-compatible,
  never invented. Carrying it lets the projection rebuild re-link a decision whose
  ``object_id`` was re-minted (§5 decoupling payoff, Slice 2).

Scope boundary (Slice 1): the vault receipt log is the durable surface for the *durable*
(Postgres) decision path. Under the explicit ``STORE_BACKEND=memory`` opt-in there is no
durable store and no selected vault — that mode is volatile by contract (I-S4 /
``app/services/decisions.py`` D-7), so the receipt append is skipped there. The guard and
the receipt apply to the real durable path.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg

from app.config.paths import resolve_optional_vault_root
from app.db.db import conn_rw
from app.vault.paths import (
    NoVaultSelectedError,
    resolve_vault_system_dir_rel_or_default,
)
from app.write_guard import DEFAULT_WRITE_GUARD

# Bump when the on-disk record shape changes. Readers/rebuild must tolerate
# older schema_versions or migrate them explicitly.
SCHEMA_VERSION = 1

# WriteGuard action token for the decision-receipt seam. Named (not a silent
# absence of a guard) so it is auditable; not in DEFAULT_BOOTSTRAP_ACTIONS, so a
# write-blocked runtime state denies it loudly.
RECEIPT_WRITE_ACTION = "decision.receipt"

_RECEIPTS_SUBDIR = Path("receipts") / "decisions"


class _Unset:
    """Sentinel so ``vault_uuid=None`` (explicit) differs from "resolve for me"."""


_UNSET = _Unset()


class DecisionReceiptWriteError(RuntimeError):
    """Raised when a decision receipt cannot be durably appended.

    The receipt append is the commit point (receipt-before-ack): the caller
    must see this failure rather than proceed to a DB-only write.
    """


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _shard_name(created_at: datetime) -> str:
    return f"decisions-{created_at.strftime('%Y%m')}.jsonl"


def decisions_receipts_dir(vault_root: Path | None = None) -> Path:
    """Absolute path to the vault decision-receipts directory.

    Resolves the vault system dir the same way companion notes do
    (``resolve_vault_system_dir_rel_or_default``), degrading to the packaged
    default system folder rather than raising on a freshly-initialized vault.
    Raises :class:`NoVaultSelectedError` when no vault is selected.
    """
    root = vault_root if vault_root is not None else resolve_optional_vault_root()
    if root is None:
        raise NoVaultSelectedError(
            "decision receipt log requires a selected vault; VAULT_ROOT is unset"
        )
    root = root.expanduser()
    system_dir_rel = resolve_vault_system_dir_rel_or_default(root)
    return root / system_dir_rel / _RECEIPTS_SUBDIR


def resolve_vault_uuid(object_id: str) -> str | None:
    """Best-effort resolve the vault frontmatter uuid for a runtime ``object_id``.

    ``decisions.object_id`` references ``store_objects.object_id``. Return the retained
    ``objects.uuid`` continuity mapping when present. Fresh canonical-only rows have no
    proven frontmatter UUID, so return ``None`` rather than inventing one; ``None`` is also
    returned when no matching object row exists or the durable lookup is unavailable.
    """
    try:
        with conn_rw() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT legacy.uuid AS vault_uuid
                    FROM store_objects canonical
                    LEFT JOIN objects legacy ON legacy.id = canonical.object_id
                    WHERE canonical.object_id = %s
                    """,
                    (object_id,),
                )
                row = cur.fetchone()
    except psycopg.Error:
        return None
    if not row:
        return None
    value = row["vault_uuid"] if isinstance(row, dict) else row[0]
    return str(value) if value is not None else None


def build_receipt(
    *,
    object_id: str,
    key: str,
    value: dict[str, Any],
    trace_id: str,
    created_at: datetime,
    vault_uuid: str | None,
) -> dict[str, Any]:
    """Build the schema-stamped receipt record.

    ``trace_id`` is folded into the ``value`` envelope exactly as the DB
    projection stores it (``app/services/decisions.py::insert_decision``), so the
    log and the projection carry identical value payloads and the rebuild is a
    faithful replay.
    """
    stored_value = dict(value)
    stored_value["trace_id"] = trace_id
    return {
        "schema_version": SCHEMA_VERSION,
        "object_id": object_id,
        "vault_uuid": vault_uuid,
        "key": key,
        "value": stored_value,
        "created_at": created_at.astimezone(timezone.utc).isoformat(),
    }


def _write_receipt_line(
    record: dict[str, Any], created_at: datetime, vault_root: Path | None = None
) -> None:
    """Append one already-built receipt record to the correct dated shard.

    Shared low-level write primitive: :func:`append_decision_receipt` builds its
    record via :func:`build_receipt` (which folds ``trace_id`` into the value
    envelope) and calls this. The slice-4 historical export
    (``app/jobs/decisions_export.py``) calls this directly with a record whose
    ``value`` must pass through unmodified — folding a ``trace_id`` into a
    historical row that never had one would misrepresent the record and break
    the export's idempotency check. Callers are responsible for the WriteGuard
    assertion (``assert_writes_allowed(RECEIPT_WRITE_ACTION)``) before calling.
    """
    try:
        target_dir = decisions_receipts_dir(vault_root)
        target_dir.mkdir(parents=True, exist_ok=True)
        shard = target_dir / _shard_name(created_at)
        line = json.dumps(record, ensure_ascii=False, sort_keys=True)
        with shard.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError as exc:
        raise DecisionReceiptWriteError(
            f"decision receipt append failed for object_id={record.get('object_id')} "
            f"key={record.get('key')}: {exc}"
        ) from exc


def append_decision_receipt(
    *,
    object_id: str,
    key: str,
    value: dict[str, Any],
    trace_id: str,
    created_at: datetime | None = None,
    vault_root: Path | None = None,
    vault_uuid: str | None | _Unset = _UNSET,
) -> dict[str, Any]:
    """Append one decision receipt to the durable JSONL log.

    Commit-point semantics (receipt-before-ack): this is called *before* the DB
    projection write. The WriteGuard is asserted at the seam first — a blocked
    guard raises ``WritesBlockedError`` (loud, never silent DB-only). Any I/O
    failure is wrapped in :class:`DecisionReceiptWriteError` so the caller's write
    fails as a whole.

    ``vault_uuid`` defaults to a best-effort DB resolution; pass an explicit value
    (including ``None``) to override (e.g. when already resolved by the caller).
    Returns the appended record.
    """
    # WriteGuard at the seam (C-6). Asserted BEFORE any path resolution or I/O so
    # a blocked runtime cannot even begin a DB-only governance action.
    DEFAULT_WRITE_GUARD.assert_writes_allowed(RECEIPT_WRITE_ACTION)

    created = created_at or _now()
    resolved_uuid = (
        resolve_vault_uuid(object_id) if isinstance(vault_uuid, _Unset) else vault_uuid
    )
    record = build_receipt(
        object_id=object_id,
        key=key,
        value=value,
        trace_id=trace_id,
        created_at=created,
        vault_uuid=resolved_uuid,
    )

    _write_receipt_line(record, created, vault_root)
    return record


def iter_decision_receipts(vault_root: Path | None = None) -> list[dict[str, Any]]:
    """Read every decision receipt across all shards, ordered by ``created_at``.

    Used by the projection rebuild (Slice 2) and the doctor equivalence check.
    Malformed lines are skipped defensively (never crash a rebuild on one bad
    line); every valid record is returned. Missing directory → empty list.
    """
    try:
        receipts_dir = decisions_receipts_dir(vault_root)
    except NoVaultSelectedError:
        return []
    if not receipts_dir.exists():
        return []

    records: list[dict[str, Any]] = []
    for shard in sorted(receipts_dir.glob("decisions-*.jsonl")):
        try:
            text = shard.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(rec, dict):
                records.append(rec)

    records.sort(key=lambda r: str(r.get("created_at") or ""))
    return records


__all__ = [
    "SCHEMA_VERSION",
    "RECEIPT_WRITE_ACTION",
    "DecisionReceiptWriteError",
    "append_decision_receipt",
    "build_receipt",
    "decisions_receipts_dir",
    "iter_decision_receipts",
    "resolve_vault_uuid",
]
