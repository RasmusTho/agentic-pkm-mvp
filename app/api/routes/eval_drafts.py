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
``app.eval.failure_capture`` write seam.

Review UI (W7/W8) and auto-promotion are out of scope.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.api.routes.vault_resolution import active_vault_root_or_selection_required
from app.eval.failure_capture import (
    DraftEvalCase,
    FailureCaptureError,
    PromotionDecisionError,
    list_pending_drafts,
    promote_draft,
    reject_draft,
)

router = APIRouter(prefix="/eval-drafts", tags=["eval-drafts"])


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
    decided_by: str
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


@router.get("", response_model=PendingEvalDraftsResponse)
def get_pending_eval_drafts() -> PendingEvalDraftsResponse | JSONResponse:
    """Bounded read over pending eval-draft candidates awaiting review.

    Read-only: scans ``<vault_system_dir>/eval_drafts/*.md`` and parses
    frontmatter. Never writes. Distinct surface from
    ``GET /api/companion/memory/review-queue`` (memory candidates) — this
    route never touches ``MemoryCandidateReviewQueue``.
    """
    vault_root = active_vault_root_or_selection_required()
    if isinstance(vault_root, JSONResponse):
        return vault_root

    drafts = [_projection(d) for d in list_pending_drafts(vault_root)]
    return PendingEvalDraftsResponse(pending_count=len(drafts), drafts=drafts)


@router.post(
    "/{draft_id}/decision",
    response_model=EvalDraftDecisionResponse,
)
def post_eval_draft_decision(
    draft_id: str, req: EvalDraftDecisionRequest
) -> EvalDraftDecisionResponse | JSONResponse:
    """Record an explicit promote/reject decision on a pending eval draft.

    Routes through ``app.eval.failure_capture.promote_draft`` /
    ``reject_draft`` directly — never through the memory review queue's
    ``materialize_promoted_memory`` promotion path. A promoted eval draft's
    downstream golden-dataset writeback stays a separate, explicit, reviewed
    doc change (unchanged from KERNEL-15); this endpoint only records the
    review decision on the draft file itself.
    """
    vault_root = active_vault_root_or_selection_required()
    if isinstance(vault_root, JSONResponse):
        return vault_root

    decide = promote_draft if req.action == "promote" else reject_draft
    try:
        decision = decide(
            vault_root,
            draft_id,
            decided_by=req.decided_by,
            notes=req.notes,
        )
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
