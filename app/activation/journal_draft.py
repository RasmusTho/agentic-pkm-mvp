"""Activation record for the journal-specific proposal writer (JRNL-03)."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

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
    posture: ActivationPosture | None = None,
    receipt_id: str | None = None,
    now: datetime | None = None,
) -> ActivationDecision:
    """Return the deterministic activation decision and decision receipt."""

    resolved = posture or build_journal_draft_posture()
    candidates = [
        CandidateContext(
            artifact_id=source_id.strip(),
            sphere=resolved.scope or JOURNAL_DRAFT_SCOPE,
            is_memory=False,
            has_provenance=True,
            review_state=ReviewState.REVIEWED,
        )
        for source_id in source_ids
        if source_id.strip()
    ]
    return evaluate_activation(resolved, candidates, receipt_id=receipt_id, now=now)


__all__ = [
    "JOURNAL_DRAFT_CAPABILITY_ID",
    "JOURNAL_DRAFT_SCOPE",
    "build_journal_draft_posture",
    "evaluate_journal_draft_activation",
]
