from __future__ import annotations

import fcntl
import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
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


def _write_status(
    run_at: datetime,
    ok: bool,
    error_message: str | None,
    binding_run: tuple[str, str] | None = None,
) -> None:
    """Rewrite the status file under an inter-process lock, atomically.

    ``binding_run`` is ``(binding id, plane)`` of the run just recorded. The
    per-binding map is read, merged and replaced inside one lock, so concurrent
    producers (API and watcher share the file) never drop each other's history,
    and a run with no provable binding keeps the existing map.
    """
    path = _status_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict = {
        "last_run_at": run_at.isoformat(),
        "last_run_ok": ok,
        "last_error_message": error_message,
        "runs": {plane: _serialize_run(meta) for plane, meta in _last_runs.items()},
    }
    with _status_lock(path):
        bindings = _read_binding_runs(path)
        if binding_run is not None:
            binding_id, plane = binding_run
            previous = bindings.get(binding_id) or {}
            bindings[binding_id] = {
                "last_run_at": run_at.isoformat(),
                "last_run_ok": ok,
                "last_error_message": error_message,
                "runs": {
                    **(previous.get("runs") or {}),
                    plane: _serialize_run(_last_runs[plane]),
                },
            }
        if bindings:
            payload["bindings"] = bindings
        tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)


@contextmanager
def _status_lock(path: Path) -> Iterator[None]:
    with open(path.with_name(f".{path.name}.lock"), "a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _read_binding_runs(path: Path) -> dict[str, dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    bindings = data.get("bindings") if isinstance(data, dict) else None
    return dict(bindings) if isinstance(bindings, dict) else {}


def _read_status() -> Tuple[datetime | None, bool | None, str | None, dict[str, dict]]:
    path = _status_path()
    if not path.exists():
        return None, None, None, {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None, None, None, {}
    return _parse_status(data)


def _parse_status(data: object) -> Tuple[datetime | None, bool | None, str | None, dict[str, dict]]:
    if not isinstance(data, dict):
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


def record_ingest_success(
    dt: Optional[datetime] = None, *, vault_binding_id: str | None = None
) -> None:
    record_ingest_run(
        "vault",
        scanned=0,
        ingested=0,
        errors=0,
        malformed=0,
        dt=dt,
        ok=True,
        message=None,
        vault_binding_id=vault_binding_id,
    )


def record_ingest_failure(
    dt: Optional[datetime], message: str, *, vault_binding_id: str | None = None
) -> None:
    record_ingest_run(
        "vault",
        scanned=0,
        ingested=0,
        errors=1,
        malformed=0,
        dt=dt,
        ok=False,
        message=message,
        vault_binding_id=vault_binding_id,
    )


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
    vault_binding_id: str | None = None,
) -> None:
    """Record one ingest run, process-wide and under its producing binding (MVR-05B4c4).

    ``vault_binding_id`` is the binding the producer proved it ingested; when omitted
    the live compatibility binding is stamped. An unprovable binding (or an explicit
    empty id from a root-handed producer that could not prove its root) records the
    run process-wide only, so a scoped read never sees a misattributed run.
    """
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
    binding_id = vault_binding_id if vault_binding_id is not None else _producing_binding()
    _write_status(run_at, ok_value, message, (binding_id, plane) if binding_id else None)


def _serialize_run(meta: dict) -> dict:
    return {
        "last_run_at": meta.get("last_run_at").isoformat() if meta.get("last_run_at") else None,
        "last_run_ok": meta.get("last_run_ok"),
        "scanned": meta.get("scanned"),
        "ingested": meta.get("ingested"),
        "errors": meta.get("errors"),
        "malformed": meta.get("malformed"),
    }


def _producing_binding() -> str | None:
    from app.instance.compatibility_binding import (
        CompatibilityBindingUnavailableError,
        live_compatibility_binding_id,
    )

    try:
        return live_compatibility_binding_id()
    except CompatibilityBindingUnavailableError:
        return None


def ingest_binding_for_root(root: Path) -> str | None:
    """The binding a root-handed ingest producer proves, or ``None`` when unprovable."""

    from app.instance.compatibility_binding import (
        CompatibilityBindingUnavailableError,
        compatibility_binding_for_root,
    )

    try:
        return compatibility_binding_for_root(root)
    except CompatibilityBindingUnavailableError:
        return None


def get_ingest_meta() -> Tuple[datetime | None, bool | None, str | None]:
    _ensure_loaded()
    return _last_ingest_run_at, _last_ingest_run_ok, _last_ingest_error_message


def get_ingest_status_for_binding(vault_binding_id: str) -> IngestionStatus:
    """Ingest status of one binding's stamped runs only; read-only (MVR-05B4c4).

    Runs recorded before binding stamping are never adopted into a binding.
    """

    entry = _read_binding_runs(_status_path()).get(vault_binding_id)
    last_run_at, last_run_ok, last_error_message, runs = _parse_status(entry or {})
    return _ingestion_status(last_run_at, last_run_ok, last_error_message, runs)


def get_ingest_status() -> IngestionStatus:
    _ensure_loaded()
    return _ingestion_status(
        _last_ingest_run_at, _last_ingest_run_ok, _last_ingest_error_message, _last_runs
    )


def _ingestion_status(
    last_run_at: datetime | None,
    last_run_ok: bool | None,
    last_error_message: str | None,
    runs: dict[str, dict],
) -> IngestionStatus:
    planes = []
    total_scanned = total_ingested = total_errors = total_malformed = 0
    for plane, meta in runs.items():
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
    "get_ingest_status_for_binding",
    "ingest_binding_for_root",
    "get_ingest_meta",
    "get_ingest_status",
    "reset_ingest_meta",
]
