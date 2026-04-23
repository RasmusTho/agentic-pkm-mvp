from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field

from app.observability.status_service import get_orientation_signals


class ResurfacingSignal(BaseModel):
    name: str
    value: int | str
    source: str


class ResurfacingWhyNow(BaseModel):
    explanation: str
    signals: list[ResurfacingSignal] = Field(default_factory=list)


class ResurfacingCandidate(BaseModel):
    candidate_id: str
    label: str
    why_now: ResurfacingWhyNow


class ResurfacingEvaluation(BaseModel):
    generated_at: str
    status_summary: str
    candidates: list[ResurfacingCandidate] = Field(default_factory=list)
    receipt: list[str] = Field(default_factory=list)
    read_only: bool = True
    mutation_intents: list[str] = Field(default_factory=list)


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def evaluate_resurfacing_candidates() -> ResurfacingEvaluation:
    """Produce resurfacing candidates from derived relevance-change runtime signals.

    This seam is intentionally query-independent and read-only.
    """

    orientation = get_orientation_signals()
    events = orientation.events
    ingestion = orientation.ingestion
    queue = orientation.worker_queue

    pending_promotions = max((events.promote_created_total or 0) - (events.promotion_executed_total or 0), 0)
    pending_worker_items = max(queue.pending or 0, 0)

    candidates: list[ResurfacingCandidate] = []

    if pending_promotions > 0:
        candidates.append(
            ResurfacingCandidate(
                candidate_id="resurface-pending-promotions",
                label="Pending promotion intents need review",
                why_now=ResurfacingWhyNow(
                    explanation=(
                        "This is back in view now because derived relevance changed: "
                        "more promotion intents exist than executed transitions."
                    ),
                    signals=[
                        ResurfacingSignal(
                            name="pending_promotions",
                            value=pending_promotions,
                            source=events.source_path or "status.events",
                        ),
                        ResurfacingSignal(
                            name="promote_created_total",
                            value=events.promote_created_total or 0,
                            source=events.source_path or "status.events",
                        ),
                        ResurfacingSignal(
                            name="promotion_executed_total",
                            value=events.promotion_executed_total or 0,
                            source=events.source_path or "status.events",
                        ),
                    ],
                ),
            )
        )

    if pending_worker_items > 0:
        candidates.append(
            ResurfacingCandidate(
                candidate_id="resurface-worker-queue",
                label="Queued runtime work remains unresolved",
                why_now=ResurfacingWhyNow(
                    explanation=(
                        "This is back in view now because derived relevance changed: "
                        "worker queue has unresolved pending items."
                    ),
                    signals=[
                        ResurfacingSignal(
                            name="worker_queue_pending",
                            value=pending_worker_items,
                            source=queue.source_path or "status.worker_queue",
                        ),
                    ],
                ),
            )
        )

    if (events.watcher_runs_24h or 0) > 0 and (events.promote_created_24h or 0) > 0:
        candidates.append(
            ResurfacingCandidate(
                candidate_id="resurface-new-activity",
                label="Recent watcher + intent activity may have changed priorities",
                why_now=ResurfacingWhyNow(
                    explanation=(
                        "This is back in view now because derived relevance changed in the last 24h: "
                        "watcher activity and promotion-intent creation both increased."
                    ),
                    signals=[
                        ResurfacingSignal(
                            name="watcher_runs_24h",
                            value=events.watcher_runs_24h or 0,
                            source=events.source_path or "status.events",
                        ),
                        ResurfacingSignal(
                            name="promote_created_24h",
                            value=events.promote_created_24h or 0,
                            source=events.source_path or "status.events",
                        ),
                    ],
                ),
            )
        )

    status_summary = (
        f"resurfacing_candidates={len(candidates)}; "
        f"pending_promotions={pending_promotions}; "
        f"pending_worker_items={pending_worker_items}; "
        f"last_ingest_at={ingestion.last_run_at.isoformat().replace('+00:00', 'Z') if ingestion.last_run_at else 'unknown'}"
    )

    receipt = [
        "resurfacing runtime evaluated derived relevance-change signals",
        "read_only=true (no writes performed)",
        status_summary,
    ]

    return ResurfacingEvaluation(
        generated_at=_iso_now(),
        status_summary=status_summary,
        candidates=candidates,
        receipt=receipt,
    )


__all__ = [
    "ResurfacingSignal",
    "ResurfacingWhyNow",
    "ResurfacingCandidate",
    "ResurfacingEvaluation",
    "evaluate_resurfacing_candidates",
]
