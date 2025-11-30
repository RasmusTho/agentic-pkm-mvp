from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID

import pytest

from app.agents.set_evaluator.agent import run_set_evaluator
from app.reasoning.multi import run_multi_note_reasoning
from app.reasoning.provider import get_deliberation_agent
from app.reasoning.schema import ReasoningInput
from app.stores import get_object_store, reset_store_backends


def _fake_reasoning_json(object_uuid: str = "OBJ1") -> str:
    return json.dumps(
        {
            "claims": [
                {
                    "id": "c1",
                    "object_uuid": object_uuid,
                    "text": "Claim about the note",
                    "modality": "assertion",
                    "confidence": 0.9,
                }
            ],
            "evidence": [
                {
                    "id": "e1",
                    "object_uuid": object_uuid,
                    "source_ref": "path/to.md",
                    "kind": "document",
                    "strength": 0.8,
                }
            ],
            "inferences": [
                {
                    "id": "i1",
                    "premises": ["c1"],
                    "conclusion_id": "c1",
                    "type": "support",
                    "rationale": "Supported by context.",
                }
            ],
        }
    )


def _patch_reasoning_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("REASONING_PROVIDER", "llm")
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.delenv("CI", raising=False)


def test_reasoning_single_note_logs_real_json(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_reasoning_env(monkeypatch)
    fake_json = _fake_reasoning_json("OBJ-SINGLE")

    captured: list[dict] = []

    def fake_log_llm_call(**kwargs):
        captured.append(kwargs)

    monkeypatch.setattr("app.services.llm.log_llm_call", fake_log_llm_call)
    monkeypatch.setattr("app.services.llm._deterministic_llm_response", lambda: fake_json)

    deliberation_agent = get_deliberation_agent()
    note_text = "Note about safety and alignment."
    ri = ReasoningInput(object_uuid="OBJ-SINGLE", text=note_text, metadata={"trace_id": "T-single"}, relations=[])

    output = deliberation_agent.reason(ri)

    assert output.claims and output.evidence and output.inferences
    assert captured, "log_llm_call should be invoked"
    entry = captured[0]
    assert entry["agent"] == "reasoning"
    assert entry["kind"] in {"reasoning.single_note", "reasoning.claims"}
    assert "claims" in entry.get("response_text", "")
    assert "inferences" in entry.get("response_text", "")
    messages = entry["messages"]
    assert any("safety and alignment" in m.get("content", "") for m in messages if m.get("role") == "user")


def test_reasoning_multi_note_logs_real_json(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_reasoning_env(monkeypatch)
    fake_json = _fake_reasoning_json("OBJ-MULTI")

    captured: list[dict] = []

    def fake_log_llm_call(**kwargs):
        captured.append(kwargs)

    monkeypatch.setattr("app.services.llm.log_llm_call", fake_log_llm_call)
    monkeypatch.setattr("app.services.llm._deterministic_llm_response", lambda: fake_json)

    reset_store_backends()
    store = get_object_store()
    obj_ids = [UUID("11111111-1111-1111-1111-111111111111"), UUID("22222222-2222-2222-2222-222222222222")]
    store.put(obj_ids[0], kind="note", source_ref="a.md", payload={"text": "Note A content"})
    store.put(obj_ids[1], kind="note", source_ref="b.md", payload={"text": "Note B content"})

    output = run_multi_note_reasoning([str(obj_ids[0]), str(obj_ids[1])], trace_id="T-multi")

    assert output.claims and output.evidence
    assert captured, "log_llm_call should be invoked for multi-note reasoning"
    kinds = {entry["kind"] for entry in captured}
    assert "reasoning.claims" in kinds or "reasoning.multi_note" in kinds
    assert all("claims" in entry.get("response_text", "") for entry in captured)


def test_set_evaluator_logs_real_json(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_reasoning_env(monkeypatch)
    fake_json = _fake_reasoning_json("OBJ-SET")

    captured: list[dict] = []

    def fake_log_llm_call(**kwargs):
        captured.append(kwargs)

    monkeypatch.setattr("app.services.llm.log_llm_call", fake_log_llm_call)
    monkeypatch.setattr("app.services.llm._deterministic_llm_response", lambda: fake_json)

    store = get_object_store()
    c1 = str(UUID(int=1))
    c2 = str(UUID(int=2))
    store.put(UUID(c1), kind="note", source_ref="a.md", payload={"text": f"text for {c1}"})
    store.put(UUID(c2), kind="note", source_ref="b.md", payload={"text": f"text for {c2}"})

    candidates = [c1, c2]
    result = run_set_evaluator(candidates, question="Which note wins?", trace_id="T-set")

    assert result.ranking
    for item in result.ranking:
        assert item.reasons and all(isinstance(r, str) and r.strip() for r in item.reasons)

    assert captured, "log_llm_call should capture set_evaluator reasoning"
    assert any(entry["agent"] == "set_evaluator" for entry in captured)
    assert any(entry["kind"] in {"set_eval.rank", "reasoning.ranking"} for entry in captured)
    assert any(entry.get("response_text", "").strip() not in ("", "{}") for entry in captured)
