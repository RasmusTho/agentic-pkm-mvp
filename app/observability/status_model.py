from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class IngestionPlaneStatus(BaseModel):
    plane: str
    last_run_at: datetime | None = None
    last_run_ok: bool | None = None
    scanned: int | None = None
    ingested: int | None = None
    errors: int | None = None
    malformed: int | None = None


class StoreStatus(BaseModel):
    name: str
    object_count: int
    last_ingest_at: datetime | None = None
    last_error_at: datetime | None = None


class IngestionStatus(BaseModel):
    last_run_at: datetime | None = None
    last_run_ok: bool | None = None
    last_error_message: str | None = None
    total_scanned: int = 0
    total_ingested: int = 0
    total_errors: int = 0
    total_malformed: int = 0
    planes: list[IngestionPlaneStatus] = Field(default_factory=list)


class AskStatus(BaseModel):
    total_queries_24h: int
    avg_latency_ms_24h: float | None = None
    error_count_24h: int = 0


class IntentStatus(BaseModel):
    promote_created_total: int = 0
    promote_created_24h: int = 0
    source_path: str | None = None


class EventCounters(BaseModel):
    watcher_runs_total: int = 0
    watcher_runs_24h: int = 0
    panel_runs_total: int = 0
    panel_runs_24h: int = 0
    promote_created_total: int = 0
    promote_created_24h: int = 0
    promotion_executed_total: int = 0
    promotion_executed_24h: int = 0
    ingest_runs_by_plane: dict[str, int] = Field(default_factory=dict)
    source_path: str | None = None


class DeliverySLAStatus(BaseModel):
    outcomes_total: dict[str, int] = Field(default_factory=dict)
    source_path: str | None = None


class IndexStatus(BaseModel):
    status: str | None = None
    issues: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    backend: str | None = None
    expected_identity: Dict[str, Any] | None = None
    stored_identity: Dict[str, Any] | None = None
    rebuild_required: bool | None = None


class PanelDiagnostics(BaseModel):
    resolved_panel_actions_root: str | None = None
    panel_actions_mappings_count: int = 0
    panel_actions_ids_sample: list[str] = Field(default_factory=list)
    has_promote_evergreen_mapping: bool = False
    last_panel_mapping_load_error: str | None = None
    source_paths: list[str] = Field(default_factory=list)
    source_mtimes: list[str | None] = Field(default_factory=list)
    combined_sha256: str | None = None


class WriteGuardStatus(BaseModel):
    writes_allowed: bool | None = None
    mode: str | None = None


class OutboxLagStatus(BaseModel):
    outbox_events: int | None = None
    worker_processed_total: int | None = None
    pending_estimate: int | None = None


class EventsLogStatus(BaseModel):
    path: str | None = None
    total_lines: int | None = None


class WorkerQueueStatus(BaseModel):
    mode: str
    pending: int | None = None
    processed_total: int | None = None
    source_path: str | None = None


class ViewFreshnessStatus(BaseModel):
    state: str
    reason: str | None = None
    sources: list[str] = Field(default_factory=list)


class InstanceProvenanceStatus(BaseModel):
    instance_id: str
    instance_role: str
    environment: str


class WatcherAutomationStatus(BaseModel):
    auto_exec_enabled: bool = False
    mode: str = "emit-only"
    source: str = "settings_default"
    env_key: str | None = None
    raw_value: str | None = None
    default_enabled: bool | None = None
    allowed_actions: list[str] = Field(default_factory=list)
    invalid_allowed_actions: list[str] = Field(default_factory=list)
    source_path: str | None = None
    source_mtime: str | None = None
    source_sha256: str | None = None
    tick_log_path: str | None = None
    panel_event_log_path: str | None = None
    writes_allowed: bool | None = None
    write_guard_mode: str | None = None
    last_tick_timestamp: str | None = None
    last_tick_panel_candidates: int | None = None
    last_tick_panel_skipped_policy: int | None = None
    last_tick_panel_skipped_auto_exec: int | None = None
    last_run_skipped_dedup: int | None = None
    last_run_skipped_idempotent: int | None = None
    last_run_skipped_writes_blocked: int | None = None
    last_run_skipped_allowed_actions: int | None = None


class SystemStatus(BaseModel):
    timestamp: datetime
    environment: str
    sot_version: str  # legacy alias for baseline SoT
    sot_baseline_version: str
    sot_forward_line_version: str
    sot_label: str
    feature_line_version: Optional[str] = None
    active_features: List[str] = Field(default_factory=list)
    stores: list[StoreStatus]
    ingestion: IngestionStatus
    ask: AskStatus
    intents: Optional[IntentStatus] = None
    events: Optional[EventCounters] = None
    delivery_sla: Optional[DeliverySLAStatus] = None
    index: Optional[IndexStatus] = None
    panel_diagnostics: Optional[PanelDiagnostics] = None
    write_guard: Optional[WriteGuardStatus] = None
    outbox_lag: Optional[OutboxLagStatus] = None
    events_log: Optional[EventsLogStatus] = None
    worker_queue: Optional[WorkerQueueStatus] = None
    view_freshness: Optional[ViewFreshnessStatus] = None
    watcher_automation: Optional[WatcherAutomationStatus] = None
    instance_provenance: Optional[InstanceProvenanceStatus] = None


__all__ = [
    "IngestionPlaneStatus",
    "StoreStatus",
    "IngestionStatus",
    "AskStatus",
    "IntentStatus",
    "EventCounters",
    "DeliverySLAStatus",
    "IndexStatus",
    "PanelDiagnostics",
    "WriteGuardStatus",
    "OutboxLagStatus",
    "EventsLogStatus",
    "WorkerQueueStatus",
    "ViewFreshnessStatus",
    "InstanceProvenanceStatus",
    "WatcherAutomationStatus",
    "SystemStatus",
]
