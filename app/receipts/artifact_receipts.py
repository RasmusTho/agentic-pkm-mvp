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
    record_source_label,
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

# Display-field fallbacks (#3363, Receipts v2). The UI must never invent a
# verb or run the runtime did not declare -- these are the honest defaults
# used only when the governed record does not carry enough to name either.
DISPLAY_VERB_FALLBACK = "Recorded"
RUN_LABEL_FALLBACK = "Run"

# Known reason/intent-type vocabulary already emitted by producers under
# app/curation and app/agents/panel_agent -- additive display-only mapping,
# never a re-classification of the record's own status/state/action_type.
_VERB_BY_REASON: dict[str, str] = {
    "curation_finding_proposed": "Proposed",
}
_VERB_BY_INTENT_TYPE: dict[str, str] = {
    "append": "Appended to",
    "create": "Created",
    "link": "Linked",
    "zone_move": "Moved",
}

# Known emitter component labels (app.events.schema source / PanelEventSource
# component) mapped to a human run label. Anything else falls back to
# RUN_LABEL_FALLBACK rather than guessing.
_RUN_LABEL_BY_SOURCE: dict[str, str] = {
    "panel_agent.confirmation": "Governed capture",
    "curation.proposal_writer": "Curation pass",
}


def _display_verb(event: str, payload: dict[str, Any]) -> str:
    if event == "panel.action.blocked":
        return "Blocked"
    declared = first_str(payload.get("display_verb"), payload.get("verb"))
    if declared:
        return declared
    intent_type = first_str(
        payload.get("intent_type"),
        nested(payload, "action", "intent_type"),
        nested(payload, "mapping", "intent_type"),
    )
    if intent_type:
        mapped = _VERB_BY_INTENT_TYPE.get(intent_type.strip().lower())
        if mapped:
            return mapped
    reason = first_str(payload.get("reason"))
    if reason:
        mapped_reason = _VERB_BY_REASON.get(reason)
        if mapped_reason:
            return mapped_reason
    return DISPLAY_VERB_FALLBACK


def _run_label(record: dict[str, Any], payload: dict[str, Any]) -> str:
    declared = first_str(payload.get("run_label"))
    if declared:
        return declared
    source_label = record_source_label(record)
    if source_label:
        mapped = _RUN_LABEL_BY_SOURCE.get(source_label)
        if mapped:
            return mapped
    return RUN_LABEL_FALLBACK


def _run_key(record: dict[str, Any], payload: dict[str, Any], receipt_id: str) -> str:
    declared = first_str(payload.get("run_key"))
    if declared:
        return declared
    trace_id = first_str(record.get("trace_id"), payload.get("trace_id"))
    return trace_id or receipt_id


def _target_absolute(raw_target: str | None, *, vault_root: Path) -> str | None:
    if not raw_target:
        return None
    path = Path(raw_target).expanduser()
    if path.is_absolute():
        return path.as_posix()
    return (vault_root / path).as_posix()


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
    raw_target = first_str(
        payload.get("artifact_path"),
        payload.get("note_path"),
        payload.get("path"),
        nested(payload, "note", "path"),
        nested(payload, "artifact_linkage", "note_path"),
    )
    artifact_path = normalize_note_path(raw_target, vault_root=vault_root)
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
        # Additive display fields (#3363, Receipts v2) -- always declared with
        # documented fallbacks; existing fields above keep their names/values.
        "display_verb": _display_verb(event, payload),
        "run_key": _run_key(record, payload, receipt_id),
        "run_label": _run_label(record, payload),
        "target_absolute": _target_absolute(raw_target, vault_root=vault_root),
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


__all__ = [
    "ArtifactReceiptTarget",
    "DISPLAY_VERB_FALLBACK",
    "RUN_LABEL_FALLBACK",
    "receipts_for_artifacts",
]
