from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional
from app.domain.state_axes import normalize_artifact_state_axes
from app.events.models import new_trace_id
from app.events.types import INGEST_OBJECT_CREATED
from app.observability.tracer import start_span
from app.services.outbox import insert_object_and_outbox
from app.write_guard import DEFAULT_WRITE_GUARD, WritesBlockedError

router = APIRouter()

# Named WriteGuard action for this seam (formal-model.md F-D, owner-decided on
# epic #2778: this V-write seam gets the same fail-closed
# ``assert_writes_allowed`` used at the other named seams, e.g. #2910's
# knowledge write port and app/api/routes/capture.py's
# ``companion.capture.append``). No bootstrap escape is registered for this
# action, so a blocked/degraded runtime denies the write atomically instead of
# reaching ``insert_object_and_outbox`` (I-A3 "WG at every V-write seam").
_WRITE_GUARD_ACTION = "ingest.object_create"


class IngestRequest(BaseModel):
    uuid: str
    title: str
    review_state: str
    content: str
    origin: Optional[str] = None
    trust: Optional[str] = None
    source_ref: Optional[str] = None


def _writeguard_blocked_detail(exc: WritesBlockedError) -> dict[str, Any]:
    return {
        "error": "writeguard_blocked",
        "state": "blocked",
        "message": str(exc),
        "reason": exc.reason,
    }


@router.post("/ingest")
async def ingest(req: IngestRequest, request: Request):
    trace_id = getattr(request.state, "trace_id", None) or new_trace_id()

    # Policy — the guard is asserted at the seam itself, before any I/O, and
    # fails closed: an evaluation error blocks the write like a denial does
    # (formal-model.md gap 4, "fail-closed guards"). Ordering matches the
    # other named seams (capture.py's /capture, companion.py's /note/save):
    # guard first, so a blocked runtime never reaches the persistence call.
    try:
        DEFAULT_WRITE_GUARD.assert_writes_allowed(_WRITE_GUARD_ACTION)
    except WritesBlockedError as exc:
        raise HTTPException(
            status_code=409,
            detail=_writeguard_blocked_detail(exc),
        ) from exc

    with start_span("api.ingest", trace_id, {"path": "/ingest"}):
        payload = normalize_artifact_state_axes(req.model_dump(exclude_none=True), default_review_state="draft")
        # required_db=True (#4214 D2): this enqueue is the route's ONLY
        # persistence side effect and it has no compensating JSONL sink, so an
        # optional self-owned skip would return ``""`` and let the route answer
        # 200 for an ingest that was never queued. Fail loud instead — the
        # pre-#4064 behaviour this route always had.
        insert_object_and_outbox(
            payload,
            INGEST_OBJECT_CREATED,
            trace_id,
            object_id=req.uuid,
            required_db=True,
        )
    return {"trace_id": trace_id}
