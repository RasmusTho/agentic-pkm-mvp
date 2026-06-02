"""Typed read-only promotion receipt query projection."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from app.events.types import PROMOTION_TRANSITION_APPLIED
from app.receipts.outbox_sources import (
    first_str,
    nested,
    normalize_note_path,
    read_receipt_source_records,
    record_event,
    record_payload,
)


@dataclass(frozen=True)
class PromotionReceiptQuery:
    artifact_uuid: str | None = None
    artifact_path: str | None = None
    receipt_or_source_event_id: str | None = None
    trace_id: str | None = None
    transition_family: str | None = None
    target_maturity: str | None = None
    outcome_status: str | None = None


@dataclass(frozen=True)
class PromotionReceiptRow:
    receipt_id: str
    source_event_id: str | None
    trace_id: str | None
    timestamp: str
    artifact_uuid: str | None
    artifact_path: str | None
    transition_family: str | None
    target_maturity: str | None
    review_state: str | None
    maturity: str | None
    authority: dict[str, Any]
    basis: dict[str, Any]
    outcome: dict[str, Any]
    artifact_linkage: dict[str, Any]
    executor: str | None
    source: str | None
    triggering_intent_event_id: str | None

    @property
    def outcome_status(self) -> str | None:
        return first_str(self.outcome.get("status"))

    def to_artifact_receipt(self) -> dict[str, str | None]:
        status = self.outcome_status or "applied"
        state = status if status in {"applied", "queued", "blocked", "rejected", "failed"} else "applied"
        return {
            "receipt_id": self.receipt_id,
            "trace_id": self.trace_id,
            "action_id": self.triggering_intent_event_id or self.source_event_id,
            "action_type": PROMOTION_TRANSITION_APPLIED,
            "artifact_uuid": self.artifact_uuid,
            "artifact_path": self.artifact_path,
            "path": self.artifact_path,
            "requested_by": first_str(
                self.authority.get("requested_by"),
                self.authority.get("component"),
                self.source,
            ),
            "approved_by": first_str(self.authority.get("approved_by")),
            "status": status,
            "timestamp": self.timestamp,
            "state": state,
        }


@dataclass(frozen=True)
class PromotionReceiptQueryResult:
    source_available: bool
    rows: tuple[PromotionReceiptRow, ...] = ()
    non_authoritative_records: tuple[dict[str, str | None], ...] = field(default_factory=tuple)


def query_promotion_receipts(
    query: PromotionReceiptQuery | None = None,
    *,
    vault_root: Path,
    outbox_path: Path | None = None,
    records: Iterable[dict[str, Any]] | None = None,
) -> PromotionReceiptQueryResult:
    """Return typed promotion receipt rows derived from authoritative records.

    The v1 authority source is ``promotion.transition.applied``. Other records,
    including ``promote.done``, are intentionally ignored.
    """

    source_records = list(records) if records is not None else read_receipt_source_records(outbox_path=outbox_path)
    if source_records is None:
        return PromotionReceiptQueryResult(source_available=False)

    filters = query or PromotionReceiptQuery()
    rows: list[PromotionReceiptRow] = []
    non_authoritative: list[dict[str, str | None]] = []
    for record in source_records:
        event = record_event(record)
        if event != PROMOTION_TRANSITION_APPLIED:
            continue
        row, reason = _project_transition_applied(record, vault_root=vault_root)
        if row is None:
            non_authoritative.append({
                "event_id": first_str(record.get("event_id")),
                "trace_id": first_str(record.get("trace_id")),
                "reason": reason,
            })
            continue
        if _matches(row, filters):
            rows.append(row)

    rows.sort(key=lambda row: row.timestamp)
    return PromotionReceiptQueryResult(
        source_available=True,
        rows=tuple(rows),
        non_authoritative_records=tuple(non_authoritative),
    )


def _project_transition_applied(
    record: dict[str, Any],
    *,
    vault_root: Path,
) -> tuple[PromotionReceiptRow | None, str]:
    payload = record_payload(record)
    authority = payload.get("authority")
    basis = payload.get("basis")
    outcome = payload.get("outcome")
    artifact_linkage = payload.get("artifact_linkage")
    if not isinstance(authority, dict):
        return None, "missing_authority"
    if not isinstance(basis, dict):
        return None, "missing_basis"
    if not isinstance(outcome, dict):
        return None, "missing_outcome"
    if not isinstance(artifact_linkage, dict):
        return None, "missing_artifact_linkage"

    artifact_uuid = first_str(
        payload.get("artifact_uuid"),
        payload.get("note_uuid"),
        nested(payload, "note", "uuid"),
        artifact_linkage.get("artifact_uuid"),
        artifact_linkage.get("note_uuid"),
    )
    artifact_path = normalize_note_path(
        first_str(
            payload.get("artifact_path"),
            payload.get("note_path"),
            payload.get("path"),
            nested(payload, "note", "path"),
            artifact_linkage.get("artifact_path"),
            artifact_linkage.get("note_path"),
        ),
        vault_root=vault_root,
    )
    if not artifact_uuid and not artifact_path:
        return None, "missing_artifact_identity"

    receipt_id = first_str(payload.get("receipt_id"), record.get("event_id"))
    if not receipt_id:
        return None, "missing_receipt_or_event_id"
    timestamp = first_str(record.get("timestamp"), record.get("created_at"))
    if not timestamp:
        return None, "missing_timestamp"

    source_event_id = first_str(
        payload.get("source_event"),
        payload.get("intent_event_id"),
        basis.get("source_event"),
        record.get("event_id"),
    )
    trace_id = first_str(record.get("trace_id"), payload.get("trace_id"))
    target_maturity = first_str(payload.get("target_maturity"), outcome.get("maturity"))
    triggering_intent = first_str(payload.get("intent_event_id"), basis.get("source_event"))
    return (
        PromotionReceiptRow(
            receipt_id=receipt_id,
            source_event_id=source_event_id,
            trace_id=trace_id,
            timestamp=timestamp,
            artifact_uuid=artifact_uuid,
            artifact_path=artifact_path,
            transition_family=first_str(payload.get("transition_family"), "promotion"),
            target_maturity=target_maturity,
            review_state=first_str(outcome.get("review_state")),
            maturity=first_str(outcome.get("maturity")),
            authority=dict(authority),
            basis=dict(basis),
            outcome=dict(outcome),
            artifact_linkage=dict(artifact_linkage),
            executor=first_str(payload.get("executor"), authority.get("executor")),
            source=_record_source(record),
            triggering_intent_event_id=triggering_intent,
        ),
        "",
    )


def _record_source(record: dict[str, Any]) -> str | None:
    source = record.get("source")
    if isinstance(source, dict):
        return first_str(source.get("component"), source.get("name"), source.get("trigger"))
    return first_str(source)


def _matches(row: PromotionReceiptRow, query: PromotionReceiptQuery) -> bool:
    if query.artifact_uuid and query.artifact_uuid != row.artifact_uuid:
        return False
    if query.artifact_path and query.artifact_path != row.artifact_path:
        return False
    if query.receipt_or_source_event_id:
        values = {
            row.receipt_id,
            row.source_event_id,
            row.triggering_intent_event_id,
        }
        if query.receipt_or_source_event_id not in values:
            return False
    if query.trace_id and query.trace_id != row.trace_id:
        return False
    if query.transition_family and query.transition_family != row.transition_family:
        return False
    if query.target_maturity and query.target_maturity != row.target_maturity:
        return False
    if query.outcome_status and query.outcome_status != row.outcome_status:
        return False
    return True


__all__ = [
    "PromotionReceiptQuery",
    "PromotionReceiptQueryResult",
    "PromotionReceiptRow",
    "query_promotion_receipts",
]
