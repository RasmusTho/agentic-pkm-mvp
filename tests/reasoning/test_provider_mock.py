from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.reasoning.provider import MockReasoner, OllamaReasoner, get_reasoner
from app.reasoning.schema import ReasoningInput, RelationSnapshot

pytestmark = pytest.mark.not_pg


def test_mock_reasoner_returns_fixture() -> None:
    samples = Path("data/golden/reasoning_samples.jsonl").read_text(encoding="utf-8").splitlines()
    fixture = json.loads(samples[0])
    reasoner = MockReasoner()
    result = reasoner.reason(
        ReasoningInput(
            object_uuid=fixture["object_uuid"],
            text=fixture["text"],
            relations=[RelationSnapshot.model_validate(rel) for rel in fixture.get("relations") or []],
        )
    )
    assert len(result.claims) == len(fixture["claims"])
    assert result.claims[0].text.startswith("Solar storage")


def test_get_reasoner_falls_back_to_mock_when_ollama_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setenv("REASONING_PROVIDER", "ollama")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    assert isinstance(get_reasoner(), MockReasoner)


def test_get_reasoner_uses_ollama_when_llm_provider_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setenv("REASONING_PROVIDER", "ollama")
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    assert isinstance(get_reasoner(), OllamaReasoner)
