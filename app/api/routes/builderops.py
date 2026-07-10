from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.builderops.boundary import BuilderOpsBoundary
from app.builderops.model_inquiry import ModelInquiryService
from app.builderops.models import BuilderOpsConflictError, BuilderOpsLeaseError, BuilderOpsValidationError

router = APIRouter(prefix="/builderops", tags=["builderops"])


class BuilderOpsCreateBase(BaseModel):
    summary: str
    source_refs: list[dict[str, Any]] = Field(min_length=1)
    created_by: dict[str, Any] | str | None = None
    idempotency_key: str | None = None


class WorklogCreateRequest(BuilderOpsCreateBase):
    body: str
    task_context: dict[str, Any] = Field(default_factory=dict)
    promotion_status: str | None = None
    tags: list[str] | None = None


class LearningSignalCreateRequest(BuilderOpsCreateBase):
    content: str
    signal_type: str
    promotion_status: str | None = None
    tags: list[str] | None = None


class PromotionIntentCreateRequest(BuilderOpsCreateBase):
    target_authority_surface: str
    target_action: str
    target_ref: str
    target_authority_class: str
    intended_output: str


class ReceiptAppendRequest(BuilderOpsCreateBase):
    event_type: str
    actor: dict[str, Any] | str
    occurred_at: str
    target_refs: list[dict[str, Any]] = Field(min_length=1)
    action: str
    receipt_body: str
    idempotency_key: str


class InquiryStartRequest(BaseModel):
    question: str
    workflow: str
    inquiry_id: str | None = None
    source_refs: list[dict[str, Any]] = Field(min_length=1)
    created_by: dict[str, Any] | str | None = None


def _boundary() -> BuilderOpsBoundary:
    return BuilderOpsBoundary.from_path()


def _inquiry_service() -> ModelInquiryService:
    return ModelInquiryService.from_env()


def _payload(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(exclude_none=True)


def _http_error(exc: BuilderOpsValidationError) -> HTTPException:
    status = 409 if isinstance(exc, (BuilderOpsConflictError, BuilderOpsLeaseError)) else 400
    if "not found" in str(exc).lower():
        status = 404
    return HTTPException(status_code=status, detail=str(exc))


@router.get("/health")
async def health() -> dict[str, Any]:
    return _boundary().health()


@router.get("/records")
async def list_records(
    object_type: str | None = Query(default=None, alias="type"),
) -> dict[str, Any]:
    try:
        return {"records": _boundary().list_records(object_type)}
    except BuilderOpsValidationError as exc:
        raise _http_error(exc) from exc


@router.get("/records/{record_id}")
async def read_record(record_id: str) -> dict[str, Any]:
    try:
        return {"record": _boundary().read_record(record_id)}
    except BuilderOpsValidationError as exc:
        raise _http_error(exc) from exc


@router.post("/worklogs")
async def create_worklog(request: WorklogCreateRequest) -> dict[str, Any]:
    try:
        return {"record": _boundary().create_agent_worklog(_payload(request))}
    except BuilderOpsValidationError as exc:
        raise _http_error(exc) from exc


@router.post("/learning-signals")
async def create_learning_signal(request: LearningSignalCreateRequest) -> dict[str, Any]:
    try:
        return {"record": _boundary().create_learning_signal(_payload(request))}
    except BuilderOpsValidationError as exc:
        raise _http_error(exc) from exc


@router.post("/promotion-intents")
async def create_promotion_intent(request: PromotionIntentCreateRequest) -> dict[str, Any]:
    try:
        return {"record": _boundary().create_promotion_intent(_payload(request))}
    except BuilderOpsValidationError as exc:
        raise _http_error(exc) from exc


@router.post("/receipts")
async def append_receipt(request: ReceiptAppendRequest) -> dict[str, Any]:
    try:
        return {"record": _boundary().append_receipt(_payload(request))}
    except BuilderOpsValidationError as exc:
        raise _http_error(exc) from exc


@router.post("/inquiries")
async def start_inquiry(request: InquiryStartRequest) -> dict[str, Any]:
    try:
        trace = _inquiry_service().start(**_payload(request))
        return {"trace": trace}
    except BuilderOpsValidationError as exc:
        raise _http_error(exc) from exc


@router.get("/inquiries/{inquiry_id}/trace")
async def trace_inquiry(inquiry_id: str) -> dict[str, Any]:
    try:
        return {"trace": _inquiry_service().trace(inquiry_id)}
    except BuilderOpsValidationError as exc:
        raise _http_error(exc) from exc


@router.post("/inquiries/{inquiry_id}/resume")
async def resume_inquiry(inquiry_id: str) -> dict[str, Any]:
    try:
        return {"resume": _inquiry_service().resume(inquiry_id)}
    except BuilderOpsValidationError as exc:
        raise _http_error(exc) from exc


__all__ = ["router"]
