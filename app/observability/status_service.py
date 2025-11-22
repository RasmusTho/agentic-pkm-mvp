from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

from app.observability.status_model import AskStatus, IngestionStatus, StoreStatus, SystemStatus
from app.stores import get_object_store
from app.version import get_sot_version

_ASK_LATENCIES: list[tuple[float, float]] = []
_ASK_WINDOW = timedelta(hours=24)
_INGEST_STATUS_PATH = Path("tmp/ingest_status.json")


def record_ask_query(latency_ms: float) -> None:
    now = time.time()
    _ASK_LATENCIES.append((now, latency_ms))
    _prune_ask_metrics(now)


def _prune_ask_metrics(now: float | None = None) -> None:
    if now is None:
        now = time.time()
    cutoff = now - _ASK_WINDOW.total_seconds()
    while _ASK_LATENCIES and _ASK_LATENCIES[0][0] < cutoff:
        _ASK_LATENCIES.pop(0)


def _iter_object_records(store) -> Iterable[dict]:
    if hasattr(store, "_objects"):
        objs = getattr(store, "_objects")
        if isinstance(objs, dict):
            return objs.values()
    return []


def _classify_domain(record: dict) -> str:
    payload = record.get("payload") or {}
    origin = str(payload.get("origin") or payload.get("source") or payload.get("source_ref") or "").lower()
    if origin.startswith("external"):
        return "external"
    return "vault"


def get_store_status() -> list[StoreStatus]:
    store = get_object_store()
    counts = {"vault": 0, "external": 0}
    for record in _iter_object_records(store):
        domain = _classify_domain(record)
        counts[domain] = counts.get(domain, 0) + 1
    statuses = [
        StoreStatus(name="vault", object_count=counts.get("vault", 0)),
        StoreStatus(name="external", object_count=counts.get("external", 0)),
    ]
    return statuses


def _read_ingest_status() -> IngestionStatus:
    if not _INGEST_STATUS_PATH.exists():
        return IngestionStatus()
    try:
        data = json.loads(_INGEST_STATUS_PATH.read_text(encoding="utf-8"))
        last_run_at = data.get("last_run_at")
        last_error_at = data.get("last_error_at")
        return IngestionStatus(
            last_run_at=datetime.fromisoformat(last_run_at) if last_run_at else None,
            last_run_ok=data.get("last_run_ok"),
            last_error_message=data.get("last_error_message"),
        )
    except Exception:
        return IngestionStatus()


def get_ingestion_status() -> IngestionStatus:
    return _read_ingest_status()


def get_ask_status() -> AskStatus:
    now = time.time()
    _prune_ask_metrics(now)
    if not _ASK_LATENCIES:
        return AskStatus(total_queries_24h=0, avg_latency_ms_24h=None)
    total = len(_ASK_LATENCIES)
    avg_ms = sum(lat for _, lat in _ASK_LATENCIES) / total
    return AskStatus(total_queries_24h=total, avg_latency_ms_24h=avg_ms)


def get_system_status() -> SystemStatus:
    return SystemStatus(
        timestamp=datetime.utcnow(),
        sot_version=get_sot_version(),
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
]
