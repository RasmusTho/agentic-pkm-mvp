"""Read-only Chat cognition scaffold.

This module intentionally provides planning/reasoning only. It never executes
tools, mutates notes, writes outbox events, or emits promotion/action intents.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Callable

from app.reasoning.facade import ReasoningModeFacade, get_reasoning_mode_facade

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
_DENY_PATTERN = re.compile(r"\b(" + "|".join(re.escape(token) for token in _DENY_HINTS) + r")\b")


@dataclass(frozen=True)
class ReadOnlyChatResponse:
    read_only: bool
    answer: str
    planning: dict[str, Any] = field(default_factory=dict)
    denied_requests: list[str] = field(default_factory=list)
    side_effects_emitted: bool = False
    trace_id: str | None = None
    degraded: bool = False


class ReadOnlyChatCognition:
    """Minimal Chat cognition seam that remains execution-denied."""

    def __init__(
        self,
        *,
        facade_factory: Callable[[], ReasoningModeFacade] = get_reasoning_mode_facade,
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

        degraded = bool(planning.get("degraded"))

        if denied:
            answer = (
                "Read-only Chat cognition denied mutation/execution requests. "
                "I can help plan, reason, and summarize, but I cannot run tools or mutate state."
            )
        else:
            answer = "Read-only Chat cognition generated a planning-only response."

        if degraded:
            # Surface the degradation instead of presenting a canned plan as real.
            answer = (
                f"{answer} A plan could not be produced: "
                f"{planning.get('provider_error') or 'planning is unavailable'}."
            )

        return ReadOnlyChatResponse(
            read_only=True,
            answer=answer,
            planning=planning,
            denied_requests=denied,
            side_effects_emitted=False,
            trace_id=trace_id,
            degraded=degraded,
        )

    @staticmethod
    def _detect_denied_requests(prompt: str) -> list[str]:
        lowered = prompt.lower()
        return sorted({match.group(1) for match in _DENY_PATTERN.finditer(lowered)})

    def _plan_read_only(self, prompt: str, *, trace_id: str | None) -> dict[str, Any]:
        """Plan via the reasoning facade, or return a self-identifying degraded payload.

        When the underlying PLANNING run fails, this surface must not substitute
        generic steps that are indistinguishable from a model-produced plan.
        The degraded payload carries the marker and the provider error instead.
        """
        facade = self._facade_factory()
        run = facade.plan([], goal=prompt, trace_id=trace_id)
        if run.status == "ok" and isinstance(run.result, dict) and run.result:
            return run.result
        return {
            "mode": "read_only_degraded",
            "degraded": True,
            "degraded_reason": "planning_unavailable",
            "provider_error": run.error or "planning run returned no result",
            "goal": prompt,
            "steps": [],
            "execution_allowed": False,
            "trace_id": trace_id,
        }
