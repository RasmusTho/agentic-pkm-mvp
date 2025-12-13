from __future__ import annotations

from datetime import datetime
from typing import List, Optional

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


class SystemStatus(BaseModel):
    timestamp: datetime
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


__all__ = [
    "IngestionPlaneStatus",
    "StoreStatus",
    "IngestionStatus",
    "AskStatus",
    "IntentStatus",
    "SystemStatus",
]
