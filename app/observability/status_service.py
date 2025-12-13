from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Iterable

from app.observability.ingest_meta import get_ingest_status
from app.observability.status_model import AskStatus, IngestionStatus, StoreStatus, SystemStatus
from app.stores import get_object_store
from app.version import SOT_BASELINE, SOT_FORWARD, SOT_LABEL, get_sot_version, get_sot_metadata

_ASK_LATENCIES: list[tuple[float, float]] = []
_ASK_ERRORS: list[float] = []
_ASK_WINDOW = timedelta(hours=24)


def record_ask_query(latency_ms: float) -> None:
    now = time.time()
    _ASK_LATENCIES.append((now, latency_ms))
    _prune_ask_metrics(now)


def record_ask_error() -> None:
    now = time.time()
    _ASK_ERRORS.append(now)
    _prune_ask_metrics(now)


def _prune_ask_metrics(now: float | None = None) -> None:
    if now is None:
        now = time.time()
    cutoff = now - _ASK_WINDOW.total_seconds()
    while _ASK_LATENCIES and _ASK_LATENCIES[0][0] < cutoff:
        _ASK_LATENCIES.pop(0)
    while _ASK_ERRORS and _ASK_ERRORS[0] < cutoff:
        _ASK_ERRORS.pop(0)


def reset_ask_metrics() -> None:
    _ASK_LATENCIES.clear()
    _ASK_ERRORS.clear()


def _iter_object_records(store) -> Iterable[dict]:
    seen: set[str] = set()
    records: list[dict] = []

    if hasattr(store, "_objects"):
        objs = getattr(store, "_objects")
        if isinstance(objs, dict):
            for rec in objs.values():
                oid = str(rec.get("object_id") or rec.get("id") or "")
                if oid:
                    seen.add(oid)
                records.append(rec)

    try:
        from app.stores.pg import _connect  # type: ignore
    except Exception:
        return records

    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT object_id, payload, source_ref FROM store_objects")
                rows = cur.fetchall()
        for row in rows or []:
            oid = str(row.get("object_id") or "")
            if oid and oid in seen:
                continue
            records.append({"object_id": oid, "payload": row.get("payload") or {}, "source_ref": row.get("source_ref")})
            if oid:
                seen.add(oid)
    except Exception:
        return records

    return records


def _classify_plane(record: dict) -> str:
    payload = record.get("payload") or {}
    plane = str(payload.get("plane") or "").lower()
    if plane:
        return plane
    origin = str(payload.get("origin") or payload.get("source") or payload.get("source_ref") or "").lower()
    if origin.startswith("external"):
        return "external"
    return "vault"


def get_store_status() -> list[StoreStatus]:
    store = get_object_store()
    counts = {"vault": 0, "external": 0}
    for record in _iter_object_records(store):
        plane = _classify_plane(record)
        counts[plane] = counts.get(plane, 0) + 1
    ingestion = get_ingestion_status()
    plane_meta = {p.plane: p for p in getattr(ingestion, "planes", [])}
    planes = sorted(set(counts.keys()) | set(plane_meta.keys()))
    statuses: list[StoreStatus] = []
    for plane in planes:
        meta = plane_meta.get(plane)
        statuses.append(
            StoreStatus(
                name=plane,
                object_count=counts.get(plane, 0),
                last_ingest_at=meta.last_run_at if meta else None,
                last_error_at=meta.last_run_at if meta and meta.last_run_ok is False else None,
            )
        )
    return statuses


def get_ingestion_status() -> IngestionStatus:
    return get_ingest_status()


def get_ask_status() -> AskStatus:
    now = time.time()
    _prune_ask_metrics(now)
    if not _ASK_LATENCIES:
        return AskStatus(total_queries_24h=0, avg_latency_ms_24h=None, error_count_24h=len(_ASK_ERRORS))
    total = len(_ASK_LATENCIES)
    avg_ms = sum(lat for _, lat in _ASK_LATENCIES) / total
    return AskStatus(total_queries_24h=total, avg_latency_ms_24h=avg_ms, error_count_24h=len(_ASK_ERRORS))


def get_system_status() -> SystemStatus:
    sot_meta = get_sot_metadata()
    return SystemStatus(
        timestamp=datetime.now(timezone.utc),
        sot_version=get_sot_version(),
        sot_baseline_version=sot_meta["baseline"],
        sot_forward_line_version=sot_meta["forward_line"],
        sot_label=sot_meta["label"],
        stores=get_store_status(),
        ingestion=get_ingestion_status(),
        ask=get_ask_status(),
    )


__all__ = [
    "get_system_status",
    "get_store_status",
    "get_ingestion_status",
    "get_ask_status",
    "record_ask_query",
    "record_ask_error",
    "reset_ask_metrics",
]
