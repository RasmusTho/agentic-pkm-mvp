"""Product API for governed provisional-memory direct writes."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from app.agent_memory.provisional_write import (
    ProvisionalMemoryWriteError,
    ProvisionalWriteRequest,
    ProvisionalWriteResult,
    write_provisional_memory,
)
from app.api.routes.vault_resolution import active_vault_root_or_selection_required
from app.write_guard import WritesBlockedError

router = APIRouter(prefix="/companion/memory", tags=["companion", "memory"])


@router.post("/provisional", response_model=ProvisionalWriteResult)
def post_provisional_memory(
    request: ProvisionalWriteRequest,
) -> ProvisionalWriteResult | JSONResponse:
    vault_root = active_vault_root_or_selection_required(require_initialized=True)
    if isinstance(vault_root, JSONResponse):
        return vault_root
    try:
        return write_provisional_memory(request, vault_root=vault_root)
    except WritesBlockedError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "writeguard_blocked",
                "state": exc.state,
                "reason": exc.reason,
                "message": str(exc),
            },
        ) from exc
    except ProvisionalMemoryWriteError as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "provisional_memory_write_incomplete",
                "state": exc.reconciliation.state.value,
                "diagnostic": exc.reconciliation.diagnostic.value,
                "receipt_id": (
                    str(exc.lifecycle_receipt.receipt_id)
                    if exc.lifecycle_receipt is not None
                    else None
                ),
            },
        ) from exc


__all__ = ["router"]
