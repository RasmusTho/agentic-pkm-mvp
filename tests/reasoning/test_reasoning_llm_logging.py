from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID

import pytest

from app.agents.set_evaluator.agent import run_set_evaluator
from app.reasoning.multi import run_multi_note_reasoning
from app.reasoning.models import ReasoningMode
from app.reasoning.provider import get_deliberation_agent, run_reasoning
from app.reasoning.schema import Inference, ReasoningInput, ReasoningOutput
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
    # call_llm no longer masks real-provider errors with a canned stub (#2108);
    # simulate a successful ollama call so logging is exercised on a real
    # response rather than the removed error->deterministic fallback.
    monkeypatch.setattr("app.services.llm._ollama_chat", lambda *a, **k: fake_json)

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
    monkeypatch.setattr("app.services.llm._ollama_chat", lambda *a, **k: fake_json)

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


def test_multi_note_trace_preserves_degraded_outcome(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_reasoning_env(monkeypatch)
    empty_json = json.dumps({"claims": [], "evidence": [], "inferences": []})

    captured: list[dict] = []

    def fake_log_llm_call(**kwargs):
        captured.append(kwargs)

    monkeypatch.setattr("app.services.llm.log_llm_call", fake_log_llm_call)
    monkeypatch.setattr("app.services.llm._ollama_chat", lambda *a, **k: empty_json)

    reset_store_backends()
    store = get_object_store()
    obj_ids = [
        UUID("33333333-3333-3333-3333-333333333333"),
        UUID("44444444-4444-4444-4444-444444444444"),
    ]
    store.put(obj_ids[0], kind="note", source_ref="c.md", payload={"text": "Note C content"})
    store.put(obj_ids[1], kind="note", source_ref="d.md", payload={"text": "Note D content"})

    output = run_multi_note_reasoning(
        [str(obj_ids[0]), str(obj_ids[1])], trace_id="T-multi-degraded"
    )

    assert output.outcome == "empty_output"
    assert output.degraded is True
    assert output.degraded_reason == "empty_provider_output"
    assert output.claims == []
    assert output.inferences == []
    assert captured, "trace logging must remain active for empty provider output"
    assert all(entry["trace_id"] == "T-multi-degraded" for entry in captured)


def test_provider_payload_cannot_override_runtime_outcome(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_reasoning_env(monkeypatch)
    provider_json = json.loads(_fake_reasoning_json("55555555-5555-5555-5555-555555555555"))
    provider_json.update(
        {"outcome": "provider_failure", "degraded_reason": "provider_says_failure"}
    )
    monkeypatch.setattr(
        "app.services.llm._ollama_chat", lambda *a, **k: json.dumps(provider_json)
    )

    reset_store_backends()
    store = get_object_store()
    object_id = UUID("55555555-5555-5555-5555-555555555555")
    store.put(object_id, kind="note", source_ref="provider.md", payload={"text": "Provider input"})

    run = run_reasoning(ReasoningMode.CLAIMS, [str(object_id)], trace_id="T-runtime-owned")

    assert run.status == "ok"
    assert run.error is None
    assert run.result["outcome"] == "success"
    assert run.result["degraded_reason"] is None
    assert run.result["claims"][0]["id"] == "c1"


def test_provider_failure_trace_preserves_degraded_outcome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_reasoning_env(monkeypatch)
    reset_store_backends()
    store = get_object_store()
    object_id = UUID("66666666-6666-6666-6666-666666666666")
    store.put(object_id, kind="note", source_ref="failure.md", payload={"text": "Failure input"})

    class FailingAgent:
        def reason(self, reasoning_input: ReasoningInput) -> ReasoningOutput:
            del reasoning_input
            raise RuntimeError("provider secret detail")

    captured: list[dict] = []
    monkeypatch.setattr(
        "app.reasoning.provider.get_deliberation_agent", lambda: FailingAgent()
    )
    monkeypatch.setattr(
        "app.reasoning.provider.log_llm_call",
        lambda **kwargs: captured.append(kwargs),
        raising=False,
    )

    run = run_reasoning(ReasoningMode.CLAIMS, [str(object_id)], trace_id="T-provider-failure")

    assert run.status == "failed"
    assert run.result["outcome"] == "provider_failure"
    assert run.result["degraded_reason"] == "provider_failure"
    assert captured == [
        {
            "provider": "ollama",
            "model": "llama3.1:8b",
            "agent": "reasoning",
            "kind": "reasoning.claims",
            "messages": [],
            "response": {
                "outcome": "provider_failure",
                "degraded_reason": "provider_failure",
            },
            "response_text": json.dumps(
                {
                    "outcome": "provider_failure",
                    "degraded_reason": "provider_failure",
                },
                sort_keys=True,
            ),
            "trace_id": "T-provider-failure",
            "status": "failed",
        }
    ]


def test_inference_only_provider_output_is_not_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_reasoning_env(monkeypatch)
    reset_store_backends()
    store = get_object_store()
    object_id = UUID("77777777-7777-7777-7777-777777777777")
    store.put(object_id, kind="note", source_ref="inference.md", payload={"text": "Inference input"})

    class InferenceOnlyAgent:
        def reason(self, reasoning_input: ReasoningInput) -> ReasoningOutput:
            return ReasoningOutput(
                inferences=[
                    Inference(
                        id="inference-only",
                        premises=[],
                        conclusion_id=reasoning_input.object_uuid,
                        type="observation",
                        rationale="Structured provider inference",
                    )
                ]
            )

    monkeypatch.setattr(
        "app.reasoning.provider.get_deliberation_agent", lambda: InferenceOnlyAgent()
    )

    run = run_reasoning(ReasoningMode.CLAIMS, [str(object_id)])

    assert run.status == "ok"
    assert run.result["outcome"] == "success"
    assert run.result["inferences"][0]["id"] == "inference-only"


def test_set_evaluator_logs_real_json(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_reasoning_env(monkeypatch)

    captured: list[dict] = []

    def fake_log_llm_call(**kwargs):
        captured.append(kwargs)

    monkeypatch.setattr("app.services.llm.log_llm_call", fake_log_llm_call)

    def _fake_ranking_chat(system, user, *args, **kwargs):
        import re

        uuids = list(dict.fromkeys(re.findall(r"[0-9a-fA-F-]{36}", user)))
        ranking = [
            {"object_uuid": u, "score": max(0.1, 1.0 - 0.05 * i), "reason": f"ranked {u}"}
            for i, u in enumerate(uuids)
        ]
        return json.dumps({"ranking": ranking})

    monkeypatch.setattr("app.services.llm._ollama_chat", _fake_ranking_chat)

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
