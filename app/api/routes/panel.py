"""Panel confirmation API routes.

POST /api/panel/confirm — submits a user's explicit confirm or reject decision
for a staged Panel proposal. The runtime owns policy evaluation, WriteGuard,
idempotency, execution, receipts, and event emission. The Companion UI must
not write vault files directly.

POST /api/panel/checkbox-projection — source-backed read-mode projection of a
runtime-declared Panel checkbox option to the canonical checked Markdown state.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

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
from app.api.compatibility_mutation import (
    capability_not_ready,
    require_compatibility_write_target,
    seal_vault_mutation,
)

router = APIRouter(
    prefix="/panel",
    tags=["panel"],
    dependencies=[Depends(seal_vault_mutation)],
)


@router.post("/confirm", response_model=ConfirmResponse)
async def panel_confirm(request: ConfirmRequest, http_request: Request) -> ConfirmResponse:
    # A staged proposal names its own note file (absolute, or relative to the
    # process VAULT_ROOT), which need not be the sealed compatibility binding:
    # prove the real target before any confirm/reject effect.
    target = confirm_module.staged_proposal_note_file(request.proposal_id)
    if target is not None:
        require_compatibility_write_target(http_request, target)
    elif getattr(http_request.state, "compatibility_write_root", None) is not None and (
        confirm_module._service._proposals.get(request.proposal_id) is not None
    ):
        # A staged proposal whose note file cannot be resolved has no provable
        # target under the seal: fail closed rather than let confirm run.
        raise capability_not_ready()
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
                "trace_id": exc.trace_id,
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/checkbox-projection", response_model=CheckboxProjectionResponse)
async def panel_checkbox_projection(
    request: CheckboxProjectionRequest,
    http_request: Request,
) -> CheckboxProjectionResponse:
    # The projection resolves its own vault root; hand it the sealed binding so it
    # proves that root before reading or writing the note.
    sealed_root = getattr(http_request.state, "compatibility_write_root", None)
    try:
        return checkbox_projection_module._service.project(request, sealed_root=sealed_root)
    except CheckboxProjectionHTTPError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=exc.response.model_dump(mode="json"),
        ) from exc
