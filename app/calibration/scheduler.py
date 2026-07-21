"""Read-only scheduling of time-based decision revisits."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from uuid import UUID

from app.calibration.ladder import DEFAULT_REVISIT_LADDER
from app.objects import DomainObject, ObjectStore
from app.receipts.outcome_receipt_log import iter_outcome_receipts
from app.receipts.revisit_dismissal_log import iter_revisit_dismissals

ReceiptReader = Callable[[Path | None], list[dict[str, Any]]]


@dataclass(frozen=True)
class DecisionForRevisit:
    decision_object_id: UUID
    decision_uuid: UUID
    decided_on: date
    title: str


@dataclass(frozen=True)
class RevisitDue:
    decision_object_id: UUID
    decision_uuid: UUID
    title: str
    decided_on: date
    rung_index: int
    rung_days: int
    due_since: date


def _as_decision(raw: object) -> DecisionForRevisit | None:
    if isinstance(raw, DomainObject):
        payload: Mapping[str, Any] = raw.payload
        frontmatter = payload.get("frontmatter")
        if not isinstance(frontmatter, Mapping) or frontmatter.get("artifact_class") != "decision_record":
            return None
        value: Mapping[str, Any] = {
            "decision_object_id": raw.uuid,
            "decision_uuid": frontmatter.get("uuid"),
            "decided_on": frontmatter.get("decided_on"),
            "title": payload.get("title") or frontmatter.get("title") or raw.source_ref or "Untitled decision",
        }
    elif isinstance(raw, Mapping):
        value = raw
    else:
        return None
    try:
        return DecisionForRevisit(
            decision_object_id=UUID(str(value["decision_object_id"])),
            decision_uuid=UUID(str(value["decision_uuid"])),
            decided_on=date.fromisoformat(str(value["decided_on"])),
            title=str(value.get("title") or "Untitled decision"),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _actioned_rungs(
    decision: DecisionForRevisit,
    records: Iterable[Mapping[str, Any]],
) -> set[int]:
    actioned: set[int] = set()
    for record in records:
        # Match on the durable ``decision_uuid`` only, never the re-mintable
        # ``decision_object_id``. The dual-identity model exists precisely so a
        # Postgres rebuild can re-link a decision whose runtime id was re-minted
        # (see DECISION_CALIBRATION/DEFINE_OUTCOME_RECEIPT_MODEL.md), and the
        # sibling dedup functions (_existing_receipt / _existing_dismissal) key on
        # decision_uuid + rung_index alone. Requiring decision_object_id here would
        # let an actioned rung resurface once the object id changes.
        if str(record.get("decision_uuid")) != str(decision.decision_uuid):
            continue
        rung_index = record.get("rung_index")
        if isinstance(rung_index, int) and not isinstance(rung_index, bool) and rung_index >= 0:
            actioned.add(rung_index)
    return actioned


def next_pending_revisit(
    decision: object,
    *,
    today: date | None = None,
    vault_root: Path | None = None,
    outcome_records: list[dict[str, Any]] | None = None,
    dismissal_records: list[dict[str, Any]] | None = None,
) -> RevisitDue | None:
    """Return only the earliest due, un-actioned rung for one decision."""
    parsed = _as_decision(decision)
    if parsed is None:
        return None
    as_of = today or date.today()
    outcomes = outcome_records if outcome_records is not None else iter_outcome_receipts(vault_root)
    dismissals = (
        dismissal_records
        if dismissal_records is not None
        else iter_revisit_dismissals(vault_root)
    )
    actioned = _actioned_rungs(parsed, [*outcomes, *dismissals])
    for rung_index, rung_days in enumerate(DEFAULT_REVISIT_LADDER):
        due_since = parsed.decided_on + timedelta(days=rung_days)
        if rung_index not in actioned and due_since <= as_of:
            return RevisitDue(
                decision_object_id=parsed.decision_object_id,
                decision_uuid=parsed.decision_uuid,
                title=parsed.title,
                decided_on=parsed.decided_on,
                rung_index=rung_index,
                rung_days=rung_days,
                due_since=due_since,
            )
    return None


def due_revisits(
    *,
    today: date | None = None,
    vault_root: Path | None = None,
    decisions: Iterable[object] | None = None,
    outcome_reader: ReceiptReader = iter_outcome_receipts,
    dismissal_reader: ReceiptReader = iter_revisit_dismissals,
) -> list[RevisitDue]:
    """Return the one pending revisit, if any, for each ingested decision record."""
    candidates = decisions if decisions is not None else ObjectStore().list_objects(limit=1_000_000)
    outcomes = outcome_reader(vault_root)
    dismissals = dismissal_reader(vault_root)
    due: list[RevisitDue] = []
    for decision in candidates:
        pending = next_pending_revisit(
            decision,
            today=today,
            outcome_records=outcomes,
            dismissal_records=dismissals,
        )
        if pending is not None:
            due.append(pending)
    return due


__all__ = [
    "DEFAULT_REVISIT_LADDER",
    "DecisionForRevisit",
    "RevisitDue",
    "due_revisits",
    "next_pending_revisit",
]
