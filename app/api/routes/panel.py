"""Panel confirmation API route.

POST /api/panel/confirm — submits a user's explicit confirm or reject decision
for a staged Panel proposal. The runtime owns policy evaluation, WriteGuard,
idempotency, execution, receipts, and event emission. The Companion UI must
not write vault files directly.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

import app.panel.confirmation as confirm_module
from app.panel.confirmation import (
    ConfirmRequest,
    ConfirmResponse,
    SameTurnExecutionError,
    UnknownProposalError,
)

router = APIRouter(prefix="/panel", tags=["panel"])


@router.post("/confirm", response_model=ConfirmResponse)
async def panel_confirm(request: ConfirmRequest) -> ConfirmResponse:
    try:
        return confirm_module._service.confirm(request)
    except UnknownProposalError as exc:
        raise HTTPException(
            status_code=404,
            detail={"error": "unknown_proposal", "proposal_id": str(exc)},
        )
    except SameTurnExecutionError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
