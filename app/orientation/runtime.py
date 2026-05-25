from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.observability.status_service import get_orientation_signals


class OrientationExplanation(BaseModel):
    leave_point: str
    open_items: list[str]
    notable_change: str


class OrientationFrame(BaseModel):
    frame: str
    explanation: OrientationExplanation
    read_only: bool = True
    mutation_intents: list[str] = Field(default_factory=list)


def _iso(dt: datetime | None) -> str:
    if dt is None:
        return "unknown"
    return dt.isoformat().replace("+00:00", "Z")


def pass_through_context_dimensions(record: dict[str, object]) -> dict[str, object]:
    raw_payload = record.get("context_dimensions")
    payload = raw_payload if isinstance(raw_payload, dict) else {}
    return {
        "scope": payload.get("scope"),
        "sphere_memberships": list(payload.get("sphere_memberships") or []),
        "situated_identity": payload.get("situated_identity"),
    }


def build_orientation_frame() -> OrientationFrame:
    signals = get_orientation_signals()
    events = signals.events
    ingestion = signals.ingestion
    queue = signals.worker_queue

    leave_point = (
        "Last known runtime leave-point: "
        f"watcher_runs_24h={events.watcher_runs_24h if events else 0}, "
        f"panel_runs_24h={events.panel_runs_24h if events else 0}, "
        f"last_ingest_at={_iso(ingestion.last_run_at)}."
    )

    open_items: list[str] = []
    if queue and (queue.pending or 0) > 0:
        open_items.append(f"Worker queue pending runtime changes: {queue.pending}.")
    if events and events.promote_created_total > events.promotion_executed_total:
        remaining = events.promote_created_total - events.promotion_executed_total
        open_items.append(f"Promotion intents created but not executed: {remaining}.")
    if not open_items:
        open_items.append("No unresolved runtime loops detected in current snapshot.")

    notable_change = (
        "Recent notable change: "
        f"ingest_total={ingestion.total_ingested}, "
        f"watcher_runs_total={events.watcher_runs_total if events else 0}, "
        f"promotion_executed_total={events.promotion_executed_total if events else 0}."
    )

    frame = (
        "Orientation frame: "
        "where you were is reconstructed from recent runtime activity, "
        "what is still open is listed as unresolved loops, "
        "and notable changes are summarized from current derived counters."
    )

    return OrientationFrame(
        frame=frame,
        explanation=OrientationExplanation(
            leave_point=leave_point,
            open_items=open_items,
            notable_change=notable_change,
        ),
    )


__all__ = ["OrientationExplanation", "OrientationFrame", "build_orientation_frame", "pass_through_context_dimensions"]
