"""Shared readers for receipt-supporting outbox records."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from app.settings.watcher_settings import load_watcher_settings


def read_receipt_source_records(*, outbox_path: Path | None = None) -> list[dict[str, Any]] | None:
    """Read receipt-supporting source records from configured durable/audit sources.

    ``None`` means no source is available. An empty list means a source is
    connected and contains no readable records.
    """

    source_available = False
    records: list[dict[str, Any]] = []

    db_records = _read_db_outbox_records()
    if db_records is not None:
        source_available = True
        records.extend(db_records)

    jsonl_records = _read_jsonl_outbox_records(outbox_path=outbox_path)
    if jsonl_records is not None:
        source_available = True
        records.extend(jsonl_records)

    return records if source_available else None


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


def coerce_timestamp(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    return str(value)


def _read_db_outbox_records() -> list[dict[str, Any]] | None:
    if not _db_outbox_configured():
        return None
    try:
        from app.services import outbox as outbox_service

        conn = outbox_service._open_conn()
    except Exception:
        return None
    try:
        cur = conn.cursor()
        cur.execute("select id, topic, payload, created_at from outbox order by created_at asc")
        rows = cur.fetchall() or []
    except Exception:
        return None
    finally:
        try:
            conn.close()
        except Exception:
            pass

    records: list[dict[str, Any]] = []
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
        records.append(record)
    return records


def _db_outbox_configured() -> bool:
    backend = (os.getenv("STORE_BACKEND") or "").strip().lower()
    return backend == "pg" or bool(os.getenv("DATABASE_URL") or os.getenv("DB_DSN"))


def _read_jsonl_outbox_records(*, outbox_path: Path | None) -> list[dict[str, Any]] | None:
    resolved = _resolve_jsonl_outbox_path(outbox_path)
    if resolved is None or not resolved.exists() or not resolved.is_file():
        return None
    records: list[dict[str, Any]] = []
    for line in resolved.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            records.append(parsed)
    return records


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
    "read_receipt_source_records",
    "record_event",
    "record_payload",
]
