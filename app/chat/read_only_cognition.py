"""Read-only Chat cognition scaffold.

This module intentionally provides planning/reasoning only. It never executes
tools, mutates notes, writes outbox events, or emits promotion/action intents.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from app.reasoning.facade import ReasoningFacade, get_reasoning_facade

_DENY_HINTS = (
    "write",
    "update",
    "edit",
    "delete",
    "append",
    "execute",
    "run",
    "tool",
    "action",
    "promote",
    "emit",
    "outbox",
)


@dataclass(frozen=True)
class ReadOnlyChatResponse:
    read_only: bool
    answer: str
    planning: dict[str, Any] = field(default_factory=dict)
    denied_requests: list[str] = field(default_factory=list)
    side_effects_emitted: bool = False
    trace_id: str | None = None


class ReadOnlyChatCognition:
    """Minimal Chat cognition seam that remains execution-denied."""

    def __init__(
        self,
        *,
        facade_factory: Callable[[], ReasoningFacade] = get_reasoning_facade,
        note_writer: Callable[..., None] | None = None,
        outbox_writer: Callable[..., None] | None = None,
    ) -> None:
        self._facade_factory = facade_factory
        self._note_writer = note_writer
        self._outbox_writer = outbox_writer

    def respond(self, prompt: str, *, trace_id: str | None = None) -> ReadOnlyChatResponse:
        text = prompt.strip()
        denied = self._detect_denied_requests(text)
        planning = self._plan_read_only(text, trace_id=trace_id)

        if denied:
            answer = (
                "Read-only Chat cognition denied mutation/execution requests. "
                "I can help plan, reason, and summarize, but I cannot run tools or mutate state."
            )
        else:
            answer = "Read-only Chat cognition generated a planning-only response."

        return ReadOnlyChatResponse(
            read_only=True,
            answer=answer,
            planning=planning,
            denied_requests=denied,
            side_effects_emitted=False,
            trace_id=trace_id,
        )

    @staticmethod
    def _detect_denied_requests(prompt: str) -> list[str]:
        lowered = prompt.lower()
        return [token for token in _DENY_HINTS if token in lowered]

    def _plan_read_only(self, prompt: str, *, trace_id: str | None) -> dict[str, Any]:
        facade = self._facade_factory()
        run = facade.plan([], goal=prompt, trace_id=trace_id)
        if run.status != "ok" or not isinstance(run.result, dict):
            return {}
        return run.result
