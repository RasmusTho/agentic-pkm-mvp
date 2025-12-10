from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

from app.observability.status_model import IngestionPlaneStatus, IngestionStatus

_last_ingest_run_at: datetime | None = None
_last_ingest_run_ok: bool | None = None
_last_ingest_error_message: str | None = None
_last_runs: dict[str, dict] = {}


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
        "runs": {
            plane: {
                "last_run_at": meta.get("last_run_at").isoformat() if meta.get("last_run_at") else None,
                "last_run_ok": meta.get("last_run_ok"),
                "scanned": meta.get("scanned"),
                "ingested": meta.get("ingested"),
                "errors": meta.get("errors"),
                "malformed": meta.get("malformed"),
            }
            for plane, meta in _last_runs.items()
        },
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _read_status() -> Tuple[datetime | None, bool | None, str | None, dict[str, dict]]:
    path = _status_path()
    if not path.exists():
        return None, None, None, {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None, None, None, {}
    last_run_at = data.get("last_run_at")
    try:
        parsed = datetime.fromisoformat(last_run_at) if last_run_at else None
    except Exception:
        parsed = None
    runs: dict[str, dict] = {}
    for plane, meta in (data.get("runs") or {}).items():
        try:
            run_at = datetime.fromisoformat(meta.get("last_run_at")) if meta.get("last_run_at") else None
        except Exception:
            run_at = None
        runs[plane] = {
            "last_run_at": run_at,
            "last_run_ok": meta.get("last_run_ok"),
            "scanned": meta.get("scanned"),
            "ingested": meta.get("ingested"),
            "errors": meta.get("errors"),
            "malformed": meta.get("malformed"),
        }
    return parsed, data.get("last_run_ok"), data.get("last_error_message"), runs


def _ensure_loaded() -> None:
    global _last_ingest_run_at, _last_ingest_run_ok, _last_ingest_error_message, _last_runs
    if (
        _last_ingest_run_at is not None
        or _last_ingest_run_ok is not None
        or _last_ingest_error_message is not None
        or _last_runs
    ):
        return
    _last_ingest_run_at, _last_ingest_run_ok, _last_ingest_error_message, _last_runs = _read_status()


def record_ingest_success(dt: Optional[datetime] = None) -> None:
    record_ingest_run("vault", scanned=0, ingested=0, errors=0, malformed=0, dt=dt, ok=True, message=None)


def record_ingest_failure(dt: Optional[datetime], message: str) -> None:
    record_ingest_run("vault", scanned=0, ingested=0, errors=1, malformed=0, dt=dt, ok=False, message=message)


def record_ingest_run(
    plane: str,
    *,
    scanned: int,
    ingested: int,
    errors: int,
    malformed: int = 0,
    dt: Optional[datetime] = None,
    ok: bool | None = None,
    message: str | None = None,
) -> None:
    global _last_ingest_run_at, _last_ingest_run_ok, _last_ingest_error_message, _last_runs
    run_at = dt or datetime.now(timezone.utc)
    ok_value = ok if ok is not None else errors == 0
    _last_ingest_run_at = run_at
    _last_ingest_run_ok = ok_value
    _last_ingest_error_message = message
    _last_runs[plane] = {
        "last_run_at": run_at,
        "last_run_ok": ok_value,
        "scanned": scanned,
        "ingested": ingested,
        "errors": errors,
        "malformed": malformed,
    }
    _write_status(run_at, ok_value, message)


def get_ingest_meta() -> Tuple[datetime | None, bool | None, str | None]:
    _ensure_loaded()
    return _last_ingest_run_at, _last_ingest_run_ok, _last_ingest_error_message


def get_ingest_status() -> IngestionStatus:
    _ensure_loaded()
    last_run_at, last_run_ok, last_error_message = _last_ingest_run_at, _last_ingest_run_ok, _last_ingest_error_message
    planes = []
    total_scanned = total_ingested = total_errors = total_malformed = 0
    for plane, meta in _last_runs.items():
        plane_status = IngestionPlaneStatus(
            plane=plane,
            last_run_at=meta.get("last_run_at"),
            last_run_ok=meta.get("last_run_ok"),
            scanned=meta.get("scanned"),
            ingested=meta.get("ingested"),
            errors=meta.get("errors"),
            malformed=meta.get("malformed"),
        )
        planes.append(plane_status)
        total_scanned += meta.get("scanned") or 0
        total_ingested += meta.get("ingested") or 0
        total_errors += meta.get("errors") or 0
        total_malformed += meta.get("malformed") or 0
    return IngestionStatus(
        last_run_at=last_run_at,
        last_run_ok=last_run_ok,
        last_error_message=last_error_message,
        total_scanned=total_scanned,
        total_ingested=total_ingested,
        total_errors=total_errors,
        total_malformed=total_malformed,
        planes=planes,
    )


def reset_ingest_meta() -> None:
    global _last_ingest_run_at, _last_ingest_run_ok, _last_ingest_error_message, _last_runs
    _last_ingest_run_at = None
    _last_ingest_run_ok = None
    _last_ingest_error_message = None
    _last_runs = {}
    try:
        _status_path().unlink()
    except FileNotFoundError:
        pass


__all__ = [
    "record_ingest_success",
    "record_ingest_failure",
    "record_ingest_run",
    "get_ingest_meta",
    "get_ingest_status",
    "reset_ingest_meta",
]
