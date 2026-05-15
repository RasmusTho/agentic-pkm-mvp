from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from app.config.environment import active_environment
from app.events.types import PROMOTE_INTENT_CREATED, PROMOTE_DONE
from app.events.types import ORCHESTRATOR_STEP_ERROR, ORCHESTRATOR_STEP_FINISHED
from app.events.types import PANEL_INTENT_EXECUTED, PANEL_LOG_CREATED
from app.observability.ingest_meta import get_ingest_status
from app.orchestrator.delivery_sla import (
    DELIVERY_SLA_DELIVERED,
    DELIVERY_SLA_FAILED,
    DELIVERY_SLA_ROLLED_BACK,
    DELIVERY_SLA_TIMEOUT,
    map_delivery_sla_from_event_record,
)
from app.observability.status_model import (
    AskStatus,
    DeliverySLAStatus,
    EventCounters,
    EventsLogStatus,
    IngestionStatus,
    InstanceProvenanceStatus,
    IntentStatus,
    IndexStatus,
    PanelDiagnostics,
    OutboxLagStatus,
    StoreStatus,
    SystemStatus,
    ViewFreshnessStatus,
    WatcherAutomationStatus,
    WorkerQueueStatus,
    WriteGuardStatus,
    WatcherLifecycleStatus,
    ContextDimensionsStatus,
)
from app.outbox.events import INDEX_OUTBOX_PATH
from app.runtime.worker_heartbeat import resolve_worker_heartbeat_path
from app.settings.runtime import get_settings_bundle
from app.settings.panel_actions_settings import load_panel_actions_settings, panel_action_ids
from app.settings.watcher_settings import invalid_allowed_actions, load_watcher_settings, resolve_auto_exec_state
from app.settings.panel_actions import get_panel_actions_diagnostics
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


_TRUE_VALUES = {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class OrientationSignals:
    events: EventCounters
    ingestion: IngestionStatus
    worker_queue: WorkerQueueStatus


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


def _delivery_sla_status(outbox_path: Path) -> DeliverySLAStatus:
    outcomes = {
        DELIVERY_SLA_DELIVERED: 0,
        DELIVERY_SLA_TIMEOUT: 0,
        DELIVERY_SLA_FAILED: 0,
        DELIVERY_SLA_ROLLED_BACK: 0,
    }
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
                if event not in {ORCHESTRATOR_STEP_ERROR, ORCHESTRATOR_STEP_FINISHED}:
                    continue
                state = map_delivery_sla_from_event_record(record)
                if not state:
                    continue
                outcomes[state] = outcomes.get(state, 0) + 1
    except FileNotFoundError:
        pass
    except Exception:
        pass
    return DeliverySLAStatus(outcomes_total=outcomes, source_path=str(outbox_path))


def _outbox_db_source() -> str:
    return os.getenv("DATABASE_URL") or os.getenv("DB_DSN") or "outbox"


def _count_events_db() -> EventCounters | None:
    try:
        from app.services import outbox as outbox_service
    except Exception:
        return None
    try:
        conn = outbox_service._open_conn()
    except Exception:
        return None
    panel_total = panel_recent = promote_total = promote_recent = watcher_total = watcher_recent = 0
    promotion_done_total = promotion_done_recent = 0
    cutoff = datetime.now(timezone.utc) - _EVENT_WINDOW
    try:
        cur = conn.cursor()
        cur.execute(
            "select topic, count(*) as total, sum(case when created_at >= %s then 1 else 0 end) as recent from outbox group by topic",
            (cutoff,),
        )
        rows = cur.fetchall() or []
    except Exception:
        return None
    finally:
        try:
            conn.close()
        except Exception:
            pass
    for row in rows:
        if isinstance(row, dict):
            topic = row.get("topic")
            total = row.get("total")
            recent = row.get("recent")
        else:
            topic = row[0]
            total = row[1] if len(row) > 1 else 0
            recent = row[2] if len(row) > 2 else 0
        topic = str(topic or "")
        total = int(total or 0)
        recent = int(recent or 0)
        if topic == "panel.intent.executed":
            panel_total += total
            panel_recent += recent
        if topic == PROMOTE_INTENT_CREATED:
            promote_total += total
            promote_recent += recent
        if topic == PROMOTE_DONE:
            promotion_done_total += total
            promotion_done_recent += recent
        if topic in _WATCHER_EVENT_NAMES:
            watcher_total += total
            watcher_recent += recent
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
        source_path=_outbox_db_source(),
    )


def _fill_ingest_run_counts(counters: EventCounters, ingestion: IngestionStatus) -> EventCounters:
    per_plane: dict[str, int] = {}
    for plane in getattr(ingestion, "planes", []) or []:
        if plane.last_run_at:
            per_plane[plane.plane] = per_plane.get(plane.plane, 0) + 1
    counters.ingest_runs_by_plane = per_plane
    return counters


def _get_intent_status(counters: EventCounters) -> IntentStatus:
    return IntentStatus(
        promote_created_total=counters.promote_created_total,
        promote_created_24h=counters.promote_created_24h,
        source_path=counters.source_path,
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
    mode = _worker_queue_mode()
    heartbeat = _read_worker_heartbeat()
    processed_total = None
    if heartbeat and isinstance(heartbeat.get("processed_total"), int):
        processed_total = heartbeat.get("processed_total")
    if mode == "db":
        pending = _count_outbox_pending_db()
        total = _count_outbox_total_db()
        return OutboxLagStatus(
            outbox_events=total,
            worker_processed_total=processed_total,
            pending_estimate=pending,
        )
    outbox_path = Path(INDEX_OUTBOX_PATH)
    if heartbeat:
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


def _get_index_status() -> IndexStatus | None:
    try:
        from app.index.doctor import diagnose_index
    except Exception:
        return None
    try:
        diag = diagnose_index()
    except Exception:
        return None
    issues = diag.get("issues") or []
    warnings = diag.get("warnings") or []
    status = diag.get("status") or "unknown"
    return IndexStatus(
        status=status,
        issues=[str(item) for item in issues],
        warnings=[str(item) for item in warnings],
        backend=diag.get("backend"),
        expected_identity=diag.get("expected_identity"),
        stored_identity=diag.get("stored_identity"),
        rebuild_required=bool(issues),
    )


def _get_panel_diagnostics() -> PanelDiagnostics:
    try:
        diag = get_panel_actions_diagnostics()
    except Exception:
        return PanelDiagnostics()

    # Populate provenance fields from panel actions settings
    source_paths: list[str] = []
    source_mtimes: list[str | None] = []
    combined_sha256: str | None = None
    try:
        panel_settings = load_panel_actions_settings()
        for src in panel_settings.sources:
            source_paths.append(src.path)
            source_mtimes.append(src.mtime)
        combined_sha256 = panel_settings.combined_sha
    except Exception:
        pass

    return PanelDiagnostics(
        **diag,
        source_paths=source_paths,
        source_mtimes=source_mtimes,
        combined_sha256=combined_sha256,
    )


def _events_log_status() -> EventsLogStatus:
    outbox_path = Path(INDEX_OUTBOX_PATH)
    total_lines = _count_outbox_events(outbox_path)
    return EventsLogStatus(path=str(outbox_path), total_lines=total_lines)


def _read_last_json_record(path: Path) -> dict | None:
    try:
        with path.open("r", encoding="utf-8") as handle:
            last: dict | None = None
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except Exception:
                    continue
                if isinstance(payload, dict):
                    last = payload
            return last
    except FileNotFoundError:
        return None
    except Exception:
        return None


def _last_watcher_run_record(path: Path) -> dict | None:
    try:
        with path.open("r", encoding="utf-8") as handle:
            last: dict | None = None
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except Exception:
                    continue
                if not isinstance(payload, dict):
                    continue
                event_name = payload.get("event") or payload.get("event_type") or payload.get("topic")
                if event_name in _WATCHER_EVENT_NAMES:
                    last = payload
            return last
    except FileNotFoundError:
        return None
    except Exception:
        return None


def _worker_queue_mode() -> str:
    raw_enabled = (os.getenv("WORKER_ENABLE") or "").strip().lower()
    if raw_enabled and raw_enabled not in _TRUE_VALUES:
        return "none"
    backend = (os.getenv("STORE_BACKEND") or "memory").strip().lower()
    db_url = os.getenv("DATABASE_URL") or os.getenv("DB_DSN")
    if backend == "pg" or db_url:
        return "db"
    if os.getenv("INDEX_OUTBOX_PATH"):
        return "jsonl"
    return "none"


def _count_outbox_pending_db() -> int | None:
    try:
        from app.services import outbox as outbox_service
    except Exception:
        return None
    try:
        conn = outbox_service._open_conn()
    except Exception:
        return None
    try:
        cur = conn.cursor()
        cur.execute("select count(*) from outbox where delivered_at is null")
        row = cur.fetchone()
        return int(row[0]) if row else 0
    except Exception:
        return None
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _count_outbox_total_db() -> int | None:
    try:
        from app.services import outbox as outbox_service
    except Exception:
        return None
    try:
        conn = outbox_service._open_conn()
    except Exception:
        return None
    try:
        cur = conn.cursor()
        cur.execute("select count(*) from outbox")
        row = cur.fetchone()
        return int(row[0]) if row else 0
    except Exception:
        return None
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _get_worker_queue_status() -> WorkerQueueStatus:
    mode = _worker_queue_mode()
    heartbeat = _read_worker_heartbeat() or {}
    processed_total = heartbeat.get("processed_total") if isinstance(heartbeat.get("processed_total"), int) else None
    source_path = None
    pending: int | None = None

    if mode == "db":
        source_path = os.getenv("DATABASE_URL") or os.getenv("DB_DSN") or "outbox"
        pending = _count_outbox_pending_db()
    elif mode == "jsonl":
        source_path = os.getenv("INDEX_OUTBOX_PATH") or str(Path(INDEX_OUTBOX_PATH))
        total_lines = _count_outbox_events(Path(source_path)) if source_path else None
        if isinstance(total_lines, int) and isinstance(processed_total, int):
            pending = max(total_lines - processed_total, 0)
        elif isinstance(total_lines, int):
            pending = total_lines

    return WorkerQueueStatus(
        mode=mode,
        pending=pending,
        processed_total=processed_total,
        source_path=source_path,
    )


def classify_view_freshness(
    *,
    stores: list[StoreStatus],
    ingestion: IngestionStatus,
    worker_queue: WorkerQueueStatus | None = None,
) -> ViewFreshnessStatus:
    sources: list[str] = []
    if stores:
        sources.append("stores")
    if ingestion.last_run_at or ingestion.planes:
        sources.append("ingestion")
    if worker_queue and worker_queue.mode != "none":
        sources.append("worker_queue")

    if not sources:
        return ViewFreshnessStatus(
            state="unknown",
            reason="no runtime freshness signals are available",
            sources=[],
        )

    if ingestion.total_errors or ingestion.total_malformed:
        return ViewFreshnessStatus(
            state="partial",
            reason="latest ingest signals include errors or malformed inputs",
            sources=sources,
        )

    if ingestion.last_run_ok is False:
        return ViewFreshnessStatus(
            state="stale",
            reason="latest ingest run failed",
            sources=sources,
        )

    if worker_queue and worker_queue.pending and worker_queue.pending > 0:
        return ViewFreshnessStatus(
            state="partial",
            reason="worker queue has pending runtime changes",
            sources=sources,
        )

    if ingestion.last_run_at or any(store.last_ingest_at for store in stores):
        return ViewFreshnessStatus(
            state="fresh",
            reason="ingest/status signals are present and no stale or partial condition was detected",
            sources=sources,
        )

    return ViewFreshnessStatus(
        state="unknown",
        reason="runtime signals exist but no freshness timestamp is available",
        sources=sources,
    )


def _get_watcher_automation_status() -> WatcherAutomationStatus:
    try:
        watcher_settings = load_watcher_settings()
    except Exception:
        return WatcherAutomationStatus()

    auto_exec = resolve_auto_exec_state()
    invalid_actions: list[str] = []
    try:
        panel_settings = load_panel_actions_settings()
        invalid_actions = invalid_allowed_actions(watcher_settings, sorted(panel_action_ids(panel_settings)))
    except Exception:
        invalid_actions = []

    write_guard = _get_write_guard_status()
    tick_record = _read_last_json_record(watcher_settings.paths.watcher_tick_log)
    watcher_run_record = _last_watcher_run_record(watcher_settings.paths.panel_event_log)
    watcher_payload = watcher_run_record.get("payload") if isinstance(watcher_run_record, dict) else {}
    if not isinstance(watcher_payload, dict):
        watcher_payload = {}

    return WatcherAutomationStatus(
        auto_exec_enabled=auto_exec.enabled,
        mode="auto-exec" if auto_exec.enabled else "emit-only",
        source=auto_exec.source,
        env_key=auto_exec.env_key,
        raw_value=auto_exec.raw_value,
        default_enabled=auto_exec.default_enabled,
        allowed_actions=list(watcher_settings.allowed_actions),
        invalid_allowed_actions=invalid_actions,
        source_path=watcher_settings.source.path,
        source_mtime=watcher_settings.source.mtime,
        source_sha256=watcher_settings.source.sha256,
        tick_log_path=str(watcher_settings.paths.watcher_tick_log),
        panel_event_log_path=str(watcher_settings.paths.panel_event_log),
        writes_allowed=write_guard.writes_allowed,
        write_guard_mode=write_guard.mode,
        last_tick_timestamp=str(tick_record.get("timestamp")) if isinstance(tick_record, dict) and tick_record.get("timestamp") else None,
        last_tick_panel_candidates=int(tick_record.get("panel_candidates", 0)) if isinstance(tick_record, dict) and tick_record.get("panel_candidates") is not None else None,
        last_tick_panel_skipped_policy=int(tick_record.get("panel_skipped_policy", 0)) if isinstance(tick_record, dict) and tick_record.get("panel_skipped_policy") is not None else None,
        last_tick_panel_skipped_auto_exec=int(tick_record.get("panel_skipped_auto_exec", 0)) if isinstance(tick_record, dict) and tick_record.get("panel_skipped_auto_exec") is not None else None,
        last_run_skipped_dedup=int(watcher_payload.get("skipped_dedup", 0)) if watcher_payload.get("skipped_dedup") is not None else None,
        last_run_skipped_idempotent=int(watcher_payload.get("skipped_idempotent", 0)) if watcher_payload.get("skipped_idempotent") is not None else None,
        last_run_skipped_writes_blocked=int(watcher_payload.get("skipped_writes_blocked", 0)) if watcher_payload.get("skipped_writes_blocked") is not None else None,
        last_run_skipped_allowed_actions=int(watcher_payload.get("panel_skipped_allowed_actions", 0)) if watcher_payload.get("panel_skipped_allowed_actions") is not None else None,
    )


def _get_instance_provenance_status() -> InstanceProvenanceStatus | None:
    try:
        bundle = get_settings_bundle()
    except Exception:
        return None
    instance = getattr(bundle, "instance", None)
    if instance is None:
        return None
    return InstanceProvenanceStatus(
        instance_id=str(getattr(instance, "id", "home")),
        instance_role=str(getattr(instance, "role", "master")),
        environment=str(getattr(instance, "environment", active_environment())),
    )


def _normalize_context_dimensions(value: object) -> ContextDimensionsStatus | None:
    if not isinstance(value, dict):
        return None
    if "scope" not in value or "sphere_memberships" not in value:
        return None
    scope = value.get("scope")
    spheres = value.get("sphere_memberships")
    if not isinstance(scope, str) or scope is None:
        return None
    if not isinstance(spheres, list):
        return None
    return ContextDimensionsStatus(
        scope=scope.strip() or "default",
        sphere_memberships=[str(item) for item in spheres],
        situated_identity=value.get("situated_identity", None),
    )


def _status_context_dimensions(outbox_path: Path) -> ContextDimensionsStatus | None:
    try:
        lines = outbox_path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return None
    for line in reversed(lines):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except Exception:
            continue
        top_level = _normalize_context_dimensions(record.get("context_dimensions"))
        if top_level is not None:
            return top_level
        payload = record.get("payload")
        if isinstance(payload, dict):
            nested = _normalize_context_dimensions(payload.get("context_dimensions"))
            if nested is not None:
                return nested
    return None


def _read_watcher_heartbeat_watchers() -> dict[str, dict]:
    try:
        from app.watcher.heartbeat import resolve_heartbeat_path
        path = resolve_heartbeat_path()
        if not path.exists():
            return {}
        raw = json.loads(path.read_text(encoding="utf-8"))
        watchers = raw.get("watchers")
        return watchers if isinstance(watchers, dict) else {}
    except Exception:
        return {}


def _last_panel_run_record(path: Path) -> dict | None:
    try:
        with path.open("r", encoding="utf-8") as handle:
            last: dict | None = None
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except Exception:
                    continue
                if not isinstance(payload, dict):
                    continue
                topic = payload.get("event") or payload.get("event_type") or payload.get("topic")
                if topic == PANEL_INTENT_EXECUTED:
                    last = payload
            return last
    except FileNotFoundError:
        return None
    except Exception:
        return None


def _last_panel_log_record(path: Path) -> dict | None:
    try:
        with path.open("r", encoding="utf-8") as handle:
            last: dict | None = None
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except Exception:
                    continue
                if not isinstance(payload, dict):
                    continue
                topic = payload.get("event") or payload.get("event_type") or payload.get("topic")
                if topic == PANEL_LOG_CREATED:
                    last = payload
            return last
    except FileNotFoundError:
        return None
    except Exception:
        return None


def _newer_panel_record(a: dict | None, b: dict | None) -> dict | None:
    if a is None:
        return b
    if b is None:
        return a
    ts_a = _parse_timestamp(a.get("timestamp") or a.get("created_at"))
    ts_b = _parse_timestamp(b.get("timestamp") or b.get("created_at"))
    if ts_a is None:
        return b
    if ts_b is None:
        return a
    return a if ts_a >= ts_b else b


def _get_watcher_lifecycle_status() -> WatcherLifecycleStatus | None:
    try:
        watcher_settings = load_watcher_settings()
    except Exception:
        return None

    watchers = _read_watcher_heartbeat_watchers()
    panel_w = watchers.get("panel") or {}
    ingest_w = watchers.get("ingest") or {}

    panel_emitted_at_raw = panel_w.get("last_emitted_event_at")
    panel_last_emitted_iso: str | None = None
    if panel_emitted_at_raw is not None:
        try:
            from datetime import timezone
            panel_last_emitted_iso = datetime.fromtimestamp(float(panel_emitted_at_raw), tz=timezone.utc).isoformat()
        except Exception:
            pass

    outbox_path = Path(INDEX_OUTBOX_PATH) if INDEX_OUTBOX_PATH else None
    panel_event_log = watcher_settings.paths.panel_event_log

    executed_record = _newer_panel_record(
        _last_panel_run_record(panel_event_log),
        _last_panel_run_record(outbox_path) if outbox_path else None,
    )

    log_record = _newer_panel_record(
        _last_panel_log_record(panel_event_log),
        _last_panel_log_record(outbox_path) if outbox_path else None,
    )

    last_panel_run_at: str | None = None
    last_panel_run_actions_count: int | None = None
    last_panel_run_executed_count: int | None = None
    last_panel_run_summary: str | None = None

    if executed_record is not None:
        last_panel_run_at = str(executed_record.get("timestamp") or executed_record.get("created_at") or "")
        payload = executed_record.get("payload") or {}
        if isinstance(payload, dict):
            actions = payload.get("actions")
            executed_ids = payload.get("executed_action_ids")
            last_panel_run_actions_count = len(actions) if isinstance(actions, list) else 0
            last_panel_run_executed_count = len(executed_ids) if isinstance(executed_ids, list) else 0

    if log_record is not None:
        log_payload = log_record.get("payload") or {}
        if isinstance(log_payload, dict):
            last_panel_run_summary = log_payload.get("summary")

    return WatcherLifecycleStatus(
        panel_changed_total=int(panel_w["changed_total"]) if "changed_total" in panel_w else None,
        panel_emitted_total=int(panel_w["emitted_total"]) if "emitted_total" in panel_w else None,
        panel_rate_limited_total=int(panel_w["rate_limited_total"]) if "rate_limited_total" in panel_w else None,
        panel_last_emitted_event_at=panel_last_emitted_iso,
        panel_last_trace_id=str(panel_w["last_trace_id"]) if "last_trace_id" in panel_w else None,
        ingest_changed_total=int(ingest_w["changed_total"]) if "changed_total" in ingest_w else None,
        ingest_emitted_total=int(ingest_w["emitted_total"]) if "emitted_total" in ingest_w else None,
        ingest_rate_limited_total=int(ingest_w["rate_limited_total"]) if "rate_limited_total" in ingest_w else None,
        last_panel_run_at=last_panel_run_at or None,
        last_panel_run_actions_count=last_panel_run_actions_count,
        last_panel_run_executed_count=last_panel_run_executed_count,
        last_panel_run_summary=last_panel_run_summary,
    )


def _get_v6_seams() -> dict | None:
    try:
        from app.cli.health import _check_v6_seams  # lazy to avoid circular import
        return _check_v6_seams()
    except Exception:
        return None


def get_system_status() -> SystemStatus:
    sot_meta = get_sot_metadata()
    ingestion = get_ingestion_status()
    queue_mode = _worker_queue_mode()
    counters: EventCounters | None = None
    if queue_mode == "db":
        counters = _count_events_db()
    if counters is None:
        counters = _count_events(Path(INDEX_OUTBOX_PATH)) if INDEX_OUTBOX_PATH else EventCounters()
    counters = _fill_ingest_run_counts(counters, ingestion)
    intent_status = _get_intent_status(counters)
    stores = get_store_status()
    worker_queue = _get_worker_queue_status()
    return SystemStatus(
        timestamp=datetime.now(timezone.utc),
        environment=active_environment(),
        sot_version=get_sot_version(),
        sot_baseline_version=sot_meta["baseline"],
        sot_forward_line_version=sot_meta["forward_line"],
        sot_label=sot_meta["label"],
        feature_line_version=SOT_FORWARD,
        active_features=list(_ACTIVE_FEATURES),
        stores=stores,
        ingestion=ingestion,
        ask=get_ask_status(),
        intents=intent_status,
        events=counters,
        delivery_sla=_delivery_sla_status(Path(INDEX_OUTBOX_PATH)),
        index=_get_index_status(),
        panel_diagnostics=_get_panel_diagnostics(),
        write_guard=_get_write_guard_status(),
        outbox_lag=_get_outbox_lag(),
        events_log=_events_log_status(),
        worker_queue=worker_queue,
        view_freshness=classify_view_freshness(
            stores=stores,
            ingestion=ingestion,
            worker_queue=worker_queue,
        ),
        watcher_automation=_get_watcher_automation_status(),
        watcher_lifecycle=_get_watcher_lifecycle_status(),
        instance_provenance=_get_instance_provenance_status(),
        context_dimensions=_status_context_dimensions(Path(INDEX_OUTBOX_PATH)),
        v6_0_seams=_get_v6_seams(),
    )


def get_orientation_signals() -> OrientationSignals:
    ingestion = get_ingestion_status()
    queue_mode = _worker_queue_mode()
    counters: EventCounters | None = None
    if queue_mode == "db":
        counters = _count_events_db()
    if counters is None:
        counters = _count_events(Path(INDEX_OUTBOX_PATH)) if INDEX_OUTBOX_PATH else EventCounters()
    counters = _fill_ingest_run_counts(counters, ingestion)
    return OrientationSignals(
        events=counters,
        ingestion=ingestion,
        worker_queue=_get_worker_queue_status(),
    )


__all__ = [
    "get_system_status",
    "get_orientation_signals",
    "get_store_status",
    "get_ingestion_status",
    "get_ask_status",
    "record_ask_query",
    "record_ask_error",
    "reset_ask_metrics",
    "classify_view_freshness",
]
