"""Carry ContextBundle linkage through the governed write-proposal path (#1564).

A context bundle may *support* a write proposal so the human can inspect the
evidence, but it must never *become* write authority. This module carries a
stable bundle reference through the production governed write-proposal lifecycle
while keeping the four states — propose / stage / apply / log — distinct and
keeping WriteGuard (``app/write_guard.py``) independently authoritative.

The apply step is the governed write boundary: it runs WriteGuard before any
write and refuses if ``may_write`` was somehow set. Executing the actual vault
write is deliberately out of scope for this slice (#1564) — apply only crosses
the governed boundary and records the distinct state transition.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.context_bundles.schema import ContextBundle
from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard
from app.writeback.bundle_proposal import (
    BundleProposalViolation,
    WriteProposal,
    build_write_proposal_from_bundle,
)

_APPLY_ACTION = "context_bundle_write_proposal_apply"


@dataclass
class GovernedProposalRecord:
    """A bundle-linked write proposal tracked through distinct lifecycle states.

    ``proposal`` carries the stable bundle reference (``proposal.bundle_id``) and
    the authority posture (``may_propose`` true, ``may_write`` false). ``state``
    advances strictly through proposed -> staged -> applied -> logged, and every
    transition is appended to ``log`` for an auditable trail.
    """

    proposal: WriteProposal
    state: str = "proposed"
    log: list[str] = field(default_factory=list)

    @property
    def bundle_id(self) -> str:
        return self.proposal.bundle_id


def propose_write_from_bundle(
    bundle: ContextBundle,
    *,
    affected_artifacts: list[str],
    proposal_basis: str,
) -> GovernedProposalRecord:
    """Create a governed write proposal carrying the bundle's stable reference.

    Delegates authority/scope gating to ``build_write_proposal_from_bundle``
    (requires ``may_propose``, rejects ``may_write`` and expired/mis-scoped
    bundles).
    """
    proposal = build_write_proposal_from_bundle(
        bundle,
        affected_artifacts=affected_artifacts,
        proposal_basis=proposal_basis,
    )
    record = GovernedProposalRecord(proposal=proposal, state="proposed")
    record.log.append("proposed")
    return record


def stage_proposal(record: GovernedProposalRecord) -> GovernedProposalRecord:
    """Advance a proposed write proposal to the distinct staged state."""
    if record.state != "proposed":
        raise BundleProposalViolation(
            f"stage requires a proposed proposal; current state={record.state!r}"
        )
    record.state = "staged"
    record.proposal.state = "staged"
    record.log.append("staged")
    return record


def apply_proposal(
    record: GovernedProposalRecord,
    *,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
) -> GovernedProposalRecord:
    """Cross the governed write boundary for a staged proposal.

    WriteGuard runs independently and remains authoritative — bundle linkage
    never bypasses it. Raises before advancing state if writes are blocked or if
    the proposal ever carried ``may_write``. No vault write is executed here
    (out of scope for #1564); only the governed boundary is crossed and the
    distinct ``applied`` state recorded.
    """
    if record.state != "staged":
        raise BundleProposalViolation(
            f"apply requires a staged proposal; current state={record.state!r}"
        )
    if record.proposal.may_write:
        raise BundleProposalViolation(
            f"proposal for bundle {record.bundle_id} carries may_write=True; "
            "bundle linkage must not grant write authority"
        )
    # Independent, authoritative governed write boundary.
    write_guard.assert_writes_allowed(_APPLY_ACTION)
    record.state = "applied"
    record.proposal.state = "applied"
    record.log.append("applied")
    return record


def log_proposal(record: GovernedProposalRecord) -> GovernedProposalRecord:
    """Record the applied proposal in the distinct logged state."""
    if record.state != "applied":
        raise BundleProposalViolation(
            f"log requires an applied proposal; current state={record.state!r}"
        )
    record.state = "logged"
    record.proposal.state = "logged"
    record.log.append("logged")
    return record


__all__ = [
    "GovernedProposalRecord",
    "propose_write_from_bundle",
    "stage_proposal",
    "apply_proposal",
    "log_proposal",
]
