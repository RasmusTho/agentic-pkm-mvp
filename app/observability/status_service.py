from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from app.events.types import PROMOTE_INTENT_CREATED, PROMOTE_DONE
from app.observability.ingest_meta import get_ingest_status
from app.observability.status_model import (
    AskStatus,
    EventCounters,
    IngestionStatus,
    IntentStatus,
    OutboxLagStatus,
    StoreStatus,
    SystemStatus,
    WriteGuardStatus,
)
from app.outbox.events import INDEX_OUTBOX_PATH
from app.runtime.worker_heartbeat import resolve_worker_heartbeat_path
from app.stores import get_object_store
from app.version import SOT_FORWARD, get_sot_version, get_sot_metadata
from app.health_contract import DEFAULT_CONTRACT

_ASK_LATENCIES: list[tuple[float, float]] = []
_ASK_ERRORS: list[float] = []
_ASK_WINDOW = timedelta(hours=24)
_EVENT_WINDOW = timedelta(hours=24)
_ACTIVE_FEATURES = [
    "PanelAgent runtime (v5.0)",
    "Watcher snapshot/policy track (v5.1–v5.4)",
    "Config-driven panel action wiring",
]
_WATCHER_EVENT_NAMES = {"watcher.run", "watcher.run.completed"}


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


def _parse_timestamp(value: object) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            iso = value
            if iso.endswith("Z"):
                iso = iso[:-1] + "+00:00"
            return datetime.fromisoformat(iso)
        except Exception:
            return None
    return None


def _count_events(outbox_path: Path) -> EventCounters:
    panel_total = panel_recent = promote_total = promote_recent = watcher_total = watcher_recent = 0
    promotion_done_total = promotion_done_recent = 0
    source = str(outbox_path) if outbox_path else None
    cutoff = datetime.now(timezone.utc) - _EVENT_WINDOW
    try:
        with outbox_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except Exception:
                    continue
                event = record.get("event") or record.get("event_type") or record.get("topic") or ""
                ts = _parse_timestamp(record.get("timestamp") or record.get("created_at"))
                is_recent = ts is not None and ts >= cutoff
                if event == "panel.intent.executed":
                    panel_total += 1
                    if is_recent:
                        panel_recent += 1
                if event == PROMOTE_INTENT_CREATED:
                    promote_total += 1
                    if is_recent:
                        promote_recent += 1
                if event == PROMOTE_DONE:
                    promotion_done_total += 1
                    if is_recent:
                        promotion_done_recent += 1
                if event in _WATCHER_EVENT_NAMES:
                    watcher_total += 1
                    if is_recent:
                        watcher_recent += 1
    except FileNotFoundError:
        return EventCounters(
            watcher_runs_total=0,
            watcher_runs_24h=0,
            panel_runs_total=0,
            panel_runs_24h=0,
            promote_created_total=0,
            promote_created_24h=0,
            promotion_executed_total=0,
            promotion_executed_24h=0,
            ingest_runs_by_plane={},
            source_path=source,
        )
    except Exception:
        return EventCounters(
            watcher_runs_total=watcher_total,
            watcher_runs_24h=watcher_recent,
            panel_runs_total=panel_total,
            panel_runs_24h=panel_recent,
            promote_created_total=promote_total,
            promote_created_24h=promote_recent,
            promotion_executed_total=promotion_done_total,
            promotion_executed_24h=promotion_done_recent,
            ingest_runs_by_plane={},
            source_path=source,
        )
    return EventCounters(
        watcher_runs_total=watcher_total,
        watcher_runs_24h=watcher_recent,
        panel_runs_total=panel_total,
        panel_runs_24h=panel_recent,
        promote_created_total=promote_total,
        promote_created_24h=promote_recent,
        promotion_executed_total=promotion_done_total,
        promotion_executed_24h=promotion_done_recent,
        ingest_runs_by_plane={},
        source_path=source,
    )


def _fill_ingest_run_counts(counters: EventCounters, ingestion: IngestionStatus) -> EventCounters:
    per_plane: dict[str, int] = {}
    for plane in getattr(ingestion, "planes", []) or []:
        if plane.last_run_at:
            per_plane[plane.plane] = per_plane.get(plane.plane, 0) + 1
    counters.ingest_runs_by_plane = per_plane
    return counters


def _get_intent_status(outbox_path: Path) -> IntentStatus:
    counts = _count_events(outbox_path)
    return IntentStatus(
        promote_created_total=counts.promote_created_total,
        promote_created_24h=counts.promote_created_24h,
        source_path=counts.source_path,
    )


def _read_worker_heartbeat() -> dict | None:
    path = resolve_worker_heartbeat_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _count_outbox_events(path: Path) -> int | None:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return sum(1 for line in handle if line.strip())
    except FileNotFoundError:
        return 0
    except Exception:
        return None


def _get_outbox_lag() -> OutboxLagStatus:
    heartbeat = _read_worker_heartbeat()
    processed_total = None
    outbox_path = Path(INDEX_OUTBOX_PATH)
    if heartbeat:
        processed_total = heartbeat.get("processed_total")
        heartbeat_path = heartbeat.get("outbox_path")
        if heartbeat_path:
            outbox_path = Path(str(heartbeat_path))
    outbox_events = _count_outbox_events(outbox_path)
    pending = None
    if isinstance(outbox_events, int) and isinstance(processed_total, int):
        pending = max(outbox_events - processed_total, 0)
    return OutboxLagStatus(
        outbox_events=outbox_events,
        worker_processed_total=processed_total if isinstance(processed_total, int) else None,
        pending_estimate=pending,
    )


def _get_write_guard_status() -> WriteGuardStatus:
    try:
        snapshot = DEFAULT_CONTRACT.evaluate()
    except Exception:
        return WriteGuardStatus()
    return WriteGuardStatus(
        writes_allowed=snapshot.get("writes_allowed"),
        mode=snapshot.get("state"),
    )


def get_system_status() -> SystemStatus:
    sot_meta = get_sot_metadata()
    ingestion = get_ingestion_status()
    counters = _count_events(Path(INDEX_OUTBOX_PATH)) if INDEX_OUTBOX_PATH else EventCounters()
    counters = _fill_ingest_run_counts(counters, ingestion)
    intent_status = IntentStatus(
        promote_created_total=counters.promote_created_total,
        promote_created_24h=counters.promote_created_24h,
        source_path=counters.source_path,
    )
    return SystemStatus(
        timestamp=datetime.now(timezone.utc),
        sot_version=get_sot_version(),
        sot_baseline_version=sot_meta["baseline"],
        sot_forward_line_version=sot_meta["forward_line"],
        sot_label=sot_meta["label"],
        feature_line_version=SOT_FORWARD,
        active_features=list(_ACTIVE_FEATURES),
        stores=get_store_status(),
        ingestion=ingestion,
        ask=get_ask_status(),
        intents=intent_status,
        events=counters,
        write_guard=_get_write_guard_status(),
        outbox_lag=_get_outbox_lag(),
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
