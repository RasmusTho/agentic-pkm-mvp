"""Read-only per-artifact receipt projection over governed outbox records."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from app.settings.watcher_settings import load_watcher_settings


@dataclass(frozen=True)
class ArtifactReceiptTarget:
    artifact_uuid: str | None
    note_path: str


_RECEIPT_SUPPORTING_EVENTS = {
    "panel.action.blocked",
    "panel.action.logged",
    "promotion.transition.applied",
}


def receipts_for_artifacts(
    targets: Iterable[ArtifactReceiptTarget],
    *,
    vault_root: Path,
    outbox_path: Path | None = None,
) -> dict[str, list[dict[str, str | None]]] | None:
    """Return receipt rows keyed by target note path.

    ``None`` means no receipt-supporting source is available, so callers should
    preserve the honest "unavailable" state. An empty list for a target means a
    source exists and no matching receipt was found.
    """

    target_list = list(targets)
    if not target_list:
        return {}

    records = _read_receipt_source_records(outbox_path=outbox_path)
    if records is None:
        return None

    path_targets = {_normalize_note_path(target.note_path, vault_root=vault_root): target for target in target_list}
    uuid_targets = {
        str(target.artifact_uuid).strip(): target
        for target in target_list
        if target.artifact_uuid and str(target.artifact_uuid).strip()
    }
    result: dict[str, list[dict[str, str | None]]] = {
        target.note_path: [] for target in target_list
    }
    seen: dict[str, set[str]] = {target.note_path: set() for target in target_list}

    for record in records:
        projected = _project_receipt_record(record, vault_root=vault_root)
        if projected is None:
            continue
        receipt, artifact_uuid, artifact_path = projected
        matched: set[str] = set()
        if artifact_uuid and artifact_uuid in uuid_targets:
            matched.add(uuid_targets[artifact_uuid].note_path)
        if artifact_path and artifact_path in path_targets:
            matched.add(path_targets[artifact_path].note_path)
        if not matched:
            continue
        receipt_id = str(receipt.get("receipt_id") or "")
        for note_path in matched:
            if receipt_id in seen[note_path]:
                continue
            result[note_path].append(dict(receipt))
            seen[note_path].add(receipt_id)

    for rows in result.values():
        rows.sort(key=lambda row: str(row.get("timestamp") or ""))
    return result


def _read_receipt_source_records(*, outbox_path: Path | None) -> list[dict[str, Any]] | None:
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
            record.setdefault("created_at", _coerce_timestamp(created_at))
            record.setdefault("timestamp", _coerce_timestamp(created_at))
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


def _project_receipt_record(
    record: dict[str, Any],
    *,
    vault_root: Path,
) -> tuple[dict[str, str | None], str | None, str | None] | None:
    event = _record_event(record)
    if event not in _RECEIPT_SUPPORTING_EVENTS:
        return None
    payload = _record_payload(record)
    artifact_uuid = _first_str(
        payload.get("artifact_uuid"),
        payload.get("note_uuid"),
        _nested(payload, "note", "uuid"),
        _nested(payload, "artifact_linkage", "note_uuid"),
    )
    artifact_path = _normalize_note_path(
        _first_str(
            payload.get("artifact_path"),
            payload.get("note_path"),
            payload.get("path"),
            _nested(payload, "note", "path"),
            _nested(payload, "artifact_linkage", "note_path"),
        ),
        vault_root=vault_root,
    )
    if not artifact_uuid and not artifact_path:
        return None

    status, state = _status_and_state(event, payload)
    trace_id = _first_str(record.get("trace_id"), payload.get("trace_id"))
    action_id = _first_str(
        payload.get("action_id"),
        payload.get("intent_event_id"),
        payload.get("source_event"),
        _nested(payload, "action", "id"),
        event,
    )
    timestamp = _first_str(record.get("timestamp"), record.get("created_at")) or ""
    receipt_id = _first_str(payload.get("receipt_id"), record.get("event_id"))
    if not receipt_id:
        receipt_id = f"{event}:{trace_id or 'no-trace'}:{artifact_uuid or artifact_path}:{timestamp}"

    receipt = {
        "receipt_id": receipt_id,
        "trace_id": trace_id,
        "action_id": action_id,
        "action_type": event,
        "artifact_uuid": artifact_uuid,
        "artifact_path": artifact_path,
        "path": artifact_path,
        "requested_by": _requested_by(record, payload),
        "approved_by": _first_str(payload.get("approved_by"), _nested(payload, "authority", "approved_by")),
        "status": status,
        "timestamp": timestamp,
        "state": state,
    }
    return receipt, artifact_uuid, artifact_path


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


def _record_event(record: dict[str, Any]) -> str:
    return str(record.get("event") or record.get("event_type") or record.get("topic") or "").strip()


def _record_payload(record: dict[str, Any]) -> dict[str, Any]:
    payload = record.get("payload")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _nested(data: dict[str, Any], *path: str) -> Any:
    current: Any = data
    for part in path:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _first_str(*values: Any) -> str | None:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _normalize_note_path(value: str | None, *, vault_root: Path) -> str | None:
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


def _status_and_state(event: str, payload: dict[str, Any]) -> tuple[str, str]:
    if event == "panel.action.blocked":
        return "blocked", "blocked"
    if event == "panel.action.logged":
        return _first_str(payload.get("status"), payload.get("outcome"), "logged") or "logged", "applied"
    raw = _first_str(
        _nested(payload, "outcome", "status"),
        payload.get("status"),
        payload.get("effect"),
        "applied",
    ) or "applied"
    if raw in {"applied", "queued", "blocked", "rejected", "failed"}:
        return raw, raw
    if raw == "ok":
        return raw, "applied"
    if raw == "failure":
        return raw, "failed"
    if raw == "degraded":
        return raw, "blocked"
    return raw, "applied"


def _requested_by(record: dict[str, Any], payload: dict[str, Any]) -> str | None:
    return _first_str(
        payload.get("requested_by"),
        _nested(payload, "authority", "requested_by"),
        _nested(payload, "authority", "component"),
        record.get("source"),
    )


def _coerce_timestamp(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    return str(value)


__all__ = ["ArtifactReceiptTarget", "receipts_for_artifacts"]
