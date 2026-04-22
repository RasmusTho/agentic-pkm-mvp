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


def query_next_and_waiting_commitments(
    commitments: tuple[CommitmentRecord, ...] | list[CommitmentRecord],
) -> CommitmentQueryResult:
    next_items = tuple(item for item in commitments if item.state == "next")
    waiting_items = tuple(item for item in commitments if item.state == "waiting")
    operator_summary: dict[str, object] = {
        "next_count": len(next_items),
        "waiting_count": len(waiting_items),
        "next_ids": [item.commitment_id for item in next_items],
        "waiting_ids": [item.commitment_id for item in waiting_items],
    }
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


__all__ = [
    "COMMITMENT_STATE_VALUES",
    "CommitmentQueryResult",
    "CommitmentHandle",
    "CommitmentRecord",
    "CommitmentState",
    "CommitmentTransitionResult",
    "CommitmentKind",
    "FIRST_WAVE_COMMITMENT_KINDS",
    "apply_commitment_state_transition",
    "make_commitment_handle",
    "normalize_commitment_state",
    "normalize_commitment_kind",
    "query_next_and_waiting_commitments",
]
