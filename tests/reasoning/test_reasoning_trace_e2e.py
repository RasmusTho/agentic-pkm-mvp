from __future__ import annotations

import json
from uuid import UUID

import pytest

from app.agents.set_evaluator.agent import run_set_evaluator
from app.llm.trace_inspect import load_trace
from app.reasoning.provider import get_reasoner
from app.reasoning.schema import ReasoningInput
from app.reasoning.multi import run_multi_note_reasoning
from app.stores import get_object_store, reset_store_backends


def _fake_reasoning_json(object_uuid: str) -> str:
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
                    "source_ref": "note.md",
                    "kind": "document",
                    "strength": 0.8,
                }
            ],
            "inferences": [
                {"id": "i1", "premises": ["c1"], "conclusion_id": "c1", "type": "support", "rationale": "ok"},
            ],
        }
    )


def _setup_trace_env(monkeypatch: pytest.MonkeyPatch, trace_path) -> None:
    monkeypatch.setenv("LLM_TRACE_ENABLE", "1")
    monkeypatch.setenv("LLM_TRACE_PATH", str(trace_path))
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("REASONING_PROVIDER", "llm")
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.delenv("CI", raising=False)


def test_reasoning_single_note_trace_has_non_empty_response_preview(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    trace_path = tmp_path / "llm-trace.jsonl"
    _setup_trace_env(monkeypatch, trace_path)

    fake_json = _fake_reasoning_json("OBJ-SINGLE")
    monkeypatch.setattr("app.services.llm._deterministic_llm_response", lambda: fake_json)

    reasoner = get_reasoner()
    ri = ReasoningInput(object_uuid="OBJ-SINGLE", text="Note A about testing.", metadata={"trace_id": "T-single"}, relations=[])
    out = reasoner.reason(ri)

    assert out.claims and out.evidence and out.inferences
    assert trace_path.exists()
    records = load_trace(trace_path)
    reasoning_records = [r for r in records if r.agent == "reasoning"]
    assert reasoning_records, "Expected reasoning trace records"
    assert any("reasoning.claims" in r.kind for r in reasoning_records)
    previews = [r.response_preview for r in reasoning_records]
    assert any("claims" in p or "evidence" in p for p in previews), previews
    assert not all(p.strip() == "{}" for p in previews), "All reasoning previews are {}"


def test_set_evaluator_trace_has_non_empty_response_preview(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    trace_path = tmp_path / "llm-trace.jsonl"
    _setup_trace_env(monkeypatch, trace_path)
    fake_json = _fake_reasoning_json("OBJ-SET")
    monkeypatch.setattr("app.services.llm._deterministic_llm_response", lambda: fake_json)

    reset_store_backends()
    store = get_object_store()
    obj_ids = [UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"), UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")]
    store.put(obj_ids[0], kind="note", source_ref="a.md", payload={"text": "First candidate"})
    store.put(obj_ids[1], kind="note", source_ref="b.md", payload={"text": "Second candidate"})

    result = run_set_evaluator([str(obj_ids[0]), str(obj_ids[1])], question="Which is better?", trace_id="T-set")
    assert result.ranking

    records = load_trace(trace_path)
    set_eval_records = [r for r in records if r.agent == "set_evaluator"]
    assert set_eval_records, "Expected set_evaluator trace records"
    assert any("reasoning.ranking" in r.kind or "set_eval" in r.kind for r in set_eval_records)
    previews = [r.response_preview for r in set_eval_records]
    assert not all(p.strip() == "{}" for p in previews), "All set_evaluator previews are {}"
    assert any(p.strip() for p in previews), previews
