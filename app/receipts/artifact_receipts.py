"""Read-only per-artifact receipt projection over governed outbox records."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from app.receipts.outbox_sources import (
    first_str,
    nested,
    normalize_note_path,
    read_receipt_source_records,
    record_event,
    record_payload,
)
from app.receipts.promotion_receipts import query_promotion_receipts


@dataclass(frozen=True)
class ArtifactReceiptTarget:
    artifact_uuid: str | None
    note_path: str


_RECEIPT_SUPPORTING_EVENTS = {
    "panel.action.blocked",
    "panel.action.logged",
}


def receipts_for_artifacts(
    targets: Iterable[ArtifactReceiptTarget],
    *,
    vault_root: Path,
    outbox_path: Path | None = None,
) -> dict[str, list[dict[str, str | None]]] | None:
    """Return receipt rows keyed by target note path.

    ``None`` means no receipt-supporting source is available, so callers should
    preserve the honest "unavailable" state. An empty list for a target means a
    source exists and no matching receipt was found.
    """

    target_list = list(targets)
    if not target_list:
        return {}

    records = read_receipt_source_records(outbox_path=outbox_path)
    if records is None:
        return None

    path_targets = {normalize_note_path(target.note_path, vault_root=vault_root): target for target in target_list}
    uuid_targets = {
        str(target.artifact_uuid).strip(): target
        for target in target_list
        if target.artifact_uuid and str(target.artifact_uuid).strip()
    }
    result: dict[str, list[dict[str, str | None]]] = {
        target.note_path: [] for target in target_list
    }
    seen: dict[str, set[str]] = {target.note_path: set() for target in target_list}

    for record in records:
        projected = _project_receipt_record(record, vault_root=vault_root)
        if projected is None:
            continue
        receipt, artifact_uuid, artifact_path = projected
        matched: set[str] = set()
        if artifact_uuid and artifact_uuid in uuid_targets:
            matched.add(uuid_targets[artifact_uuid].note_path)
        if artifact_path and artifact_path in path_targets:
            matched.add(path_targets[artifact_path].note_path)
        if not matched:
            continue
        receipt_id = str(receipt.get("receipt_id") or "")
        for note_path in matched:
            if receipt_id in seen[note_path]:
                continue
            result[note_path].append(dict(receipt))
            seen[note_path].add(receipt_id)

    promotion_projection = query_promotion_receipts(vault_root=vault_root, records=records)
    for row in promotion_projection.rows:
        receipt = row.to_artifact_receipt()
        promotion_matched: set[str] = set()
        if row.artifact_uuid and row.artifact_uuid in uuid_targets:
            promotion_matched.add(uuid_targets[row.artifact_uuid].note_path)
        if row.artifact_path and row.artifact_path in path_targets:
            promotion_matched.add(path_targets[row.artifact_path].note_path)
        if not promotion_matched:
            continue
        receipt_id = str(receipt.get("receipt_id") or "")
        for note_path in promotion_matched:
            if receipt_id in seen[note_path]:
                continue
            result[note_path].append(dict(receipt))
            seen[note_path].add(receipt_id)

    for rows in result.values():
        rows.sort(key=lambda row: str(row.get("timestamp") or ""))
    return result


def _project_receipt_record(
    record: dict[str, Any],
    *,
    vault_root: Path,
) -> tuple[dict[str, str | None], str | None, str | None] | None:
    event = record_event(record)
    if event not in _RECEIPT_SUPPORTING_EVENTS:
        return None
    payload = record_payload(record)
    artifact_uuid = first_str(
        payload.get("artifact_uuid"),
        payload.get("note_uuid"),
        nested(payload, "note", "uuid"),
        nested(payload, "artifact_linkage", "note_uuid"),
    )
    artifact_path = normalize_note_path(
        first_str(
            payload.get("artifact_path"),
            payload.get("note_path"),
            payload.get("path"),
            nested(payload, "note", "path"),
            nested(payload, "artifact_linkage", "note_path"),
        ),
        vault_root=vault_root,
    )
    if not artifact_uuid and not artifact_path:
        return None

    status, state = _status_and_state(event, payload)
    trace_id = first_str(record.get("trace_id"), payload.get("trace_id"))
    action_id = first_str(
        payload.get("action_id"),
        payload.get("intent_event_id"),
        payload.get("source_event"),
        nested(payload, "action", "id"),
        event,
    )
    timestamp = first_str(record.get("timestamp"), record.get("created_at")) or ""
    receipt_id = first_str(payload.get("receipt_id"), record.get("event_id"))
    if not receipt_id:
        receipt_id = f"{event}:{trace_id or 'no-trace'}:{artifact_uuid or artifact_path}:{timestamp}"

    receipt = {
        "receipt_id": receipt_id,
        "trace_id": trace_id,
        "action_id": action_id,
        "action_type": event,
        "artifact_uuid": artifact_uuid,
        "artifact_path": artifact_path,
        "path": artifact_path,
        "requested_by": _requested_by(record, payload),
        "approved_by": first_str(payload.get("approved_by"), nested(payload, "authority", "approved_by")),
        "status": status,
        "timestamp": timestamp,
        "state": state,
    }
    return receipt, artifact_uuid, artifact_path


def _status_and_state(event: str, payload: dict[str, Any]) -> tuple[str, str]:
    if event == "panel.action.blocked":
        return "blocked", "blocked"
    if event == "panel.action.logged":
        return first_str(payload.get("status"), payload.get("outcome"), "logged") or "logged", "applied"
    raw = first_str(
        nested(payload, "outcome", "status"),
        payload.get("status"),
        payload.get("effect"),
        "applied",
    ) or "applied"
    if raw in {"applied", "queued", "blocked", "rejected", "failed"}:
        return raw, raw
    if raw == "ok":
        return raw, "applied"
    if raw == "failure":
        return raw, "failed"
    if raw == "degraded":
        return raw, "blocked"
    return raw, "applied"


def _requested_by(record: dict[str, Any], payload: dict[str, Any]) -> str | None:
    return first_str(
        payload.get("requested_by"),
        nested(payload, "authority", "requested_by"),
        nested(payload, "authority", "component"),
        record.get("source"),
    )


__all__ = ["ArtifactReceiptTarget", "receipts_for_artifacts"]
