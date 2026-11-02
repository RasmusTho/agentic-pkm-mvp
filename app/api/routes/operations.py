"""Authenticated common HTTP boundary for operation clients.

Companion and any separately authorized MCP v2 adapter use these outcomes;
neither surface gains an alternate execution or receipt authority here.
"""
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from app.api.operation_runtime import build_production_operation_runtime
from app.api.operation_schemas import (
    BatchConfirmation, BatchPreviewCommand, OperationCommand,
)
from app.api.batch_operation_runtime import build_production_batch_runtime
from app.operations.batch_operations import BatchStateUnavailable
from app.api.request_governed_write import governed_context_write
from app.auth import api_key_header, require_loopback_or_api_key
from app.governance.binding_authority import BindingAuthorizationError
from app.instance.context_selection import ContextSelectionError
from app.instance.active_context_service import ActiveContextServiceError
from app.instance.context_bound_read import ContextBoundReadError
from app.instance.vault_registry import RegistryQualificationError
from app.governance.governed_write import GovernedWriteProtocolError
from app.operations.contracts import OperationContext, OperationRequest
from app.write_guard import WritesBlockedError
from app.vault.active_context_v1 import ActiveContextError

router = APIRouter(prefix="/operations", tags=["operations"],
                   dependencies=[Depends(require_loopback_or_api_key)])


def _runtime(request: Request, api_key: str | None, session: str | None,
             override: str | None, *, batch: bool = False, **kwargs: Any) -> Any:
    try:
        factory = build_production_batch_runtime if batch else build_production_operation_runtime
        return factory(request, api_key=api_key,
            session_bearer=session, override_bearer=override, **kwargs)
    except (ContextSelectionError, ActiveContextServiceError) as exc:
        raise HTTPException(401, "reselection_required") from exc
    except (BindingAuthorizationError, GovernedWriteProtocolError, ContextBoundReadError,
            RegistryQualificationError, WritesBlockedError, ActiveContextError) as exc:
        raise HTTPException(403, "operation_authority_unavailable") from exc


@router.get("/capabilities")
def capabilities(request: Request, api_key: str | None = Depends(api_key_header),
    x_active_context_session: str | None = Header(default=None),
    x_active_context_override: str | None = Header(default=None)) -> dict[str, Any]:
    runtime = _runtime(request, api_key, x_active_context_session, x_active_context_override)
    operation = OperationRequest("operation.discovery", "discovery", runtime.context)
    return runtime.invoke(operation).to_dict()


@router.post("")
@governed_context_write
def execute(command: OperationCommand, request: Request,
    api_key: str | None = Depends(api_key_header),
    x_active_context_session: str | None = Header(default=None),
    x_active_context_override: str | None = Header(default=None)) -> dict[str, Any]:
    operation = OperationRequest(command.operation_id, command.request_id,
        OperationContext(command.active_context_ref, command.vault_generation),
        targets=tuple(target.model_dump(exclude_none=True) for target in command.targets),
        arguments=command.arguments, expected_version=command.expected_version)
    runtime = _runtime(request, api_key, x_active_context_session, x_active_context_override,
                       operation=operation, target_binding_id=command.target_binding_id)
    try:
        return runtime.invoke(operation).to_dict()
    except (ContextSelectionError, ActiveContextServiceError, ContextBoundReadError,
            GovernedWriteProtocolError, BindingAuthorizationError, ActiveContextError) as exc:
        raise HTTPException(403, "operation_authority_unavailable") from exc


@router.get("/receipts/{request_id}")
def receipt(request_id: str, request: Request,
    api_key: str | None = Depends(api_key_header),
    x_active_context_session: str | None = Header(default=None),
    x_active_context_override: str | None = Header(default=None)) -> dict[str, Any]:
    runtime = _runtime(request, api_key, x_active_context_session, x_active_context_override)
    try:
        return runtime.receipt(request_id).to_dict()
    except (ContextSelectionError, ContextBoundReadError, BindingAuthorizationError) as exc:
        raise HTTPException(403, "operation_authority_unavailable") from exc


@router.post("/preconditions")
def preconditions(command: OperationCommand, request: Request,
    api_key: str | None = Depends(api_key_header),
    x_active_context_session: str | None = Header(default=None),
    x_active_context_override: str | None = Header(default=None)) -> dict[str, Any]:
    if command.expected_version is not None:
        raise HTTPException(422, "preconditions_do_not_accept_expected_version")
    operation = OperationRequest(command.operation_id, command.request_id,
        OperationContext(command.active_context_ref, command.vault_generation),
        targets=tuple(target.model_dump(exclude_none=True) for target in command.targets),
        arguments=command.arguments)
    runtime = _runtime(request, api_key, x_active_context_session, x_active_context_override,
                       operation=operation, target_binding_id=command.target_binding_id)
    try:
        return runtime.preconditions(operation)
    except (ContextSelectionError, ActiveContextServiceError, ContextBoundReadError,
            GovernedWriteProtocolError, BindingAuthorizationError, ActiveContextError, WritesBlockedError) as exc:
        raise HTTPException(403, "operation_authority_unavailable") from exc


def _batch_call(call: Any) -> dict[str, Any]:
    try:
        return call()
    except BatchStateUnavailable as exc:
        raise HTTPException(409, "batch_state_unavailable") from exc
    except ValueError as exc:
        raise HTTPException(409, "batch_intent_refused") from exc
    except (ContextSelectionError, ActiveContextServiceError, ContextBoundReadError,
            GovernedWriteProtocolError, BindingAuthorizationError, ActiveContextError, WritesBlockedError) as exc:
        raise HTTPException(403, "operation_authority_unavailable") from exc


@router.post("/batches/preview")
@governed_context_write
def batch_preview(command: BatchPreviewCommand, request: Request,
    api_key: str | None = Depends(api_key_header),
    x_active_context_session: str | None = Header(default=None),
    x_active_context_override: str | None = Header(default=None)) -> dict[str, Any]:
    runtime = _runtime(request, api_key, x_active_context_session, x_active_context_override, batch=True)
    context = OperationContext(command.active_context_ref, command.vault_generation)
    items = tuple(OperationRequest(command.operation_id, item.request_id, context,
        targets=({"artifact_id": item.artifact_id},), arguments=item.arguments,
        expected_version=item.expected_version) for item in command.items)
    return _batch_call(lambda: runtime.preview(command.batch_id, items,
        target_binding_id=command.target_binding_id, limit=command.limit,
        partial_success_policy=command.partial_success_policy))


@router.get("/batches/{batch_id}")
def batch_inspect(batch_id: str, expected_digest: str, request: Request,
    api_key: str | None = Depends(api_key_header),
    x_active_context_session: str | None = Header(default=None),
    x_active_context_override: str | None = Header(default=None)) -> dict[str, Any]:
    runtime = _runtime(request, api_key, x_active_context_session, x_active_context_override, batch=True)
    return _batch_call(lambda: runtime.inspect(batch_id, expected_digest=expected_digest))


@router.post("/batches/{batch_id}/execute")
@governed_context_write
def batch_execute(batch_id: str, command: BatchConfirmation, request: Request,
    api_key: str | None = Depends(api_key_header),
    x_active_context_session: str | None = Header(default=None),
    x_active_context_override: str | None = Header(default=None)) -> dict[str, Any]:
    runtime = _runtime(request, api_key, x_active_context_session, x_active_context_override, batch=True)
    return _batch_call(lambda: runtime.execute(batch_id, expected_digest=command.expected_digest))


@router.post("/batches/{batch_id}/cancel")
@governed_context_write
def batch_cancel(batch_id: str, command: BatchConfirmation, request: Request,
    api_key: str | None = Depends(api_key_header),
    x_active_context_session: str | None = Header(default=None),
    x_active_context_override: str | None = Header(default=None)) -> dict[str, Any]:
    runtime = _runtime(request, api_key, x_active_context_session, x_active_context_override, batch=True)
    return _batch_call(lambda: runtime.cancel(batch_id, expected_digest=command.expected_digest))
