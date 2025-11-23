from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

from app.observability.status_model import IngestionStatus

_last_ingest_run_at: datetime | None = None
_last_ingest_run_ok: bool | None = None
_last_ingest_error_message: str | None = None


def _status_path() -> Path:
    raw = os.getenv("INGEST_STATUS_PATH")
    return Path(raw).expanduser() if raw else Path("tmp/ingest_status.json")


def _write_status(run_at: datetime, ok: bool, error_message: str | None) -> None:
    path = _status_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "last_run_at": run_at.isoformat(),
        "last_run_ok": ok,
        "last_error_message": error_message,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _read_status() -> Tuple[datetime | None, bool | None, str | None]:
    path = _status_path()
    if not path.exists():
        return None, None, None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None, None, None
    last_run_at = data.get("last_run_at")
    try:
        parsed = datetime.fromisoformat(last_run_at) if last_run_at else None
    except Exception:
        parsed = None
    return parsed, data.get("last_run_ok"), data.get("last_error_message")


def _ensure_loaded() -> None:
    global _last_ingest_run_at, _last_ingest_run_ok, _last_ingest_error_message
    if _last_ingest_run_at is not None or _last_ingest_run_ok is not None or _last_ingest_error_message is not None:
        return
    _last_ingest_run_at, _last_ingest_run_ok, _last_ingest_error_message = _read_status()


def record_ingest_success(dt: Optional[datetime] = None) -> None:
    global _last_ingest_run_at, _last_ingest_run_ok, _last_ingest_error_message
    _last_ingest_run_at = dt or datetime.now(timezone.utc)
    _last_ingest_run_ok = True
    _last_ingest_error_message = None
    _write_status(_last_ingest_run_at, True, None)


def record_ingest_failure(dt: Optional[datetime], message: str) -> None:
    global _last_ingest_run_at, _last_ingest_run_ok, _last_ingest_error_message
    _last_ingest_run_at = dt or datetime.now(timezone.utc)
    _last_ingest_run_ok = False
    _last_ingest_error_message = message
    _write_status(_last_ingest_run_at, False, message)


def get_ingest_meta() -> Tuple[datetime | None, bool | None, str | None]:
    _ensure_loaded()
    return _last_ingest_run_at, _last_ingest_run_ok, _last_ingest_error_message


def get_ingest_status() -> IngestionStatus:
    last_run_at, last_run_ok, last_error_message = get_ingest_meta()
    return IngestionStatus(
        last_run_at=last_run_at,
        last_run_ok=last_run_ok,
        last_error_message=last_error_message,
    )


def reset_ingest_meta() -> None:
    global _last_ingest_run_at, _last_ingest_run_ok, _last_ingest_error_message
    _last_ingest_run_at = None
    _last_ingest_run_ok = None
    _last_ingest_error_message = None


__all__ = [
    "record_ingest_success",
    "record_ingest_failure",
    "get_ingest_meta",
    "get_ingest_status",
    "reset_ingest_meta",
]
