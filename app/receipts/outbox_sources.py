"""Shared readers for receipt-supporting outbox records."""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from itertools import chain
from pathlib import Path
from typing import Any, Generator, Iterator

from app.settings.watcher_settings import load_watcher_settings


_DB_RECEIPT_BATCH_SIZE = 256


class ReceiptSourceUnavailableError(RuntimeError):
    """A configured DB receipt source failed before traversal completed."""


@dataclass(frozen=True)
class ReceiptSourceSnapshot:
    """Independently readable receipt records and any unavailable sources.

    This snapshot is for reconciliation paths that may accept a validated
    matching receipt from one durable sink. Callers must still fail closed if
    no matching receipt is found while a configured source is unavailable.
    """

    records: tuple[dict[str, Any], ...]
    unavailable_sources: tuple[str, ...]


@contextmanager
def open_receipt_source_records(
    *, outbox_path: Path | None = None,
) -> Iterator[Iterator[dict[str, Any]] | None]:
    """Open complete DB-before-JSONL traversal without retaining source history.

    ``None`` retains the unavailable-source meaning of the list adapter,
    including refusal when the configured DB cannot be read. A late DB failure
    raises ``ReceiptSourceUnavailableError`` so consumers discard their partial
    projection. JSONL corruption still raises its existing integrity error.
    Exiting the context closes cursors, connections, files and read locks even
    when a consumer stops early.
    """

    from app.services.outbox import iter_jsonl_outbox_records

    with _open_db_outbox_records() as db_records:
        if _db_outbox_configured() and db_records is None:
            yield None
            return
        resolved = _resolve_jsonl_outbox_path(outbox_path)
        jsonl_records = (
            iter_jsonl_outbox_records(resolved)
            if resolved is not None and resolved.exists() and resolved.is_file()
            else None
        )
        if db_records is None and jsonl_records is None:
            yield None
            return
        try:
            yield chain(db_records or (), jsonl_records or ())
        finally:
            if jsonl_records is not None:
                jsonl_records.close()


def read_receipt_source_records(*, outbox_path: Path | None = None) -> list[dict[str, Any]] | None:
    """Read receipt-supporting source records from configured durable/audit sources.

    ``None`` means no source is available. An empty list means a source is
    connected and contains no readable records. When the configured database
    source cannot be read, return ``None`` even if JSONL is readable: a
    partial view must not be treated as an empty authoritative source.
    """

    source_available = False
    records: list[dict[str, Any]] = []

    db_configured = _db_outbox_configured()
    db_records = _read_db_outbox_records()
    if db_configured and db_records is None:
        return None
    if db_records is not None:
        source_available = True
        records.extend(db_records)

    jsonl_records = _read_jsonl_outbox_records(outbox_path=outbox_path)
    if jsonl_records is not None:
        source_available = True
        records.extend(jsonl_records)

    return records if source_available else None


def read_receipt_source_snapshot(*, outbox_path: Path | None = None) -> ReceiptSourceSnapshot:
    """Read each receipt source independently for idempotent reconciliation.

    Unlike :func:`read_receipt_source_records`, this reports partial
    availability instead of discarding records from a healthy sink. It does
    not make a partial empty view authoritative: a caller may use matching
    records that are present, but must refuse to create a replacement receipt
    when an unavailable source might already contain it.
    """

    records: list[dict[str, Any]] = []
    unavailable_sources: list[str] = []

    if _db_outbox_configured():
        try:
            db_records = _read_db_outbox_records()
        except Exception:
            db_records = None
        if db_records is None:
            unavailable_sources.append("DB")
        else:
            records.extend(db_records)

    try:
        jsonl_records = _read_jsonl_outbox_records(outbox_path=outbox_path)
    except Exception:
        jsonl_records = None
        unavailable_sources.append("JSONL")
    else:
        if jsonl_records is not None:
            records.extend(jsonl_records)

    return ReceiptSourceSnapshot(
        records=tuple(records),
        unavailable_sources=tuple(unavailable_sources),
    )


def record_event(record: dict[str, Any]) -> str:
    return str(record.get("event") or record.get("event_type") or record.get("topic") or "").strip()


def record_payload(record: dict[str, Any]) -> dict[str, Any]:
    payload = record.get("payload")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return {}
    return dict(payload) if isinstance(payload, dict) else {}


def first_str(*values: Any) -> str | None:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def nested(data: dict[str, Any], *path: str) -> Any:
    current: Any = data
    for part in path:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def normalize_note_path(value: str | None, *, vault_root: Path) -> str | None:
    text = (value or "").strip()
    if not text:
        return None
    path = Path(text).expanduser()
    if path.is_absolute():
        try:
            return path.relative_to(vault_root).as_posix()
        except ValueError:
            return path.as_posix()
    return path.as_posix().removeprefix("./")


def record_source_label(record: dict[str, Any]) -> str | None:
    """Best-effort component/source label for a record.

    Different emitters shape the outbox ``source`` field differently: some
    write a plain string (``app.events.schema.make_outbox_event``), others
    write a nested object carrying ``component``/``name``/``trigger``
    (``app.events.panel.PanelEventSource``). Both shapes are read here so
    downstream display-field derivation (run labels) can key off a single
    normalized string regardless of emitter.
    """
    source = record.get("source")
    if isinstance(source, dict):
        return first_str(source.get("component"), source.get("name"), source.get("trigger"))
    return first_str(source)


def coerce_timestamp(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    return str(value)


def _read_db_outbox_records() -> list[dict[str, Any]] | None:
    """Compatibility adapter for callers whose result is complete source history."""

    with _open_db_outbox_records() as records:
        if records is None:
            return None
        try:
            return list(records)
        except ReceiptSourceUnavailableError:
            return None


@contextmanager
def _open_db_outbox_records() -> Iterator[Iterator[dict[str, Any]] | None]:
    if not _db_outbox_configured():
        yield None
        return
    conn = None
    try:
        from app.services import outbox as outbox_service

        conn = outbox_service._open_conn()
        # A normal psycopg cursor buffers its whole result client-side even
        # with fetchmany. This self-owned read-only transaction uses a server
        # cursor; close rolls back without issuing any source mutation.
        conn.autocommit = False
        conn.read_only = True
        cur = conn.cursor(name="receipt_source")
        cur.execute("select id, topic, payload, created_at from outbox order by created_at asc")
    except Exception:
        if conn is not None:
            _close_connection(conn)
        yield None
        return
    records = _iter_db_outbox_records(cur)
    try:
        yield records
    finally:
        records.close()
        try:
            cur.close()
        except Exception:
            pass
        _close_connection(conn)


def _close_connection(conn: Any) -> None:
    try:
        conn.close()
    except Exception:
        pass


def _iter_db_outbox_records(cur: Any) -> Generator[dict[str, Any], None, None]:
    while True:
        try:
            rows = cur.fetchmany(_DB_RECEIPT_BATCH_SIZE)
        except Exception as exc:
            raise ReceiptSourceUnavailableError("DB receipt traversal unavailable") from exc
        if not rows:
            return
        for row in rows:
            if isinstance(row, dict):
                row_id = row.get("id")
                topic = row.get("topic")
                payload = row.get("payload")
                created_at = row.get("created_at")
            else:
                row_id, topic, payload, created_at = row
            record = _coerce_record(payload)
            record.setdefault("event", topic)
            record.setdefault("event_type", topic)
            record.setdefault("event_id", str(row_id) if row_id is not None else "")
            if created_at is not None:
                record.setdefault("created_at", coerce_timestamp(created_at))
                record.setdefault("timestamp", coerce_timestamp(created_at))
            yield record


def _db_outbox_configured() -> bool:
    backend = (os.getenv("STORE_BACKEND") or "").strip().lower()
    return backend == "pg" or bool(os.getenv("DATABASE_URL") or os.getenv("DB_DSN"))


def _read_jsonl_outbox_records(*, outbox_path: Path | None) -> list[dict[str, Any]] | None:
    from app.services.outbox import iter_jsonl_outbox_records

    resolved = _resolve_jsonl_outbox_path(outbox_path)
    if resolved is None or not resolved.exists() or not resolved.is_file():
        return None
    return list(iter_jsonl_outbox_records(resolved))


def _resolve_jsonl_outbox_path(outbox_path: Path | None) -> Path | None:
    if outbox_path is not None:
        return Path(outbox_path).expanduser()
    env_path = (os.getenv("INDEX_OUTBOX_PATH") or "").strip()
    if env_path:
        return Path(env_path).expanduser()
    try:
        return load_watcher_settings().paths.index_outbox
    except Exception:
        return None


def _coerce_record(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return dict(parsed) if isinstance(parsed, dict) else {}
    return {}


__all__ = [
    "coerce_timestamp",
    "first_str",
    "nested",
    "normalize_note_path",
    "open_receipt_source_records",
    "ReceiptSourceUnavailableError",
    "read_receipt_source_records",
    "read_receipt_source_snapshot",
    "ReceiptSourceSnapshot",
    "record_event",
    "record_payload",
    "record_source_label",
]
