"""Panel confirmation API routes.

POST /api/panel/confirm — submits a user's explicit confirm or reject decision
for a staged Panel proposal. The runtime owns policy evaluation, WriteGuard,
idempotency, execution, receipts, and event emission. The Companion UI must
not write vault files directly.

POST /api/panel/checkbox-projection — source-backed read-mode projection of a
runtime-declared Panel checkbox option to the canonical checked Markdown state.
"""

from __future__ import annotations

import logging
import os
from dataclasses import asdict
from pathlib import Path

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
    RestageRequiredError,
    UnknownProposalError,
)
from app.api.compatibility_mutation import (
    capability_not_ready,
    require_compatibility_write_target,
    seal_vault_mutation,
)
from app.config.database import runtime_database_is_named
from app.instance.compatibility_binding import compatibility_binding_for_root
from app.auth import require_loopback_or_api_key
from app.standing_questions.projection import rebuild_standing_questions_projection
from app.standing_questions.review import (
    QuestionReviewError,
    accepted_question_receipt,
    complete_question_acceptance,
    prepare_question_acceptance,
    reconcile_missing_question_acceptance,
)
from app.text.helpers import content_hash

router = APIRouter(
    prefix="/panel",
    tags=["panel"],
    dependencies=[Depends(seal_vault_mutation)],
)

_LOGGER = logging.getLogger(__name__)


def _sync_standing_question_projection(vault_root: Path) -> None:
    if not runtime_database_is_named(os.environ):
        return
    try:
        binding_id = compatibility_binding_for_root(vault_root)
        rebuild_standing_questions_projection(vault_root, vault_binding_id=binding_id)
    except Exception:
        # The vault write is authoritative; GET reports a stale projection
        # until the producer retries or a later rebuild succeeds.
        _LOGGER.exception("standing-question projection refresh failed after review write")


@router.post("/confirm", response_model=ConfirmResponse)
async def panel_confirm(
    request: ConfirmRequest,
    http_request: Request = None,  # type: ignore[assignment]  # FastAPI injects; None only for direct calls
) -> ConfirmResponse:
    # A staged proposal names its own note file (absolute, or relative to the
    # process VAULT_ROOT), which need not be the sealed compatibility binding:
    # prove the real target before any confirm/reject effect.
    # FastAPI always injects the request; a direct in-process call (no router seal)
    # has no sealed binding to prove against.
    sealed_root = (
        getattr(http_request.state, "compatibility_write_root", None) if http_request is not None else None
    )
    target = confirm_module.staged_proposal_note_file(request.proposal_id)
    if http_request is not None and target is not None:
        require_compatibility_write_target(http_request, target)
    elif sealed_root is not None and (
        confirm_module._service._proposals.get(request.proposal_id) is not None
    ):
        # A staged proposal whose note file cannot be resolved has no provable
        # target under the seal: fail closed rather than let confirm run.
        raise capability_not_ready()
    try:
        response = confirm_module._service.confirm(request)
        if response.error == "authority_receipt_persistence_failed":
            raise HTTPException(status_code=500, detail={
                "error": response.error, "state": "not_acknowledged",
                "message": "The source was written but confirmation accountability requires reconciliation; do not retry the source.",
                "trace_id": response.trace_id,
                "source_state": response.source_state,
                "source_receipt": asdict(response.source_receipt) if response.source_receipt else None,
            })
        return response
    except RestageRequiredError as exc:
        raise HTTPException(
            status_code=409,
            detail={"error": "restage_required", "proposal_id": str(exc)},
        )
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


@router.post(
    "/checkbox-projection",
    response_model=CheckboxProjectionResponse,
    dependencies=[Depends(require_loopback_or_api_key)],
)
async def panel_checkbox_projection(
    request: CheckboxProjectionRequest,
    http_request: Request,
) -> CheckboxProjectionResponse:
    # SQ review reads and writes must stay inside the exact vault authorized by
    # the mutation seal. Never resolve the process-global selection here: a
    # concurrent or stale selector could point at a different vault.
    sealed_root = getattr(http_request.state, "compatibility_write_root", None)
    preflight = None
    vault_root = Path(sealed_root) if sealed_root is not None else None
    if request.review_question_id is not None:
        if vault_root is None:
            # The legacy pre-registry/pre-floor seal has no durable binding to
            # prove. Do not let a Question acceptance fall through to ordinary
            # checkbox projection or resolve the process-global selection.
            raise capability_not_ready()
        try:
            replay = accepted_question_receipt(request, vault_root=vault_root)
            if replay is not None:
                return CheckboxProjectionResponse(
                    status="executed",
                    artifact_id=request.artifact_id,
                    note_path=request.note_path,
                    panel_id=request.panel_id,
                    option_id=request.option_id,
                    content_hash_before=request.expected_content_hash,
                    content_hash_after=request.expected_content_hash,
                    receipt=replay,
                    idempotency_key=request.idempotency_key,
                )
            reconciled = reconcile_missing_question_acceptance(
                request,
                vault_root=vault_root,
            )
            if reconciled is not None:
                _sync_standing_question_projection(Path(vault_root))
                return CheckboxProjectionResponse(
                    status="executed",
                    artifact_id=request.artifact_id,
                    note_path=request.note_path,
                    panel_id=request.panel_id,
                    option_id=request.option_id,
                    content_hash_before=request.expected_content_hash,
                    content_hash_after=request.expected_content_hash,
                    receipt=reconciled,
                    idempotency_key=request.idempotency_key,
                )
            preflight = prepare_question_acceptance(
                request,
                vault_root=vault_root,
            )
        except QuestionReviewError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    try:
        if preflight is not None and preflight.already_projected:
            checked_note = preflight.draft_path.read_text(encoding="utf-8")
            normalized = checked_note.replace("\r\n", "\n").replace("\r", "\n")
            response = CheckboxProjectionResponse(
                status="already_projected",
                artifact_id=request.artifact_id,
                note_path=request.note_path,
                panel_id=request.panel_id,
                option_id=request.option_id,
                content_hash_before=request.expected_content_hash,
                content_hash_after=content_hash(normalized),
                idempotency_key=request.idempotency_key,
            )
        else:
            response = checkbox_projection_module._service.project(
                request,
                sealed_root=sealed_root,
                execute_runtime=preflight is None,
                legacy_standing_question_acceptance=(
                    (
                        request.option_id,
                        f"Accept this draft into the vault (draft {request.artifact_id[:12]})",
                    )
                    if preflight is not None
                    else None
                ),
            )
    except CheckboxProjectionHTTPError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=exc.response.model_dump(mode="json"),
        ) from exc
    if preflight is not None and response.status in {"projected", "already_projected"}:
        try:
            receipt = complete_question_acceptance(preflight, vault_root=vault_root)
        except QuestionReviewError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
        _sync_standing_question_projection(Path(vault_root))
        return response.model_copy(update={"status": "executed", "receipt": receipt})
    return response
