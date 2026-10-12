"""Observe-only completeness report for learning and reevaluation signals."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any, Mapping

from app.builderops.epic_run_state import TERMINAL_LEARNING_EVALUATION_OUTCOMES
from app.builderops.models import (
    SUCCESSOR_REF_TYPES,
    TERMINAL_SIGNAL_LIFECYCLE_STATES,
)
from app.builderops.store import SqliteBuilderOpsStore

RETROSPECTIVE_EVENT_TYPE = "learning_retrospective"
LEARNING_LOG_ENTRY_RE = re.compile(r"^##\s+\d{4}-\d{2}-\d{2}\s+.+$", re.MULTILINE)
RETRO_MARKER_RE = re.compile(r"^--- retro \d{4}-\d{2}-\d{2}: applied \d+/\d+ proposals ---$", re.MULTILINE)
SIGNAL_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]+$")
SIGNAL_OUTCOME_CLAIM_RE = re.compile(
    r"(?<![A-Za-z0-9_.:-])(?P<signal_id>[A-Za-z0-9_.:-]+)\s*=\s*(?P<outcome>[^\s,;|]*)"
)
MARKDOWN_TABLE_SEPARATOR_RE = re.compile(r":?-+:?")
PATTERN_ROUTING_RECEIPT_PREFIX = "Repeated-pattern routing observe-only report:"
ROUTES_SECTION_RE = re.compile(r";\s*routes\s*:")
TERMINAL_OUTCOMES_SECTION_RE = re.compile(r"\bterminal_outcomes\s*:")


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
            "terminal_signals_missing_successor_refs": [],
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
    missing_successors = [
        _terminal_signal_summary(signal)
        for signal in learning_signals
        if _terminal_signal_missing_successor(signal)
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
        or missing_successors
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
        "terminal_signals_missing_successor_refs": missing_successors,
        "reevaluation_candidates_without_outcome": unresolved_candidates,
        "stale_compatibility_entries": stale_entries,
        "terminal_outcomes": list(TERMINAL_LEARNING_EVALUATION_OUTCOMES),
        "receipt_body": _receipt_body(
            storage_state=storage_state,
            unprocessed=unprocessed,
            missing_terminal=missing_terminal,
            missing_successors=missing_successors,
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
        records = SqliteBuilderOpsStore(db_path, read_only=True).list_records()
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
        structured_claims: dict[str, set[str | None]] = {}
        for item in structured:
            if not isinstance(item, Mapping):
                continue
            signal_id = item.get("signal_id")
            outcome = item.get("outcome")
            if isinstance(signal_id, str) and signal_id:
                structured_claims.setdefault(signal_id, set()).add(
                    outcome
                    if isinstance(outcome, str)
                    and outcome in TERMINAL_LEARNING_EVALUATION_OUTCOMES
                    else None
                )
        return _unambiguous_terminal_outcomes(structured_claims)

    body = receipt.get("receipt_body")
    if not isinstance(body, str):
        return {}
    body_claims: dict[str, set[str | None]] = {}
    lines = body.splitlines()
    for line in lines:
        for match in SIGNAL_OUTCOME_CLAIM_RE.finditer(_outcome_token_text(line)):
            signal_id = match.group("signal_id")
            outcome = _recognized_outcome_token(match.group("outcome"))
            body_claims.setdefault(signal_id, set()).add(outcome)

    _add_markdown_table_outcome_claims(lines, body_claims)
    return _unambiguous_terminal_outcomes(body_claims)


def _recognized_outcome_token(value: str) -> str | None:
    # Permit one ordinary sentence-ending punctuation mark after a complete token,
    # while rejecting recognized prefixes such as "applied.extra".
    token = value[:-1] if value.endswith((".", "!", "?")) else value
    return token if token in TERMINAL_LEARNING_EVALUATION_OUTCOMES else None


def _outcome_token_text(line: str) -> str:
    """Ignore the pattern-routing producer's explicitly named route metadata."""

    if not line.startswith(PATTERN_ROUTING_RECEIPT_PREFIX):
        return line
    routes = ROUTES_SECTION_RE.search(line)
    if routes is None:
        return line
    terminal_outcomes = TERMINAL_OUTCOMES_SECTION_RE.search(line, routes.end())
    if terminal_outcomes is None:
        return line[:routes.start()]
    return line[:routes.start()] + " " + line[terminal_outcomes.end():]


def _unambiguous_terminal_outcomes(
    claims: Mapping[str, set[str | None]],
) -> dict[str, str]:
    resolved: dict[str, str] = {}
    for signal_id, outcomes in claims.items():
        if len(outcomes) != 1:
            continue
        outcome = next(iter(outcomes))
        if outcome is not None:
            resolved[signal_id] = outcome
    return resolved


def _add_markdown_table_outcome_claims(
    lines: list[str],
    claims: dict[str, set[str | None]],
) -> None:
    for line_index, line in enumerate(lines):
        header = _markdown_table_cells(line)
        if header is None:
            continue
        header_values = [_markdown_cell_value(cell) for cell in header]
        if (
            len(header_values) != 2
            or not all(valid for _, valid in header_values)
            or [value for value, _ in header_values] != ["signal_id", "outcome"]
        ):
            continue

        separator_index = line_index + 1
        separator = (
            _markdown_table_cells(lines[separator_index])
            if separator_index < len(lines)
            else None
        )
        valid_separator = bool(
            separator is not None
            and len(separator) == 2
            and all(MARKDOWN_TABLE_SEPARATOR_RE.fullmatch(cell) for cell in separator)
        )
        row_index = separator_index + 1 if valid_separator else separator_index
        while row_index < len(lines) and "|" in lines[row_index] and lines[row_index].strip():
            cells = _markdown_table_cells(lines[row_index])
            if cells:
                signal_id, signal_cell_valid = _markdown_cell_value(cells[0])
                if not signal_cell_valid:
                    signal_id = signal_id.strip("`")
                if SIGNAL_ID_PATTERN.fullmatch(signal_id):
                    outcome: str | None = None
                    if valid_separator and len(cells) == 2 and signal_cell_valid:
                        outcome_cell, outcome_cell_valid = _markdown_cell_value(cells[1])
                        if outcome_cell_valid and outcome_cell in TERMINAL_LEARNING_EVALUATION_OUTCOMES:
                            outcome = outcome_cell
                    claims.setdefault(signal_id, set()).add(outcome)
            row_index += 1


def _markdown_table_cells(line: str) -> list[str] | None:
    stripped = line.strip()
    if "|" not in stripped:
        return None
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def _markdown_cell_value(cell: str) -> tuple[str, bool]:
    value = cell.strip()
    if value.startswith("`") or value.endswith("`"):
        opening_fence = len(value) - len(value.lstrip("`"))
        closing_fence = len(value) - len(value.rstrip("`"))
        if opening_fence and opening_fence == closing_fence:
            content = value[opening_fence:-closing_fence]
            if "`" not in content:
                return content.strip(), True
        return value.strip("`").strip(), False
    return value, True


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


def _terminal_signal_missing_successor(signal: Mapping[str, Any]) -> bool:
    if signal.get("lifecycle_state") not in TERMINAL_SIGNAL_LIFECYCLE_STATES:
        return False
    successors = signal.get("successor_refs")
    if not isinstance(successors, list) or not successors:
        return True
    return not any(
        isinstance(ref, Mapping) and ref.get("ref_type") in SUCCESSOR_REF_TYPES
        for ref in successors
    )


def _terminal_signal_summary(signal: Mapping[str, Any]) -> dict[str, Any]:
    summary = _signal_summary(signal)
    summary["lifecycle_state"] = signal.get("lifecycle_state")
    return summary


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
    missing_successors: list[dict[str, Any]],
    unresolved_candidates: list[dict[str, Any]],
    stale_entries: list[dict[str, Any]],
) -> str:
    if not storage_state.get("available", False):
        return "Completeness report unavailable: BuilderOps storage unavailable."
    incomplete = (
        unprocessed
        or missing_terminal
        or missing_successors
        or unresolved_candidates
        or stale_entries
    )
    posture = "incomplete" if incomplete else "complete"
    return (
        f"Completeness report {posture}: "
        f"unprocessed_learning_signals={len(unprocessed)}, "
        f"receipts_missing_terminal_outcomes={len(missing_terminal)}, "
        f"terminal_signals_missing_successor_refs={len(missing_successors)}, "
        f"reevaluation_candidates_without_outcome={len(unresolved_candidates)}, "
        f"stale_compatibility_entries={len(stale_entries)}."
    )


__all__ = [
    "RETROSPECTIVE_EVENT_TYPE",
    "build_completeness_report",
    "load_records_from_db",
]
