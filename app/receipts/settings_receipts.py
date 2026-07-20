"""Typed read-only settings-write receipt query projection.

Mirrors ``app/receipts/promotion_receipts.py`` for the ``settings.write.receipt`` topic
(#2787, RESEARCH-01 divergence D-1). ``SettingsWriteReceipt`` (``app/vault/settings_service.py``)
is the in-memory return value; this module is the durable, queryable projection over the same
receipt data once it has been emitted to the outbox.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from app.events.types import SETTINGS_WRITE_RECEIPT
from app.receipts.outbox_sources import (
    first_str,
    read_receipt_source_records,
    record_event,
    record_payload,
)


@dataclass(frozen=True)
class SettingsReceiptQuery:
    key: str | None = None
    surface: str | None = None
    actor: str | None = None
    is_runtime_gating: bool | None = None
    vault_id: str | None = None
    local_instance_id: str | None = None


@dataclass(frozen=True)
class SettingsReceiptRow:
    event_id: str | None
    trace_id: str | None
    timestamp: str
    key: str
    value: Any
    old_value: Any
    new_value: Any
    file: str | None
    surface: str | None
    actor: str | None
    is_runtime_gating: bool
    operation_id: str | None
    vault_id: str | None
    local_instance_id: str | None


@dataclass(frozen=True)
class SettingsReceiptQueryResult:
    source_available: bool
    rows: tuple[SettingsReceiptRow, ...] = ()
    non_authoritative_records: tuple[dict[str, str | None], ...] = field(default_factory=tuple)


def query_settings_receipts(
    query: SettingsReceiptQuery | None = None,
    *,
    vault_root: Path | None = None,
    outbox_path: Path | None = None,
    records: Iterable[dict[str, Any]] | None = None,
    require_operation_id: bool = False,
    durable_append_order: bool = False,
) -> SettingsReceiptQueryResult:
    """Return typed settings-write receipt rows derived from durable outbox records.

    ``vault_root`` is accepted for signature symmetry with ``query_promotion_receipts``
    (settings receipts carry no vault-relative path to normalize today) and is currently
    unused.
    """

    del vault_root  # unused today; kept for projection-reader signature symmetry
    source_records: list[dict[str, Any]] | None
    if records is not None:
        source_records = list(records)
    elif durable_append_order:
        source_records = _read_durable_jsonl_records(outbox_path=outbox_path)
    else:
        source_records = read_receipt_source_records(outbox_path=outbox_path)
    if source_records is None:
        return SettingsReceiptQueryResult(source_available=False)

    filters = query or SettingsReceiptQuery()
    projected_rows: list[SettingsReceiptRow] = []
    rows_by_operation: dict[str, SettingsReceiptRow] = {}
    invalid_operations: set[str] = set()
    non_authoritative: list[dict[str, str | None]] = []
    for record in source_records:
        event = record_event(record)
        if event != SETTINGS_WRITE_RECEIPT:
            continue
        row, reason = _project_settings_receipt(record)
        if row is None:
            non_authoritative.append({
                "event_id": first_str(record.get("event_id")),
                "trace_id": first_str(record.get("trace_id")),
                "reason": reason,
            })
            continue
        if require_operation_id and not row.operation_id:
            non_authoritative.append(
                {
                    "event_id": row.event_id,
                    "trace_id": row.trace_id,
                    "reason": "missing_operation_id",
                }
            )
            continue
        if row.operation_id:
            prior = rows_by_operation.get(row.operation_id)
            if prior is not None:
                if not _same_operation_payload(prior, row):
                    invalid_operations.add(row.operation_id)
                continue
            rows_by_operation[row.operation_id] = row
        projected_rows.append(row)

    for operation_id in sorted(invalid_operations):
        prior = rows_by_operation[operation_id]
        non_authoritative.append(
            {
                "event_id": prior.event_id,
                "trace_id": prior.trace_id,
                "reason": "operation_id_collision",
            }
        )
    rows = [
        row
        for row in projected_rows
        if row.operation_id not in invalid_operations and _matches(row, filters)
    ]
    if not durable_append_order:
        rows.sort(key=lambda row: row.timestamp)
    return SettingsReceiptQueryResult(
        source_available=True,
        rows=tuple(rows),
        non_authoritative_records=tuple(non_authoritative),
    )


def _project_settings_receipt(record: dict[str, Any]) -> tuple[SettingsReceiptRow | None, str]:
    payload = record_payload(record)
    key = first_str(payload.get("key"))
    if not key:
        return None, "missing_key"
    if "surface" not in payload and "actor" not in payload:
        return None, "missing_actor_and_surface"

    timestamp = first_str(payload.get("timestamp"), record.get("timestamp"), record.get("created_at"))
    if not timestamp:
        return None, "missing_timestamp"

    return (
        SettingsReceiptRow(
            event_id=first_str(record.get("event_id")),
            trace_id=first_str(record.get("trace_id")),
            timestamp=timestamp,
            key=key,
            value=payload.get("value"),
            old_value=payload.get("old_value"),
            new_value=payload.get("new_value", payload.get("value")),
            file=first_str(payload.get("file")),
            surface=first_str(payload.get("surface")),
            actor=first_str(payload.get("actor")),
            is_runtime_gating=bool(payload.get("is_runtime_gating", False)),
            operation_id=first_str(payload.get("operation_id")),
            vault_id=first_str(payload.get("vault_id")),
            local_instance_id=first_str(payload.get("local_instance_id")),
        ),
        "",
    )


def _matches(row: SettingsReceiptRow, query: SettingsReceiptQuery) -> bool:
    if query.key and query.key != row.key:
        return False
    if query.surface and query.surface != row.surface:
        return False
    if query.actor and query.actor != row.actor:
        return False
    if query.is_runtime_gating is not None and query.is_runtime_gating != row.is_runtime_gating:
        return False
    if query.vault_id and query.vault_id != row.vault_id:
        return False
    if query.local_instance_id and query.local_instance_id != row.local_instance_id:
        return False
    return True


def _same_operation_payload(
    left: SettingsReceiptRow, right: SettingsReceiptRow
) -> bool:
    return (
        left.timestamp == right.timestamp
        and left.key == right.key
        and left.value == right.value
        and left.old_value == right.old_value
        and left.new_value == right.new_value
        and left.file == right.file
        and left.surface == right.surface
        and left.actor == right.actor
        and left.is_runtime_gating == right.is_runtime_gating
        and left.operation_id == right.operation_id
        and left.vault_id == right.vault_id
        and left.local_instance_id == right.local_instance_id
    )


def _read_durable_jsonl_records(
    *, outbox_path: Path | None
) -> list[dict[str, Any]] | None:
    if outbox_path is None:
        from app.outbox.events import get_index_outbox_path  # noqa: PLC0415

        resolved = get_index_outbox_path()
    else:
        resolved = Path(outbox_path).expanduser()
    if not resolved.exists() or not resolved.is_file():
        return None
    records: list[dict[str, Any]] = []
    with resolved.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                records.append(record)
    return records


__all__ = [
    "SettingsReceiptQuery",
    "SettingsReceiptQueryResult",
    "SettingsReceiptRow",
    "query_settings_receipts",
]
