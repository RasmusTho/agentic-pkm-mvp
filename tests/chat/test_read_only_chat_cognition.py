from __future__ import annotations

import pytest

from app.chat.read_only_cognition import ReadOnlyChatCognition
from app.reasoning.models import ReasoningMode, ReasoningRun


class _StubFacade:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def plan(self, object_ids: list[str], *, goal: str | None = None, trace_id: str | None = None) -> ReasoningRun:
        self.calls.append({"object_ids": object_ids, "goal": goal, "trace_id": trace_id})
        return ReasoningRun(
            id="run-chat-1",
            mode=ReasoningMode.PLANNING,
            status="ok",
            result={"steps": ["understand", "answer"]},
            object_uuids=[],
            trace_id=trace_id,
            error=None,
        )


class _SpySideEffect:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, *_args: object, **_kwargs: object) -> None:
        self.calls += 1


class _FailingFacade:
    def plan(self, object_ids: list[str], *, goal: str | None = None, trace_id: str | None = None) -> ReasoningRun:
        return ReasoningRun(
            id="run-chat-fail",
            mode=ReasoningMode.PLANNING,
            status="failed",
            result={},
            object_uuids=[],
            trace_id=trace_id,
            error="mode planning not implemented",
        )


def test_chat_cognition_uses_reasoning_facade_and_returns_structured_response() -> None:
    facade = _StubFacade()
    cognition = ReadOnlyChatCognition(facade_factory=lambda: facade)

    result = cognition.respond("Summarize these notes", trace_id="trace-chat-1")

    assert result.read_only is True
    assert result.trace_id == "trace-chat-1"
    assert result.planning == {"steps": ["understand", "answer"]}
    assert facade.calls == [{"object_ids": [], "goal": "Summarize these notes", "trace_id": "trace-chat-1"}]


def test_chat_cognition_denies_mutation_and_execution_requests() -> None:
    facade = _StubFacade()
    cognition = ReadOnlyChatCognition(facade_factory=lambda: facade)

    result = cognition.respond("Write a note and run the panel action now")

    assert result.read_only is True
    assert result.denied_requests
    assert "read-only" in result.answer.lower()
    assert result.side_effects_emitted is False


def test_chat_cognition_has_no_note_or_outbox_side_effects() -> None:
    facade = _StubFacade()
    note_writer = _SpySideEffect()
    outbox_writer = _SpySideEffect()
    cognition = ReadOnlyChatCognition(
        facade_factory=lambda: facade,
        note_writer=note_writer,
        outbox_writer=outbox_writer,
    )

    result = cognition.respond("Help me reason about this idea")

    assert result.read_only is True
    assert result.side_effects_emitted is False
    assert note_writer.calls == 0
    assert outbox_writer.calls == 0


def test_chat_cognition_marks_planning_degraded_when_reasoning_plan_fails() -> None:
    cognition = ReadOnlyChatCognition(facade_factory=lambda: _FailingFacade())
    result = cognition.respond("Plan how to summarize this thread", trace_id="trace-chat-fallback")

    # The degraded payload must be self-identifying, not a canned plan that
    # reads like a real one.
    assert result.planning["mode"] == "read_only_degraded"
    assert result.planning["degraded"] is True
    assert result.planning["degraded_reason"] == "planning_unavailable"
    assert result.planning["provider_error"] == "mode planning not implemented"
    assert result.planning["execution_allowed"] is False
    assert result.planning["goal"] == "Plan how to summarize this thread"
    assert result.planning["trace_id"] == "trace-chat-fallback"
    # No fabricated plan steps.
    assert result.planning.get("steps") == []
    assert result.degraded is True
    assert "could not be produced" in result.answer.lower()


def test_chat_cognition_reaches_real_planning_path_on_mock_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The default (non-injected) facade must now reach a real PLANNING result
    # instead of always falling back.
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("REASONING_PROVIDER", "mock")
    monkeypatch.delenv("CI", raising=False)

    result = ReadOnlyChatCognition().respond("Help me think about X", trace_id="trace-real")

    assert result.degraded is False
    assert result.planning.get("mode") not in {"read_only_fallback", "read_only_degraded"}
    assert result.planning.get("plan")
    assert result.planning.get("steps")


def test_chat_cognition_denied_detection_uses_word_boundaries() -> None:
    facade = _StubFacade()
    cognition = ReadOnlyChatCognition(facade_factory=lambda: facade)
    result = cognition.respond("Explain runtime architecture and actionable constraints.")
    assert "run" not in result.denied_requests
    assert "action" not in result.denied_requests
