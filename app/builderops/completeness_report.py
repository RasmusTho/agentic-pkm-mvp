"""Observe-only completeness report for learning and reevaluation signals."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any, Mapping

from app.builderops.epic_run_state import TERMINAL_LEARNING_EVALUATION_OUTCOMES
from app.builderops.store import SqliteBuilderOpsStore

RETROSPECTIVE_EVENT_TYPE = "learning_retrospective"
LEARNING_LOG_ENTRY_RE = re.compile(r"^##\s+\d{4}-\d{2}-\d{2}\s+.+$", re.MULTILINE)
RETRO_MARKER_RE = re.compile(r"^--- retro \d{4}-\d{2}-\d{2}: applied \d+/\d+ proposals ---$", re.MULTILINE)


def build_completeness_report(
    *,
    records: list[Mapping[str, Any]] | None,
    storage: Mapping[str, Any] | None = None,
    learning_log_text: str | None = None,
    reevaluation_candidates: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Report unresolved learning/reevaluation signals without mutating sources."""

    storage_state = dict(storage or {"available": True, "source": "records"})
    if records is None:
        return {
            "observe_only": True,
            "mutations_performed": False,
            "storage": storage_state,
            "complete": False,
            "unprocessed_learning_signals": [],
            "retrospective_receipts_missing_terminal_outcomes": [],
            "reevaluation_candidates_without_outcome": [],
            "stale_compatibility_entries": [],
            "receipt_body": "Completeness report unavailable: BuilderOps storage unavailable.",
        }

    normalized_records = [dict(record) for record in records]
    learning_signals = [
        record for record in normalized_records
        if record.get("object_type") == "LearningSignal"
    ]
    retrospective_receipts = [
        record for record in normalized_records
        if record.get("object_type") == "BuilderOpsReceipt"
        and record.get("event_type") == RETROSPECTIVE_EVENT_TYPE
    ]

    receipt_reports = [
        _retrospective_receipt_report(receipt)
        for receipt in retrospective_receipts
    ]
    processed_signal_ids = {
        signal_id
        for receipt in receipt_reports
        for signal_id in receipt["terminal_signal_ids"]
    }
    unprocessed = [
        _signal_summary(signal)
        for signal in learning_signals
        if str(signal.get("id")) not in processed_signal_ids
    ]
    missing_terminal = [
        receipt for receipt in receipt_reports
        if receipt["missing_terminal_outcomes"]
    ]
    unresolved_candidates = [
        _candidate_summary(candidate)
        for candidate in (reevaluation_candidates or [])
        if candidate.get("outcome") not in TERMINAL_LEARNING_EVALUATION_OUTCOMES
    ]
    stale_entries = _stale_compatibility_entries(learning_log_text)
    complete = not (
        unprocessed
        or missing_terminal
        or unresolved_candidates
        or stale_entries
        or not storage_state.get("available", False)
    )

    return {
        "observe_only": True,
        "mutations_performed": False,
        "storage": storage_state,
        "complete": complete,
        "last_retrospective_receipt": _last_receipt_summary(retrospective_receipts),
        "unprocessed_learning_signals": unprocessed,
        "retrospective_receipts_missing_terminal_outcomes": missing_terminal,
        "reevaluation_candidates_without_outcome": unresolved_candidates,
        "stale_compatibility_entries": stale_entries,
        "terminal_outcomes": list(TERMINAL_LEARNING_EVALUATION_OUTCOMES),
        "receipt_body": _receipt_body(
            storage_state=storage_state,
            unprocessed=unprocessed,
            missing_terminal=missing_terminal,
            unresolved_candidates=unresolved_candidates,
            stale_entries=stale_entries,
        ),
    }


def load_records_from_db(db_path: Path) -> tuple[list[dict[str, Any]] | None, dict[str, Any]]:
    """Load BuilderOps records when storage exists; never create or initialize it."""

    if not db_path.exists():
        return None, {
            "available": False,
            "source": str(db_path),
            "reason": "missing_builderops_db",
        }
    try:
        records = SqliteBuilderOpsStore(db_path).list_records()
    except (sqlite3.Error, OSError, ValueError) as exc:
        return None, {
            "available": False,
            "source": str(db_path),
            "reason": "unreadable_builderops_db",
            "error": str(exc),
        }
    return records, {
        "available": True,
        "source": str(db_path),
        "record_count": len(records),
    }


def _retrospective_receipt_report(receipt: Mapping[str, Any]) -> dict[str, Any]:
    target_signal_ids = _target_signal_ids(receipt)
    outcomes = _terminal_outcomes_from_receipt(receipt)
    terminal_signal_ids = [
        signal_id for signal_id in target_signal_ids
        if outcomes.get(signal_id) in TERMINAL_LEARNING_EVALUATION_OUTCOMES
    ]
    return {
        "receipt_id": str(receipt.get("id")),
        "summary": receipt.get("summary"),
        "occurred_at": receipt.get("occurred_at"),
        "target_signal_ids": target_signal_ids,
        "terminal_outcomes": [
            {"signal_id": signal_id, "outcome": outcomes[signal_id]}
            for signal_id in terminal_signal_ids
        ],
        "terminal_signal_ids": terminal_signal_ids,
        "missing_terminal_outcomes": [
            signal_id for signal_id in target_signal_ids
            if signal_id not in terminal_signal_ids
        ],
    }


def _terminal_outcomes_from_receipt(receipt: Mapping[str, Any]) -> dict[str, str]:
    structured = receipt.get("processed_signal_outcomes")
    if isinstance(structured, list):
        outcomes: dict[str, str] = {}
        for item in structured:
            if not isinstance(item, Mapping):
                continue
            signal_id = item.get("signal_id")
            outcome = item.get("outcome")
            if isinstance(signal_id, str) and outcome in TERMINAL_LEARNING_EVALUATION_OUTCOMES:
                outcomes[signal_id] = outcome
        return outcomes

    body = receipt.get("receipt_body")
    if not isinstance(body, str):
        return {}
    allowed = "|".join(re.escape(outcome) for outcome in TERMINAL_LEARNING_EVALUATION_OUTCOMES)
    pattern = re.compile(rf"([A-Za-z0-9_.:-]+)=({allowed})")
    return {match.group(1): match.group(2) for match in pattern.finditer(body)}


def _target_signal_ids(receipt: Mapping[str, Any]) -> list[str]:
    refs = receipt.get("target_refs")
    if not isinstance(refs, list):
        return []
    signal_ids: list[str] = []
    for ref in refs:
        if not isinstance(ref, Mapping):
            continue
        ref_value = ref.get("ref")
        if ref.get("ref_type") == "builderops_object" and isinstance(ref_value, str):
            signal_ids.append(ref_value)
    return signal_ids


def _signal_summary(signal: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": signal.get("id"),
        "summary": signal.get("summary"),
        "created_at": signal.get("created_at"),
        "signal_type": signal.get("signal_type"),
    }


def _candidate_summary(candidate: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": candidate.get("id") or candidate.get("candidate_id"),
        "summary": candidate.get("summary"),
        "outcome": candidate.get("outcome"),
        "evidence_kind": candidate.get("evidence_kind") or candidate.get("route"),
        "upstream_artifact_hint": (
            candidate.get("upstream_artifact_hint") or candidate.get("upstream_artifact")
        ),
    }


def _last_receipt_summary(receipts: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not receipts:
        return None
    latest = max(
        receipts,
        key=lambda item: str(item.get("occurred_at") or item.get("created_at") or ""),
    )
    return {
        "id": latest.get("id"),
        "summary": latest.get("summary"),
        "occurred_at": latest.get("occurred_at"),
    }


def _stale_compatibility_entries(learning_log_text: str | None) -> list[dict[str, Any]]:
    if not learning_log_text:
        return []
    markers = list(RETRO_MARKER_RE.finditer(learning_log_text))
    start = markers[-1].end() if markers else 0
    tail = learning_log_text[start:]
    entries = []
    for match in LEARNING_LOG_ENTRY_RE.finditer(tail):
        entries.append({"heading": match.group(0).removeprefix("## ").strip()})
    return entries


def _receipt_body(
    *,
    storage_state: Mapping[str, Any],
    unprocessed: list[dict[str, Any]],
    missing_terminal: list[dict[str, Any]],
    unresolved_candidates: list[dict[str, Any]],
    stale_entries: list[dict[str, Any]],
) -> str:
    if not storage_state.get("available", False):
        return "Completeness report unavailable: BuilderOps storage unavailable."
    incomplete = (
        unprocessed
        or missing_terminal
        or unresolved_candidates
        or stale_entries
    )
    posture = "incomplete" if incomplete else "complete"
    return (
        f"Completeness report {posture}: "
        f"unprocessed_learning_signals={len(unprocessed)}, "
        f"receipts_missing_terminal_outcomes={len(missing_terminal)}, "
        f"reevaluation_candidates_without_outcome={len(unresolved_candidates)}, "
        f"stale_compatibility_entries={len(stale_entries)}."
    )


__all__ = [
    "RETROSPECTIVE_EVENT_TYPE",
    "build_completeness_report",
    "load_records_from_db",
]
