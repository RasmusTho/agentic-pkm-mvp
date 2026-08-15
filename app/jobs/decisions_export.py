"""One-time export of historical DB-only decision rows into the canonical receipt log.

Spec: ``docs/DECISION_RECEIPT_LOG/README.md`` (feat #2969, slice 4, issue #2973).

Slices 1-3 made the receipt log (``app/receipts/decision_receipt_log.py``) canonical
for *new* decisions going forward (dual-write, then read-cutover in docs). They did
not touch decision rows written *before* the dual-write cutover — those exist only
in Postgres. ``rebuild_decisions_projection()`` (slice 2, ``app/jobs/decisions_projection.py``)
replaces the compatibility binding's ``decisions`` rows and replays the log; running it before this
export exists would silently lose those historical DB-only rows (issue #2973,
2026-07-05 comment: prod holds 2 such rows, key ``classification``, written via the
deprecated ``app/stores/postgres.py::PgDecisions.put`` path pre-cutover).

``export_decisions_to_receipt_log()`` closes that gap: it finds every row in the
``decisions`` table not yet represented in the log and appends it as a receipt,
through the same WriteGuard-gated seam live decisions use. It is:

- **Read-only over the DB.** Never truncates, updates, or deletes a ``decisions``
  row. Safe to run against a live table with concurrent writers.
- **Idempotent.** A row already represented in the log (matched on
  ``(object_id, key, created_at, value)`` — the same tuple
  ``doctor_decisions_projection`` compares) is skipped. Re-running after a full or
  partial export finds nothing left to do and appends nothing new.
- **Faithful.** The receipt's ``value`` is the DB row's ``value`` passed through
  unmodified — *not* rebuilt via ``build_receipt`` (which unconditionally folds a
  ``trace_id`` key into the value envelope for the live dual-write path). Historical
  classification-path rows never carried a ``trace_id`` in their value envelope;
  injecting one on export would (a) misrepresent the historical record and (b) break
  idempotency, since the tuple used to detect "already exported" would then only
  match the mutated shape, not the original DB row, on every subsequent run.
- **Fails loud, never skips, on an unexportable row.** A DB row missing a ``key``,
  ``object_id``, or a real ``created_at`` timestamp raises :class:`DecisionExportError`
  and aborts the run (any rows already appended earlier in the same run stay — the
  export is not transactional across rows, but is idempotent, so a fixed re-run
  picks up exactly where it left off). This differs deliberately from
  ``rebuild_decisions_projection``'s orphan-skip behavior: an orphan skipped by the
  rebuild is still recoverable from the log; a row this export cannot faithfully
  place into the log is about to become unrecoverable the moment a rebuild
  truncates the table it currently lives in only.

Known, pre-existing, out-of-scope gap (not introduced or fixed here): the
``decisions`` table also carries ``agent``/``kind`` columns (deprecated
``PgDecisions.put`` path) that receipt schema v1 does not carry and
``rebuild_decisions_projection`` does not restore on replay. That gap predates this
slice (slice 2) and applies to every decision row, not just the historical ones this
export targets; it is not part of the #2973 acceptance criteria.

**Not executed against prod by this module.** This function is available to be run;
the operator-gated one-off run itself (plus verify-counts, flip-canonical, and the
backup-scope doc update) is the remainder of slice 4 and stays gated on operator ack
per the issue.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.db.db import conn_rw
from app.instance.binding_ids import COMPATIBILITY_BINDING_ID
from app.receipts.decision_receipt_log import (
    RECEIPT_WRITE_ACTION,
    SCHEMA_VERSION,
    _write_receipt_line,
    iter_decision_receipts,
    resolve_vault_uuid,
)
from app.write_guard import DEFAULT_WRITE_GUARD


class DecisionExportError(RuntimeError):
    """Raised when a ``decisions`` row cannot be faithfully exported to the log.

    Raised instead of skipping so an unexportable row is understood and fixed
    before ``rebuild_decisions_projection()`` can ever run and lose it.
    """


@dataclass
class ExportSummary:
    total_db_rows: int = 0
    already_in_log: int = 0
    exported: int = 0
    exported_rows: list[dict[str, Any]] = field(default_factory=list)


def _created_at_iso(value: datetime) -> str:
    dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _created_at_iso_from_raw(raw: Any) -> str:
    if isinstance(raw, datetime):
        return _created_at_iso(raw)
    if not isinstance(raw, str) or not raw:
        return ""
    text = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return ""
    return _created_at_iso(parsed)


def _value_json(value: Any) -> str:
    if isinstance(value, dict):
        parsed = value
    elif value:
        parsed = json.loads(value)
    else:
        parsed = {}
    return json.dumps(parsed or {}, sort_keys=True)


def _db_rows() -> list[dict[str, Any]]:
    """Every row currently in the ``decisions`` projection table, raw (no re-linking)."""
    rows: list[dict[str, Any]] = []
    with conn_rw() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, object_id, key, value, created_at FROM decisions "
                "WHERE vault_binding_id = %s ORDER BY created_at",
                (COMPATIBILITY_BINDING_ID,),
            )
            for r in cur.fetchall():
                row_id = r["id"] if isinstance(r, dict) else r[0]
                object_id = r["object_id"] if isinstance(r, dict) else r[1]
                key = r["key"] if isinstance(r, dict) else r[2]
                value = r["value"] if isinstance(r, dict) else r[3]
                created_at = r["created_at"] if isinstance(r, dict) else r[4]
                rows.append(
                    {
                        "id": str(row_id) if row_id is not None else None,
                        "object_id": str(object_id) if object_id is not None else None,
                        "key": key,
                        "value": value,
                        "created_at": created_at,
                    }
                )
    return rows


def _existing_log_keys(vault_root: Path | None) -> set[tuple[str, str, str, str]]:
    """``(object_id, key, created_at_iso, value_json)`` tuples already in the log.

    Same tuple domain ``doctor_decisions_projection`` compares between the log and
    the DB — a DB row whose tuple is already in this set has already been exported.
    """
    keys: set[tuple[str, str, str, str]] = set()
    for receipt in iter_decision_receipts(vault_root):
        key = receipt.get("key")
        if not key:
            continue
        object_id = receipt.get("object_id")
        keys.add(
            (
                str(object_id) if object_id is not None else "",
                str(key),
                _created_at_iso_from_raw(receipt.get("created_at")),
                _value_json(receipt.get("value")),
            )
        )
    return keys


def export_decisions_to_receipt_log(vault_root: Path | None = None) -> ExportSummary:
    """One-time export of ``decisions`` rows that exist only in Postgres into the
    canonical receipt log. See module docstring for the full contract
    (read-only over the DB, idempotent, faithful value passthrough, fail-loud).
    """
    # WriteGuard at the seam (C-6), same token the live receipt writer asserts —
    # a blocked runtime cannot begin this write either.
    DEFAULT_WRITE_GUARD.assert_writes_allowed(RECEIPT_WRITE_ACTION)

    db_rows = _db_rows()
    existing = _existing_log_keys(vault_root)
    summary = ExportSummary(total_db_rows=len(db_rows))

    for row in db_rows:
        key = row.get("key")
        if not key:
            raise DecisionExportError(
                f"decisions row id={row.get('id')} has no key; cannot export faithfully"
            )
        object_id = row.get("object_id")
        if object_id is None:
            raise DecisionExportError(
                f"decisions row id={row.get('id')} key={key} has no object_id; "
                "cannot export faithfully"
            )
        created_at = row.get("created_at")
        if not isinstance(created_at, datetime):
            raise DecisionExportError(
                f"decisions row id={row.get('id')} key={key} has no usable created_at; "
                "cannot export faithfully"
            )

        raw_value = row.get("value")
        value = raw_value if isinstance(raw_value, dict) else json.loads(raw_value or "{}")

        dedupe_key = (
            str(object_id),
            str(key),
            _created_at_iso(created_at),
            _value_json(value),
        )
        if dedupe_key in existing:
            summary.already_in_log += 1
            continue

        vault_uuid = resolve_vault_uuid(str(object_id))
        record = {
            "schema_version": SCHEMA_VERSION,
            "object_id": str(object_id),
            "vault_uuid": vault_uuid,
            "key": str(key),
            # Exact passthrough — no trace_id folding. See module docstring:
            # `build_receipt` unconditionally injects a `trace_id` key into the
            # value envelope, which would misrepresent historical rows that never
            # carried one and would break idempotency on re-run.
            "value": value,
            "created_at": _created_at_iso(created_at),
        }
        _write_receipt_line(record, created_at, vault_root)

        existing.add(dedupe_key)
        summary.exported += 1
        summary.exported_rows.append(
            {"object_id": str(object_id), "key": str(key), "created_at": record["created_at"]}
        )

    return summary


__all__ = ["DecisionExportError", "ExportSummary", "export_decisions_to_receipt_log"]
