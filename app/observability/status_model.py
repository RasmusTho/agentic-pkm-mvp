from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


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
    planes: list[IngestionPlaneStatus] = []


class AskStatus(BaseModel):
    total_queries_24h: int
    avg_latency_ms_24h: float | None = None
    error_count_24h: int = 0


class SystemStatus(BaseModel):
    timestamp: datetime
    sot_version: str  # legacy alias for baseline SoT
    sot_baseline_version: str
    sot_forward_line_version: str
    sot_label: str
    stores: list[StoreStatus]
    ingestion: IngestionStatus
    ask: AskStatus


__all__ = [
    "IngestionPlaneStatus",
    "StoreStatus",
    "IngestionStatus",
    "AskStatus",
    "SystemStatus",
]
