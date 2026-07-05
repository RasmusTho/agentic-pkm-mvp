"""Panel confirmation API routes.

POST /api/panel/confirm — submits a user's explicit confirm or reject decision
for a staged Panel proposal. The runtime owns policy evaluation, WriteGuard,
idempotency, execution, receipts, and event emission. The Companion UI must
not write vault files directly.

POST /api/panel/checkbox-projection — source-backed read-mode projection of a
runtime-declared Panel checkbox option to the canonical checked Markdown state.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

import app.panel.confirmation as confirm_module
import app.panel.checkbox_projection as checkbox_projection_module
from app.panel.checkbox_projection import (
    CheckboxProjectionHTTPError,
    CheckboxProjectionRequest,
    CheckboxProjectionResponse,
)
from app.panel.confirmation import (
    ConfirmRequest,
    ConfirmResponse,
    PanelReceiptPersistenceError,
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
    except PanelReceiptPersistenceError as exc:
        # Receipt-before-ack (P-5, T-panel-confirm): the panel.action.* receipt
        # could not be persisted to any outbox sink. Withhold the success ack
        # rather than return a receipt for a lost accountability record —
        # mirrors T-capture's authority_receipt_persistence_failed shape.
        raise HTTPException(
            status_code=500,
            detail={
                "error": "authority_receipt_persistence_failed",
                "state": "not_acknowledged",
                "message": (
                    "The panel action may have been applied, but its "
                    "accountability receipt could not be persisted; success "
                    "acknowledgement was withheld."
                ),
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/checkbox-projection", response_model=CheckboxProjectionResponse)
async def panel_checkbox_projection(
    request: CheckboxProjectionRequest,
) -> CheckboxProjectionResponse:
    try:
        return checkbox_projection_module._service.project(request)
    except CheckboxProjectionHTTPError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=exc.response.model_dump(mode="json"),
        ) from exc
