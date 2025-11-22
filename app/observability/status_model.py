from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class StoreStatus(BaseModel):
    name: str
    object_count: int
    last_ingest_at: datetime | None = None
    last_error_at: datetime | None = None


class IngestionStatus(BaseModel):
    last_run_at: datetime | None = None
    last_run_ok: bool | None = None
    last_error_message: str | None = None


class AskStatus(BaseModel):
    total_queries_24h: int
    avg_latency_ms_24h: float | None = None


class SystemStatus(BaseModel):
    timestamp: datetime
    sot_version: str
    stores: list[StoreStatus]
    ingestion: IngestionStatus
    ask: AskStatus


__all__ = [
    "StoreStatus",
    "IngestionStatus",
    "AskStatus",
    "SystemStatus",
]
