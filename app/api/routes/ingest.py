from fastapi import APIRouter, Request
from pydantic import BaseModel
from typing import Optional
from app.agent.events import INGEST_OBJECT_CREATED, new_trace_id
from app.observability.tracer import start_span
from app.services.outbox import insert_object_and_outbox

router = APIRouter()

class IngestRequest(BaseModel):
    uuid: str
    title: str
    review_state: str
    content: str
    origin: Optional[str] = None
    trust: Optional[str] = None
    source_ref: Optional[str] = None

@router.post("/ingest")
async def ingest(req: IngestRequest, request: Request):
    trace_id = getattr(request.state, "trace_id", None) or new_trace_id()
    with start_span("api.ingest", trace_id, {"path": "/ingest"}):
        insert_object_and_outbox(req.model_dump(), INGEST_OBJECT_CREATED, trace_id)
    return {"trace_id": trace_id}
