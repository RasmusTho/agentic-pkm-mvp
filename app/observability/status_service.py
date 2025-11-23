from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Iterable

from app.observability.ingest_meta import get_ingest_status
from app.observability.status_model import AskStatus, IngestionStatus, StoreStatus, SystemStatus
from app.stores import get_object_store
from app.version import get_sot_version

_ASK_LATENCIES: list[tuple[float, float]] = []
_ASK_WINDOW = timedelta(hours=24)


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
    try:
        from app.stores.pg import PgObjectStore, _connect  # type: ignore
    except Exception:
        return []
    if isinstance(store, PgObjectStore):
        try:
            with _connect() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT payload FROM store_objects")
                    rows = cur.fetchall()
            return ({"payload": row.get("payload") or {}} for row in rows)
        except Exception:
            return []
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


def get_ingestion_status() -> IngestionStatus:
    return get_ingest_status()


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
        timestamp=datetime.now(timezone.utc),
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
