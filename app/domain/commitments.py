from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast


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
        payload: dict[str, str] = {"commitment_kind": self.commitment_kind}
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
    return cast(CommitmentKind, cleaned)


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


__all__ = [
    "CommitmentHandle",
    "CommitmentKind",
    "FIRST_WAVE_COMMITMENT_KINDS",
    "make_commitment_handle",
    "normalize_commitment_kind",
]
