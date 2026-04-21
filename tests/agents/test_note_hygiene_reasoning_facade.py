from __future__ import annotations

from pathlib import Path

from app.agents.note_hygiene.agent import classify_and_act
from app.components.reasoning.facade import ReviewResult


def test_note_hygiene_uses_reasoning_facade(monkeypatch) -> None:
    class StubFacade:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def reason(self, task_kind, input, trace_id=None):  # type: ignore[no-untyped-def]
            self.calls.append({"task_kind": task_kind, "input": input, "trace_id": trace_id})
            return ReviewResult(summary="Facade summary", suggestions=[])

    stub = StubFacade()
    monkeypatch.setattr("app.agents.note_hygiene.agent.get_reasoning_facade", lambda: stub)

    note = {"fm": {"uuid": "nh-1", "kind": "concept"}, "body": "# T\nThis body is short."}
    out = classify_and_act(note, trace_id="t-note-hygiene")

    assert out["action"] == "fix_structure"
    assert "Facade summary" in out["body"]
    assert len(stub.calls) == 1
    call = stub.calls[0]
    assert str(call["task_kind"]).endswith("REVIEW")
    assert call["trace_id"] == "t-note-hygiene"
    assert call["input"]["object_uuid"] == "nh-1"
    assert call["input"]["_agent"] == "note_hygiene"

    source = Path("app/agents/note_hygiene/agent.py").read_text(encoding="utf-8")
    assert "LLMRouter(" not in source
    assert "ChatClient(" not in source


def test_note_hygiene_accepts_deterministic_facade_double() -> None:
    class DeterministicFacade:
        def reason(self, task_kind, input, trace_id=None):  # type: ignore[no-untyped-def]
            return ReviewResult(summary="Deterministic summary", suggestions=["keep pointers"])

    note = {"fm": {"uuid": "nh-2", "kind": "concept"}, "body": "# Widgets\nhttps://example.com/x"}
    out = classify_and_act(note, trace_id="t-note-hygiene-double", reasoning_facade=DeterministicFacade())

    assert out["action"] == "fix_structure"
    assert "Deterministic summary" in out["body"]
