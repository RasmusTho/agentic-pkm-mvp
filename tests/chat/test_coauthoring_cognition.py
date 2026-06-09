"""Co-authoring cognition — acceptance tests (no live LLM provider).

Covers the write-capable co-authoring cognition that turns a user intent
plus the current note body into a generated body revision via the shared
``ReasoningFacade``. The cognition produces body-only text and never emits
frontmatter; a frontmatter-bearing generation is rejected before write.

The read-only cognition scaffold must remain unchanged and execution-denied.
"""

from __future__ import annotations

import inspect

import pytest

from app.chat.canvas_writer import GovernanceBearingMutationError
from app.chat.coauthoring_cognition import (
    CoAuthoringCognition,
    CoAuthoringUnavailableError,
)
from app.chat.read_only_cognition import ReadOnlyChatCognition
from app.reasoning.models import ReasoningMode, ReasoningRun


class _StubFacade:
    """Deterministic facade stub that records calls and returns body text."""

    def __init__(self, body: str) -> None:
        self._body = body
        self.calls: list[dict[str, object]] = []

    def answer(
        self,
        question: str,
        *,
        context: str | None = None,
        object_ids: list[str] | None = None,
        trace_id: str | None = None,
    ) -> ReasoningRun:
        self.calls.append(
            {
                "question": question,
                "context": context,
                "object_ids": object_ids,
                "trace_id": trace_id,
            }
        )
        return ReasoningRun(
            id="run-coauthor-1",
            mode=ReasoningMode.ASK_ANSWER,
            status="ok",
            result={"answer": self._body},
            object_uuids=[],
            trace_id=trace_id,
            error=None,
        )

    def plan(
        self,
        object_ids: list[str],
        *,
        goal: str | None = None,
        trace_id: str | None = None,
    ) -> ReasoningRun:
        return ReasoningRun(
            id="run-coauthor-plan",
            mode=ReasoningMode.PLANNING,
            status="ok",
            result={"steps": ["plan"]},
            object_uuids=[],
            trace_id=trace_id,
            error=None,
        )


def test_generates_body_from_intent() -> None:
    facade = _StubFacade("# Hello\n\nExpanded decision section with trade-offs.\n")
    cognition = CoAuthoringCognition(facade_factory=lambda: facade)

    result = cognition.generate_body(
        intent="expand the decision section with the trade-offs we discussed",
        current_body="# Hello\n\nOriginal body.\n",
        trace_id="trace-coauthor-1",
    )

    assert result.generated is True
    assert result.body == "# Hello\n\nExpanded decision section with trade-offs.\n"
    # Body-only output: no frontmatter delimiter.
    assert not result.body.lstrip().startswith("---")
    # The cognition consulted the shared ReasoningFacade with intent + body.
    assert len(facade.calls) == 1
    call = facade.calls[0]
    assert "expand the decision section" in str(call["question"])
    assert "Original body." in str(call["context"])
    assert call["trace_id"] == "trace-coauthor-1"


def test_generated_body_with_frontmatter_is_rejected() -> None:
    facade = _StubFacade("---\ntype: note\n---\n\n# Hello\n\nRewritten body.\n")
    cognition = CoAuthoringCognition(facade_factory=lambda: facade)

    with pytest.raises(GovernanceBearingMutationError):
        cognition.generate_body(
            intent="rewrite the note and change its type",
            current_body="# Hello\n\nOriginal body.\n",
        )


def test_mock_generation_is_rejected_not_applied() -> None:
    # A mock/degraded backend returns a diagnostic string, not an edit.
    facade = _StubFacade("MOCK_ASK_ANSWER: rewrite the note | context: ...")
    cognition = CoAuthoringCognition(facade_factory=lambda: facade)

    with pytest.raises(CoAuthoringUnavailableError):
        cognition.generate_body(
            intent="rewrite the note",
            current_body="# Hello\n\nOriginal body.\n",
        )


def test_read_only_cognition_remains_execution_denied() -> None:
    # The read-only scaffold must keep denying mutation/execution and never
    # acquire body-generation or write capability.
    cognition = ReadOnlyChatCognition()
    assert not hasattr(cognition, "generate_body")
    assert not hasattr(cognition, "apply_edit")

    source = inspect.getsource(ReadOnlyChatCognition)
    assert "CanvasWriter" not in source
    assert "apply_edit" not in source

    facade = _StubFacade("ignored")
    read_only = ReadOnlyChatCognition(facade_factory=lambda: facade)
    response = read_only.respond("write a new note and run the panel action")
    assert response.read_only is True
    assert response.side_effects_emitted is False
    assert response.denied_requests
