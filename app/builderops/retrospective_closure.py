"""Retrospective terminal-outcome ledger helpers."""

from __future__ import annotations

from typing import Any, Mapping

from app.builderops.epic_run_state import TERMINAL_LEARNING_EVALUATION_OUTCOMES
from app.builderops.models import BuilderOpsValidationError, validate_source_refs

OUTCOME_TARGET_REF_TYPES = {
    "applied": frozenset({"pull_request", "repo_doc", "builderops_object"}),
    "already_satisfied": frozenset({"repo_doc", "pull_request", "github_issue"}),
    "issue_created": frozenset({"github_issue"}),
    "promotion_pending": frozenset({"builderops_object"}),
    "debt_or_fitness_recorded": frozenset({"repo_doc", "github_issue"}),
    "discarded_or_superseded": frozenset({"builderops_object"}),
}


class RetrospectiveClosureError(BuilderOpsValidationError):
    """Raised when retrospective closure input is malformed."""


def build_retrospective_closure_ledger(
    *,
    signals: list[Mapping[str, Any]],
    outcomes: list[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build an observe-only terminal-outcome ledger for processed signals."""

    normalized_signals = [_normalize_signal(item) for item in signals]
    normalized_outcomes = [_normalize_outcome(item) for item in outcomes]
    signal_index = {item["signal_id"]: item for item in normalized_signals}
    duplicate_signals = _duplicates([item["signal_id"] for item in normalized_signals])
    if duplicate_signals:
        raise RetrospectiveClosureError(
            f"duplicate signal id(s): {', '.join(duplicate_signals)}"
        )

    outcome_index: dict[str, dict[str, Any]] = {}
    for outcome in normalized_outcomes:
        signal_id = outcome["signal_id"]
        if signal_id not in signal_index:
            raise RetrospectiveClosureError(
                f"outcome references unknown signal: {signal_id}"
            )
        if signal_id in outcome_index:
            raise RetrospectiveClosureError(
                f"duplicate outcome for signal: {signal_id}"
            )
        outcome_index[signal_id] = outcome

    processed = [
        {
            "signal_id": signal["signal_id"],
            "summary": signal.get("summary"),
            "outcome": outcome_index[signal["signal_id"]]["outcome"],
            "target_refs": outcome_index[signal["signal_id"]]["target_refs"],
        }
        for signal in normalized_signals
        if signal["signal_id"] in outcome_index
    ]
    unresolved = [
        signal
        for signal in normalized_signals
        if signal["signal_id"] not in outcome_index
    ]

    return {
        "complete": not unresolved,
        "processed_signal_outcomes": processed,
        "unresolved_signals": unresolved,
        "terminal_outcomes": list(TERMINAL_LEARNING_EVALUATION_OUTCOMES),
        "receipt_body": _receipt_body(processed, unresolved),
    }


def _normalize_signal(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise RetrospectiveClosureError("signals entries must be objects")
    signal_id = _required_string(value.get("id") or value.get("signal_id"), "signal id")
    normalized: dict[str, Any] = {"signal_id": signal_id}
    if value.get("summary"):
        normalized["summary"] = _required_string(value["summary"], "summary")
    return normalized


def _normalize_outcome(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise RetrospectiveClosureError("outcome entries must be objects")
    signal_id = _required_string(value.get("signal_id"), "outcome.signal_id")
    outcome = _required_string(value.get("outcome"), "outcome.outcome")
    if outcome not in TERMINAL_LEARNING_EVALUATION_OUTCOMES:
        raise RetrospectiveClosureError(
            "outcome.outcome must be one of "
            f"{list(TERMINAL_LEARNING_EVALUATION_OUTCOMES)}"
        )
    raw_target_refs = value.get("target_refs")
    try:
        validate_source_refs(raw_target_refs, "outcome.target_refs")
    except BuilderOpsValidationError as exc:
        raise RetrospectiveClosureError(str(exc)) from exc
    if not isinstance(raw_target_refs, list):  # validate_source_refs guards this.
        raise RetrospectiveClosureError("outcome.target_refs must be a non-empty list")
    target_refs = list(raw_target_refs)
    _validate_target_ref_types(outcome, target_refs)
    return {
        "signal_id": signal_id,
        "outcome": outcome,
        "target_refs": target_refs,
    }


def _validate_target_ref_types(
    outcome: str,
    target_refs: list[dict[str, Any]],
) -> None:
    allowed = OUTCOME_TARGET_REF_TYPES[outcome]
    invalid = [
        str(ref.get("ref_type"))
        for ref in target_refs
        if ref.get("ref_type") not in allowed
    ]
    if invalid:
        raise RetrospectiveClosureError(
            f"outcome {outcome!r} target_refs must use ref_type "
            f"{sorted(allowed)}; got {invalid}"
        )


def _required_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RetrospectiveClosureError(f"{field} must be a non-empty string")
    return value.strip()


def _duplicates(values: list[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for value in values:
        if value in seen and value not in duplicates:
            duplicates.append(value)
        seen.add(value)
    return duplicates


def _receipt_body(
    processed: list[dict[str, Any]],
    unresolved: list[dict[str, Any]],
) -> str:
    if not processed and unresolved:
        return (
            "Retrospective incomplete; unresolved signals: "
            + ", ".join(item["signal_id"] for item in unresolved)
            + "."
        )
    fragments = [
        f"{item['signal_id']}={item['outcome']}"
        for item in processed
    ]
    if unresolved:
        fragments.append(
            "unresolved=" + ",".join(item["signal_id"] for item in unresolved)
        )
        return "Retrospective incomplete; outcomes: " + "; ".join(fragments) + "."
    return "Retrospective complete; outcomes: " + "; ".join(fragments) + "."


__all__ = [
    "OUTCOME_TARGET_REF_TYPES",
    "RetrospectiveClosureError",
    "build_retrospective_closure_ledger",
]
