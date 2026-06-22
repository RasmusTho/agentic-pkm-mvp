from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field

from app.observability.status_service import OrientationSignals, get_orientation_signals

# Server-declared "scarce" display cap for the resurface glance surface. A
# handful, never a feed (Resurface Surface design, "A scarce glance, not a
# feed" §4). The UI caps to this count and renders the withheld line — without a
# number — whenever the evaluation produced more than it.
RESURFACE_SCARCE_COUNT = 3


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
    # Held by the user. Purely a sort/visual signal — never urgency, never write
    # authority. Stays False until pin persistence lands (pin action is not yet
    # enabled), but the contract field is emitted now so the render activates the
    # moment a candidate is pinned.
    pinned: bool = False


class ResurfacingEvaluation(BaseModel):
    generated_at: str
    status_summary: str
    candidates: list[ResurfacingCandidate] = Field(default_factory=list)
    receipt: list[str] = Field(default_factory=list)
    read_only: bool = True
    mutation_intents: list[str] = Field(default_factory=list)
    # The scarce display cap and whether the evaluation produced more than it.
    # ``more_held_back`` lets the UI render "others were held below the line"
    # truthfully, with no count.
    scarce_count: int = RESURFACE_SCARCE_COUNT
    more_held_back: bool = False


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def evaluate_resurfacing_candidates(signals: OrientationSignals | None = None) -> ResurfacingEvaluation:
    """Produce resurfacing candidates from derived relevance-change runtime signals.

    This seam is intentionally query-independent and read-only.
    """

    orientation = signals if signals is not None else get_orientation_signals()
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

    # Pinned cards sort to the top, then the rest in server order. This is a
    # stable sort, so the underlying relevance order is otherwise preserved — the
    # surface never re-ranks (Resurface Surface design §4).
    candidates.sort(key=lambda candidate: not candidate.pinned)

    more_held_back = len(candidates) > RESURFACE_SCARCE_COUNT

    status_summary = (
        f"resurfacing_candidates={len(candidates)}; "
        f"scarce_count={RESURFACE_SCARCE_COUNT}; "
        f"more_held_back={str(more_held_back).lower()}; "
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
        scarce_count=RESURFACE_SCARCE_COUNT,
        more_held_back=more_held_back,
    )


__all__ = [
    "RESURFACE_SCARCE_COUNT",
    "ResurfacingSignal",
    "ResurfacingWhyNow",
    "ResurfacingCandidate",
    "ResurfacingEvaluation",
    "evaluate_resurfacing_candidates",
]
