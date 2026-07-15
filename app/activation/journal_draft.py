"""Activation record for the journal-specific proposal writer (JRNL-03)."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Mapping
from uuid import uuid4

from app.activation.gate import (
    ActivationDecision,
    ActivationPosture,
    CandidateContext,
    ConsumingAuthority,
    evaluate_activation,
)
from app.agent_memory.candidate import ReviewState


JOURNAL_DRAFT_CAPABILITY_ID = "journal_draft_proposal"
JOURNAL_DRAFT_SCOPE = "journaling.draft.staging"
JOURNAL_DRAFT_RECEIPT_EVENT = "activation.journaling.draft_gate_record"
JOURNAL_DRAFT_RECEIPT_SOURCE = "app.activation.journal_draft"


def build_journal_draft_posture(
    *,
    admissibility_declared: bool = True,
    loop_precondition_green: bool = True,
    observable: bool = True,
) -> ActivationPosture:
    """Declare JRNL-03 independently at proposal authority.

    This is deliberately not Create's ``synthesis_note_proposal`` record: the
    journal draft has its own caller, input contract, and staged artifact class.
    """

    return ActivationPosture(
        capability_id=JOURNAL_DRAFT_CAPABILITY_ID,
        declared_authority=ConsumingAuthority.PROPOSAL,
        admissibility_declared=admissibility_declared,
        loop_precondition_green=loop_precondition_green,
        reversible_write_path=True,
        observable=observable,
        scope=JOURNAL_DRAFT_SCOPE,
    )


def evaluate_journal_draft_activation(
    source_ids: Iterable[str],
    *,
    review_states: Mapping[str, ReviewState | None] | None = None,
    posture: ActivationPosture | None = None,
    receipt_id: str | None = None,
    now: datetime | None = None,
) -> ActivationDecision:
    """Return the deterministic activation decision and decision receipt."""

    resolved = posture or build_journal_draft_posture()
    source_review_states = review_states or {}
    candidates = [
        CandidateContext(
            artifact_id=source_id.strip(),
            sphere=resolved.scope or JOURNAL_DRAFT_SCOPE,
            is_memory=False,
            has_provenance=True,
            # A missing declaration stays unknown/read-only. Production
            # callers explicitly identify owner transcripts and draft captures
            # as raw/unreviewed; absence must not become cited-proposal input.
            review_state=source_review_states.get(source_id.strip()),
        )
        for source_id in source_ids
        if source_id.strip()
    ]
    return evaluate_activation(resolved, candidates, receipt_id=receipt_id, now=now)


def build_journal_draft_receipt_record(
    decision: ActivationDecision,
) -> dict[str, object]:
    """Build the content-free durable record embedded with the draft.

    The shape mirrors Expansion's append-only activation receipt. JRNL-03
    embeds it in the atomically replaced proposal so a draft can never point
    at a receipt that was lost in a separate write transaction.
    """

    receipt = decision.receipt
    return {
        "event": JOURNAL_DRAFT_RECEIPT_EVENT,
        "event_id": receipt.receipt_id,
        "trace_id": uuid4().hex,
        "source": JOURNAL_DRAFT_RECEIPT_SOURCE,
        "timestamp": receipt.created_at.astimezone(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
        "payload": {
            "capability_id": decision.capability_id,
            "consuming_authority": receipt.consuming_authority.value,
            "outcome": receipt.outcome,
            "activatable": decision.activatable,
            "blocked_reasons": list(decision.blocked_reasons),
            "admitted_artifact_ids": list(decision.admitted_artifact_ids),
        },
    }


__all__ = [
    "JOURNAL_DRAFT_CAPABILITY_ID",
    "JOURNAL_DRAFT_RECEIPT_EVENT",
    "JOURNAL_DRAFT_SCOPE",
    "build_journal_draft_receipt_record",
    "build_journal_draft_posture",
    "evaluate_journal_draft_activation",
]
