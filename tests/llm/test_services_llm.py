from __future__ import annotations

import json

from app.services.llm import call_llm


def test_call_llm_uses_mock_response(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("LLM_MOCK_RESPONSE", "Mock response [#1]")

    result = call_llm("qa", {"system": "", "user": "hi"}, kind="qa.draft")

    assert result == "Mock response [#1]"


def test_call_llm_preserves_reasoning_shape(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("LLM_MOCK_RESPONSE", "Mock response [#1]")

    result = call_llm("reasoning", {"system": "", "user": "hi"}, kind="reasoning.claims")
    payload = json.loads(result)

    assert "claims" in payload
