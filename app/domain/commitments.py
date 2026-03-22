from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


CommitmentKind = Literal[
    "open_loop",
    "project",
    "next_action",
    "waiting",
    "review_return",
]

FIRST_WAVE_COMMITMENT_KINDS: tuple[CommitmentKind, ...] = (
    "open_loop",
    "project",
    "next_action",
    "waiting",
    "review_return",
)


@dataclass(frozen=True)
class CommitmentHandle:
    commitment_kind: CommitmentKind
    target_ref: str | None = None
    summary: str | None = None
    source_goal: str | None = None

    def to_dict(self) -> dict[str, str]:
        payload = {"commitment_kind": self.commitment_kind}
        if self.target_ref:
            payload["target_ref"] = self.target_ref
        if self.summary:
            payload["summary"] = self.summary
        if self.source_goal:
            payload["source_goal"] = self.source_goal
        return payload


def normalize_commitment_kind(value: object) -> CommitmentKind:
    cleaned = str(value or "").strip().lower()
    if cleaned not in FIRST_WAVE_COMMITMENT_KINDS:
        raise ValueError(f"unsupported commitment_kind '{value}'")
    return cleaned  # type: ignore[return-value]


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


def build_commitment_handles_for_goal(goal: str, *, target_ref: str | None = None) -> list[CommitmentHandle]:
    cleaned_goal = str(goal or "").strip()
    lowered = cleaned_goal.lower()
    if not cleaned_goal:
        return []

    kinds: list[CommitmentKind] = []
    if "next action" in lowered:
        kinds.append("next_action")
    if "waiting" in lowered or "await" in lowered:
        kinds.append("waiting")
    if "review return" in lowered or "revisit" in lowered:
        kinds.append("review_return")
    if "project" in lowered:
        kinds.append("project")
    if not kinds:
        kinds.append("open_loop")

    return [
        CommitmentHandle(
            commitment_kind=kind,
            target_ref=target_ref or None,
            summary=cleaned_goal,
            source_goal=cleaned_goal,
        )
        for kind in kinds
    ]


__all__ = [
    "CommitmentHandle",
    "CommitmentKind",
    "FIRST_WAVE_COMMITMENT_KINDS",
    "build_commitment_handles_for_goal",
    "make_commitment_handle",
    "normalize_commitment_kind",
]
