"""Pending eval-drafts review surface (KERNEL-15 follow-up, #2871).

Read surface + decision wiring over the file-based eval-draft artifacts
written by ``app.eval.failure_capture`` (KERNEL-15, #2777, PR #2867). Lists
pending drafts from ``<vault_system_dir>/eval_drafts/*.md`` with their
provenance, and lets a reviewer adjudicate a listed draft through the
existing ``promote_draft`` / ``reject_draft`` entrypoints.

HARD CONSTRAINT: eval drafts are a distinct artifact class from memory
candidates. This module must never import or route through
``app.agent_memory.review_queue.MemoryCandidateReviewQueue`` or
``app.agent_memory.materialization.materialize_promoted_memory`` — see the
"Deliberate divergence" section in ``app/eval/failure_capture.py`` and the
"Reviewer surfacing" section in
``docs/RUNTIME_CORRECTNESS_KERNEL/FAILURE_TO_EVAL_CAPTURE_LOOP.md``.

The listing route is a pure read (P-3 read-purity property,
``tests/properties/test_read_purity.py``): it only scans and parses files
under ``eval_drafts/`` via ``list_pending_drafts``/``read_draft``, neither of
which touches a durable-write primitive. The decision route is a POST and
therefore out of P-3's GET-only scope; its write goes through
``promote_draft``/``reject_draft``, which are already WriteGuard-gated at the
``app.eval.failure_capture`` write seam. Its reviewer actor is derived from the
authenticated auth/GOV principal boundary; a client ``decided_by`` value is
only an optional assertion of that server-derived identity.

Review UI (W7/W8) and auto-promotion are out of scope.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.api.compatibility_mutation import seal_vault_mutation
from app.vault.manager import nearest_enclosing_vault_root
from app.api.request_active_context import (
    current_scoped_route_read,
    route_read_vault_root_or_selection_required,
    scoped_route_read,
)
from app.api.routes.active_context_selection import build_selection_service, get_selection_store
from app.auth import api_key_header, resolve_auth_subject
from app.api.routes.vault_resolution import compatibility_vault_root_or_selection_required
from app.eval.failure_capture import (
    DRAFT_DIR_NAME,
    DraftEvalCase,
    DRAFT_STATUS_PENDING,
    DRAFT_STATUS_PROMOTED,
    DRAFT_STATUS_REJECTED,
    FailureCaptureError,
    PromotionDecision,
    PromotionDecisionError,
    list_pending_drafts,
    promote_draft,
    read_draft,
    reconcile_pending_disposition_receipt,
    reject_draft,
)
from app.knowledge.errors import KnowledgeWriteConflict
from app.instance.local_operator_principal import PrincipalPreflightError
from app.vault.paths import get_vault_system_dir_rel

# MVR-05B3: the decision route is a vault-bound mutation and carries the pre-05C
# seal; the listing route reads its own ActiveContextSet when it carries one.
router = APIRouter(
    prefix="/eval-drafts",
    tags=["eval-drafts"],
    dependencies=[Depends(seal_vault_mutation)],
)


class EvalDraftSourceEvent(BaseModel):
    topic: str
    event_id: str


class EvalDraftProjection(BaseModel):
    """Bounded provenance projection of one pending eval draft.

    Deliberately excludes ``payload_snapshot`` from the list surface — the
    listing is a discoverability index, not a full-content dump; a reviewer
    reads the full draft note (``draft_path``) directly for payload detail.
    """

    draft_id: str
    kind: str
    trace_id: str | None = None
    source_event: EvalDraftSourceEvent
    status: str
    created_at: str
    draft_path: str | None = None


class PendingEvalDraftsResponse(BaseModel):
    source: Literal["eval.failure_capture.eval_drafts"] = "eval.failure_capture.eval_drafts"
    pending_count: int
    drafts: list[EvalDraftProjection] = Field(default_factory=list)


class EvalDraftDecisionRequest(BaseModel):
    action: Literal["promote", "reject"]
    # Optional assertion for clients that already know the server-derived principal. The
    # route never treats this client field as authority; it derives the actor below.
    decided_by: str | None = Field(default=None, min_length=1)
    notes: str | None = None


class EvalDraftDecisionResponse(BaseModel):
    draft_id: str
    decision: str
    decided_by: str
    decided_at: str
    notes: str | None = None


def _projection(draft: DraftEvalCase) -> EvalDraftProjection:
    return EvalDraftProjection(
        draft_id=draft.draft_id,
        kind=draft.kind,
        trace_id=draft.trace_id,
        source_event=EvalDraftSourceEvent(
            topic=draft.source_event.topic, event_id=draft.source_event.event_id
        ),
        status=draft.status,
        created_at=draft.created_at,
        draft_path=draft.draft_path,
    )


def _authenticated_principal_id(
    request: Request,
    api_key: str | None,
) -> str:
    """Resolve the actor through the existing auth/GOV principal boundary."""
    if not os.getenv("INSTANCE_VAULT_REGISTRY_PATH", "").strip():
        raise HTTPException(
            status_code=503,
            detail="instance registry is not bound on this process",
        )
    try:
        subject = resolve_auth_subject(request, api_key)
        derived = build_selection_service(get_selection_store()).derive(
            subject,
            presented_credential=api_key,
        )
    except PrincipalPreflightError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return derived.principal.principal_id


def _reconcile_matching_terminal_decision(
    vault_root: Path,
    draft_id: str,
    *,
    action: Literal["promote", "reject"],
    actor: str,
    notes: str | None,
) -> PromotionDecision | None:
    """Recover only an exact retry of this principal's recorded decision."""
    draft = read_draft(vault_root, draft_id)
    if draft is None or draft.status == DRAFT_STATUS_PENDING:
        return None
    expected_status = (
        DRAFT_STATUS_PROMOTED if action == "promote" else DRAFT_STATUS_REJECTED
    )
    if (
        draft.status != expected_status
        or draft.decided_by != actor
        or draft.notes != notes
    ):
        return None
    return reconcile_pending_disposition_receipt(vault_root, draft_id)


def _scoped_drafts_dir_is_contained(vault_root: Path) -> bool:
    """Whether the drafts folder resolves inside the bound binding's root.

    The system folder may be overridden process-wide; a scoped read never
    follows such an override out of the binding it is bound to.
    """

    root = vault_root.resolve()
    try:
        drafts_dir = (vault_root / get_vault_system_dir_rel(vault_root) / DRAFT_DIR_NAME).resolve()
    except (OSError, ValueError):
        return False
    try:
        drafts_dir.relative_to(root)
    except ValueError:
        return False
    if drafts_dir == root:
        return False
    # An initialized nested child vault is a hard read boundary: a system folder
    # configured beneath one belongs to that child, not to this binding.
    return nearest_enclosing_vault_root(drafts_dir, search_root=root) == root


@router.get("", response_model=PendingEvalDraftsResponse)
@scoped_route_read
def get_pending_eval_drafts() -> PendingEvalDraftsResponse | JSONResponse:
    """Bounded read over pending eval-draft candidates awaiting review.

    Read-only: scans ``<vault_system_dir>/eval_drafts/*.md`` and parses
    frontmatter. Never writes. Distinct surface from
    ``GET /api/companion/memory/review-queue`` (memory candidates) — this
    route never touches ``MemoryCandidateReviewQueue``. A carrier-bearing
    request lists its own bound binding (MVR-05B3).
    """
    vault_root = route_read_vault_root_or_selection_required()
    if isinstance(vault_root, JSONResponse):
        return vault_root
    if current_scoped_route_read() is not None and not _scoped_drafts_dir_is_contained(vault_root):
        raise HTTPException(status_code=409, detail="active_context_read_unavailable")

    drafts = [_projection(d) for d in list_pending_drafts(vault_root)]
    return PendingEvalDraftsResponse(pending_count=len(drafts), drafts=drafts)


@router.post(
    "/{draft_id}/decision",
    response_model=EvalDraftDecisionResponse,
)
def post_eval_draft_decision(
    draft_id: str,
    req: EvalDraftDecisionRequest,
    request: Request,
    api_key: str | None = Depends(api_key_header),
) -> EvalDraftDecisionResponse | JSONResponse:
    """Record an explicit promote/reject decision on a pending eval draft.

    Routes through ``app.eval.failure_capture.promote_draft`` /
    ``reject_draft`` directly — never through the memory review queue's
    ``materialize_promoted_memory`` promotion path. A promoted eval draft's
    downstream golden-dataset writeback stays a separate, explicit, reviewed
    doc change (unchanged from KERNEL-15); this endpoint only records the
    review decision on the draft file itself.
    """
    authenticated_actor = _authenticated_principal_id(request, api_key)
    if req.decided_by is not None and req.decided_by != authenticated_actor:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "reviewer_identity_mismatch",
                "message": "decided_by must match the authenticated principal",
            },
        )
    # Sealed legacy write: the router dependency already proved the process
    # selection is the sole freshly revalidated compatibility binding.
    vault_root = compatibility_vault_root_or_selection_required()
    if isinstance(vault_root, JSONResponse):
        return vault_root

    decide = promote_draft if req.action == "promote" else reject_draft
    try:
        decision = _reconcile_matching_terminal_decision(
            vault_root,
            draft_id,
            action=req.action,
            actor=authenticated_actor,
            notes=req.notes,
        )
        if decision is None:
            try:
                decision = decide(
                    vault_root,
                    draft_id,
                    decided_by=authenticated_actor,
                    notes=req.notes,
                )
            except (KnowledgeWriteConflict, FailureCaptureError):
                # Another identical request may have completed the state-owner
                # mutation while this request was in flight, or this request
                # may have reached applied_receipt_pending. Recover only when
                # the authenticated actor and full decision match the durable
                # terminal draft; otherwise preserve the original refusal.
                recovered = _reconcile_matching_terminal_decision(
                    vault_root,
                    draft_id,
                    action=req.action,
                    actor=authenticated_actor,
                    notes=req.notes,
                )
                if recovered is None:
                    raise
                decision = recovered
    except KnowledgeWriteConflict as exc:
        if exc.receipt is None or exc.receipt.outcome != "conflict_staged":
            raise
        raise HTTPException(
            status_code=409,
            detail={"error": "eval_draft_decision_refused", "message": str(exc)},
        ) from exc
    except PromotionDecisionError as exc:
        raise HTTPException(
            status_code=409,
            detail={"error": "eval_draft_decision_refused", "message": str(exc)},
        ) from exc
    except FailureCaptureError as exc:
        raise HTTPException(
            status_code=409,
            detail={"error": "eval_draft_write_failed", "message": str(exc)},
        ) from exc

    return EvalDraftDecisionResponse(
        draft_id=decision.draft_id,
        decision=decision.decision,
        decided_by=decision.decided_by,
        decided_at=decision.decided_at,
        notes=decision.notes,
    )


__all__ = ["router"]
