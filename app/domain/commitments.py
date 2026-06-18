from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal, cast


CommitmentKind = Literal[
    "open_loop",
    "project",
    "next_action",
    "waiting",
    "review_return",
]

CommitmentState = Literal[
    "unknown",
    "open",
    "next",
    "waiting",
    "blocked",
    "done",
]

FIRST_WAVE_COMMITMENT_KINDS: tuple[CommitmentKind, ...] = (
    "open_loop",
    "project",
    "next_action",
    "waiting",
    "review_return",
)

COMMITMENT_STATE_VALUES: tuple[CommitmentState, ...] = (
    "unknown",
    "open",
    "next",
    "waiting",
    "blocked",
    "done",
)


@dataclass(frozen=True)
class CommitmentHandle:
    commitment_kind: CommitmentKind
    target_ref: str | None = None
    summary: str | None = None
    source_goal: str | None = None

    def to_dict(self) -> dict[str, str]:
        payload: dict[str, str] = {"commitment_kind": self.commitment_kind}
        if self.target_ref:
            payload["target_ref"] = self.target_ref
        if self.summary:
            payload["summary"] = self.summary
        if self.source_goal:
            payload["source_goal"] = self.source_goal
        return payload


@dataclass(frozen=True)
class CommitmentRecord:
    commitment_id: str
    commitment_kind: CommitmentKind
    state: CommitmentState = "unknown"
    target_ref: str | None = None
    summary: str | None = None
    source_goal: str | None = None
    # Optional commitment-layer provenance. All default ``None`` and an absent
    # value is rendered as an omitted line — never fabricated (no-fabricated-data
    # invariant; COMMITMENT_LAYER_CONTRACT.md). ``waiting_*`` apply to ``waiting``
    # commitments (the actor/event a waiting item depends on, and since when);
    # ``review_cadence`` / ``last_reviewed`` apply to ``review_return`` (the
    # re-orientation cadence and when it was last reviewed).
    waiting_on: str | None = None
    waiting_since: str | None = None
    review_cadence: str | None = None
    last_reviewed: str | None = None


@dataclass(frozen=True)
class CommitmentQueryResult:
    next_items: tuple[CommitmentRecord, ...]
    waiting_items: tuple[CommitmentRecord, ...]
    operator_summary: dict[str, object]


@dataclass(frozen=True)
class CommitmentTransitionResult:
    updated: CommitmentRecord
    receipt_metadata: dict[str, str]


def normalize_commitment_kind(value: object) -> CommitmentKind:
    cleaned = str(value or "").strip().lower()
    if cleaned not in FIRST_WAVE_COMMITMENT_KINDS:
        raise ValueError(f"unsupported commitment_kind '{value}'")
    return cast(CommitmentKind, cleaned)


def normalize_commitment_state(value: object) -> CommitmentState:
    cleaned = str(value or "").strip().lower()
    if cleaned not in COMMITMENT_STATE_VALUES:
        raise ValueError(f"unsupported commitment_state '{value}'")
    return cast(CommitmentState, cleaned)


def make_commitment_handle(
    *,
    commitment_kind: object,
    target_ref: str | None = None,
    summary: str | None = None,
    source_goal: str | None = None,
) -> CommitmentHandle:
    return CommitmentHandle(
        commitment_kind=normalize_commitment_kind(commitment_kind),
        target_ref=target_ref or None,
        summary=summary or None,
        source_goal=source_goal or None,
    )


def _salience_rank_score(
    commitment_id: str,
    salience_scores: dict[str, float] | None,
    staleness_scores: dict[str, float] | None,
) -> float:
    """Derive a composite ranking score from optional salience and staleness inputs.

    Both signals are optional and may be absent or partial.  When a signal is
    missing for a given commitment_id the contribution of that signal is treated
    as 0.0 so the function never raises.  Higher scores sort earlier.

    Ranking formula: salience_score + staleness_score (equally weighted).
    Neither signal is required; an absent signal contributes 0.0.
    """
    salience = (salience_scores or {}).get(commitment_id, 0.0)
    staleness = (staleness_scores or {}).get(commitment_id, 0.0)
    return salience + staleness


def query_next_and_waiting_commitments(
    commitments: tuple[CommitmentRecord, ...] | list[CommitmentRecord],
    *,
    salience_scores: dict[str, float] | None = None,
    staleness_scores: dict[str, float] | None = None,
) -> CommitmentQueryResult:
    """Return next and waiting commitments, optionally ranked by salience/staleness.

    Parameters
    ----------
    commitments:
        All commitment records to surface from.
    salience_scores:
        Optional mapping of commitment_id -> salience score (0.0–1.0).
        When present, higher-salience next-items rank earlier.
        Absent or partial maps degrade gracefully; no error is raised.
    staleness_scores:
        Optional mapping of commitment_id -> staleness score (0.0–1.0).
        When present, higher-staleness next-items rank earlier, and staleness
        metadata is included in operator_summary for waiting items.
        Absent or partial maps degrade gracefully; no error is raised.

    Returns
    -------
    CommitmentQueryResult
        Results are commitment-typed (CommitmentRecord).  States remain within
        the commitment state vocabulary and are never collapsed into note-state
        axes (review_state / maturity).
    """
    raw_next = [item for item in commitments if item.state == "next"]
    raw_waiting = [item for item in commitments if item.state == "waiting"]

    # Rank next items when any signal is present; Python's sort is stable so
    # items with equal scores (no signal → 0.0) retain their insertion order.
    signals_present = salience_scores is not None or staleness_scores is not None
    if signals_present:
        raw_next.sort(
            key=lambda c: _salience_rank_score(c.commitment_id, salience_scores, staleness_scores),
            reverse=True,
        )

    next_items = tuple(raw_next)
    waiting_items = tuple(raw_waiting)

    operator_summary: dict[str, object] = {
        "next_count": len(next_items),
        "waiting_count": len(waiting_items),
        "next_ids": [item.commitment_id for item in next_items],
        "waiting_ids": [item.commitment_id for item in waiting_items],
    }

    # Expose staleness metadata for waiting items when staleness scores are present.
    if staleness_scores is not None:
        waiting_staleness: dict[str, float] = {
            item.commitment_id: staleness_scores.get(item.commitment_id, 0.0)
            for item in waiting_items
        }
        operator_summary["waiting_staleness"] = waiting_staleness

    return CommitmentQueryResult(
        next_items=next_items,
        waiting_items=waiting_items,
        operator_summary=operator_summary,
    )


def apply_commitment_state_transition(
    commitment: CommitmentRecord,
    *,
    to_state: object,
    receipt_event_id: str,
    trace_id: str,
    cause: str,
    executor: str = "commitment.runtime",
) -> CommitmentTransitionResult:
    next_state = normalize_commitment_state(to_state)
    updated = replace(commitment, state=next_state)
    receipt_metadata = {
        "commitment_id": commitment.commitment_id,
        "receipt_event_id": str(receipt_event_id),
        "trace_id": str(trace_id),
        "before_state": commitment.state,
        "after_state": next_state,
        "transition_family": "commitment_state",
        "cause": str(cause),
        "executor": executor,
    }
    return CommitmentTransitionResult(updated=updated, receipt_metadata=receipt_metadata)


_REQUIRED_RECEIPT_FIELDS: tuple[str, ...] = (
    "verb",
    "authority",
    "basis",
    "outcome",
    "artifact_linkage",
    "instance_provenance",
)


def apply_commitment_mutation(
    commitment: CommitmentRecord,
    *,
    to_state: object,
    receipt_request: dict[str, object],
) -> CommitmentTransitionResult:
    """Gate commitment state mutations through a receipt-bearing APPLY request.

    Raises ValueError if the verb is not APPLY or if any required receipt field
    is missing. Returns a CommitmentTransitionResult on success.
    """
    verb = str(receipt_request.get("verb") or "").strip().upper()
    if verb != "APPLY":
        raise ValueError(
            f"commitment mutation requires trust verb APPLY; got '{verb or '(empty)'}'"
        )

    for field in _REQUIRED_RECEIPT_FIELDS:
        if field not in receipt_request or receipt_request[field] is None or str(receipt_request[field]).strip() == "":
            raise ValueError(
                f"commitment mutation missing required receipt field '{field}'"
            )

    next_state = normalize_commitment_state(to_state)
    updated = replace(commitment, state=next_state)
    receipt_metadata: dict[str, str] = {
        "commitment_id": commitment.commitment_id,
        "before_state": commitment.state,
        "after_state": next_state,
        "transition_family": "commitment_state",
    }
    for field in _REQUIRED_RECEIPT_FIELDS:
        receipt_metadata[field] = verb if field == "verb" else str(receipt_request[field])
    return CommitmentTransitionResult(updated=updated, receipt_metadata=receipt_metadata)


__all__ = [
    "COMMITMENT_STATE_VALUES",
    "CommitmentQueryResult",
    "CommitmentHandle",
    "CommitmentRecord",
    "CommitmentState",
    "CommitmentTransitionResult",
    "CommitmentKind",
    "FIRST_WAVE_COMMITMENT_KINDS",
    "apply_commitment_mutation",
    "apply_commitment_state_transition",
    "make_commitment_handle",
    "normalize_commitment_state",
    "normalize_commitment_kind",
    "query_next_and_waiting_commitments",
]
