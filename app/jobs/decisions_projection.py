"""Rebuild the ``decisions`` Postgres projection from the canonical receipt log.

Spec: ``docs/DECISION_RECEIPT_LOG/README.md`` (feat #2969, slice 2).

The decision-receipt log (``app/receipts/decision_receipt_log.py``) is the canonical
judgment record; the ``decisions`` table is a rebuildable projection index over it
(KERNEL-05 / ARCHITECTURAL_CONSTITUTION C-4). This module:

- ``rebuild_decisions_projection()`` — truncate the ``decisions`` table and replay every
  JSONL receipt (all shards, ordered by ``created_at``) back into it. It re-links each
  receipt's runtime ``object_id`` when the DB was rebuilt and ids were re-minted: if the
  receipt's ``object_id`` is no longer a current ``store_objects.object_id`` but its
  ``vault_uuid`` resolves to a canonical object identity, the row is re-linked
  (the §5 identity-decoupling payoff).
- ``doctor_decisions_projection()`` — assert the DB projection equals the log row-for-row
  on ``(object_id, key, created_at, value)`` (verify-the-verifier). Returns a structured
  report; ``ok`` is ``True`` only when they match.

Both operate on the durable Postgres path only (they are meaningless under the volatile
``STORE_BACKEND=memory`` opt-in, which keeps no durable receipt log).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.db.db import conn_rw
from app.db.decisions_schema import assert_decisions_schema
from app.receipts.decision_receipt_log import iter_decision_receipts


@dataclass
class RebuildSummary:
    total_receipts: int = 0
    inserted: int = 0
    relinked: int = 0
    skipped_orphans: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class DoctorReport:
    ok: bool
    db_rows: int
    log_rows: int
    missing_in_db: list[dict[str, Any]] = field(default_factory=list)
    extra_in_db: list[dict[str, Any]] = field(default_factory=list)


def _parse_ts(raw: Any) -> datetime | None:
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    if not isinstance(raw, str) or not raw:
        return None
    text = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _existing_object_ids(cur) -> set[str]:
    cur.execute("SELECT object_id FROM store_objects")
    return {str(r["object_id"] if isinstance(r, dict) else r[0]) for r in cur.fetchall()}


def _uuid_to_id_map(cur) -> dict[str, str]:
    cur.execute(
        """
        SELECT canonical.object_id,
               COALESCE(legacy.uuid, canonical.object_id) AS vault_uuid
        FROM store_objects canonical
        LEFT JOIN objects legacy ON legacy.id = canonical.object_id
        """
    )
    out: dict[str, str] = {}
    for r in cur.fetchall():
        rid = str(r["object_id"] if isinstance(r, dict) else r[0])
        ruuid = r["vault_uuid"] if isinstance(r, dict) else r[1]
        out[str(ruuid)] = rid
    return out


def _resolve_target_object_id(
    receipt: dict[str, Any],
    existing_ids: set[str],
    uuid_to_id: dict[str, str],
) -> str | None:
    """Return the current ``objects.id`` this receipt should link to, or None.

    Priority: the receipt's own ``object_id`` if it still exists; otherwise the
    object whose ``objects.uuid`` matches the receipt's ``vault_uuid`` (re-link
    after id re-minting). ``None`` when neither resolves — a genuine orphan that
    cannot satisfy the ``decisions.object_id`` FK.
    """
    object_id = receipt.get("object_id")
    if object_id is not None and str(object_id) in existing_ids:
        return str(object_id)
    vault_uuid = receipt.get("vault_uuid")
    if vault_uuid is not None and str(vault_uuid) in uuid_to_id:
        return uuid_to_id[str(vault_uuid)]
    return None


def rebuild_decisions_projection(vault_root: Path | None = None) -> RebuildSummary:
    """Truncate and repopulate the ``decisions`` table from the receipt log.

    Runs in one transaction: the truncate and every replayed insert commit
    together, so a failure mid-replay leaves the prior projection intact.
    """
    receipts = iter_decision_receipts(vault_root)
    summary = RebuildSummary(total_receipts=len(receipts))

    with conn_rw() as conn:
        with conn.cursor() as cur:
            assert_decisions_schema(conn)
            existing_ids = _existing_object_ids(cur)
            uuid_to_id = _uuid_to_id_map(cur)

            cur.execute("TRUNCATE TABLE decisions")

            for receipt in receipts:
                key = receipt.get("key")
                if not key:
                    summary.skipped_orphans.append(
                        {"reason": "missing_key", "receipt": receipt}
                    )
                    continue
                target_id = _resolve_target_object_id(receipt, existing_ids, uuid_to_id)
                if target_id is None:
                    summary.skipped_orphans.append(
                        {
                            "reason": "unresolved_object",
                            "object_id": receipt.get("object_id"),
                            "vault_uuid": receipt.get("vault_uuid"),
                            "key": key,
                        }
                    )
                    continue
                if str(receipt.get("object_id")) != target_id:
                    summary.relinked += 1

                value = receipt.get("value") or {}
                created = _parse_ts(receipt.get("created_at")) or datetime.now(timezone.utc)
                cur.execute(
                    """
                    INSERT INTO decisions (object_id, key, value, created_at)
                    VALUES (%s, %s, %s::jsonb, %s)
                    """,
                    (target_id, key, json.dumps(value), created),
                )
                summary.inserted += 1

    return summary


def _log_projection_rows(vault_root: Path | None = None) -> list[tuple[str, str, str, str]]:
    """The comparable ``(object_id, key, created_at_iso, value_json)`` tuples the
    log implies for the projection — after re-linking, matching what a rebuild
    would have written. Orphaned receipts (no resolvable object) are excluded,
    because a rebuild cannot insert them either."""
    receipts = iter_decision_receipts(vault_root)
    rows: list[tuple[str, str, str, str]] = []
    with conn_rw() as conn:
        with conn.cursor() as cur:
            existing_ids = _existing_object_ids(cur)
            uuid_to_id = _uuid_to_id_map(cur)
    for receipt in receipts:
        key = receipt.get("key")
        if not key:
            continue
        target_id = _resolve_target_object_id(receipt, existing_ids, uuid_to_id)
        if target_id is None:
            continue
        created = _parse_ts(receipt.get("created_at"))
        created_iso = created.astimezone(timezone.utc).isoformat() if created else ""
        value_json = json.dumps(receipt.get("value") or {}, sort_keys=True)
        rows.append((target_id, str(key), created_iso, value_json))
    return sorted(rows)


def _db_projection_rows() -> list[tuple[str, str, str, str]]:
    rows: list[tuple[str, str, str, str]] = []
    with conn_rw() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT object_id, key, value, created_at FROM decisions")
            for r in cur.fetchall():
                object_id = str(r["object_id"] if isinstance(r, dict) else r[0])
                key = str(r["key"] if isinstance(r, dict) else r[1])
                raw_value = r["value"] if isinstance(r, dict) else r[2]
                value = raw_value if isinstance(raw_value, dict) else json.loads(raw_value)
                created = r["created_at"] if isinstance(r, dict) else r[3]
                created_iso = (
                    created.astimezone(timezone.utc).isoformat()
                    if isinstance(created, datetime)
                    else ""
                )
                value_json = json.dumps(value or {}, sort_keys=True)
                rows.append((object_id, key, created_iso, value_json))
    return sorted(rows)


def doctor_decisions_projection(vault_root: Path | None = None) -> DoctorReport:
    """Assert the DB projection matches the log row-for-row.

    Compares ``(object_id, key, created_at, value)``. ``ok`` is True only when
    the multiset of DB rows equals the multiset of (resolvable) log rows.
    """
    log_rows = _log_projection_rows(vault_root)
    db_rows = _db_projection_rows()

    from collections import Counter

    log_counter = Counter(log_rows)
    db_counter = Counter(db_rows)

    missing = list((log_counter - db_counter).elements())
    extra = list((db_counter - log_counter).elements())

    def _fmt(row: tuple[str, str, str, str]) -> dict[str, Any]:
        return {"object_id": row[0], "key": row[1], "created_at": row[2], "value": row[3]}

    return DoctorReport(
        ok=not missing and not extra,
        db_rows=len(db_rows),
        log_rows=len(log_rows),
        missing_in_db=[_fmt(r) for r in missing],
        extra_in_db=[_fmt(r) for r in extra],
    )


__all__ = [
    "DoctorReport",
    "RebuildSummary",
    "doctor_decisions_projection",
    "rebuild_decisions_projection",
]
