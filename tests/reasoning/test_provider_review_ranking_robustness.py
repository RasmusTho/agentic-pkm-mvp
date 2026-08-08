"""Regression coverage for REVIEW/RANKING provider failure handling."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.reasoning import provider as provider_module
from app.reasoning.models import ReasoningMode
from app.reasoning.provider import run_reasoning
from app.stores import get_object_store, reset_store_backends


def _llm_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("REASONING_PROVIDER", "llm")
    monkeypatch.delenv("CI", raising=False)


def _store_note() -> str:
    store = get_object_store()
    object_id = uuid4()
    store.put(object_id, kind="note", source_ref="note.md", payload={"text": "A note to reason about."})
    return str(object_id)


def test_review_rejects_non_object_json_without_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _llm_env(monkeypatch)
    reset_store_backends()
    object_id = _store_note()
    monkeypatch.setattr(provider_module, "_call_chat", lambda **_kwargs: '["not", "an object"]')

    run = run_reasoning(ReasoningMode.REVIEW, [object_id])

    assert run.status == "failed"
    assert run.error
    assert run.result == {"summary": "", "issues": [], "suggestions": []}


def test_ranking_rejects_non_object_json_without_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _llm_env(monkeypatch)
    reset_store_backends()
    object_id = _store_note()
    monkeypatch.setattr(provider_module, "_call_chat", lambda **_kwargs: '"not an object"')

    run = run_reasoning(ReasoningMode.RANKING, [object_id], question="Rank this")

    assert run.status == "failed"
    assert run.error
    assert run.result == {"ranking": []}


def test_review_uses_mock_result_when_provider_is_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("REASONING_PROVIDER", "llm")
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("CI", raising=False)
    reset_store_backends()
    object_id = _store_note()

    def _must_not_be_called(**_kwargs: object) -> str:  # pragma: no cover - guard
        raise AssertionError("review must not call the chat backend on a mock route")

    monkeypatch.setattr(provider_module, "_call_chat", _must_not_be_called)

    run = run_reasoning(ReasoningMode.REVIEW, [object_id])

    assert run.status == "ok"
    assert run.result["summary"].startswith("Summary:")


def test_review_honors_forced_real_provider_before_mock_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("REASONING_PROVIDER", "llm")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("LLM_FORCE_PROVIDER", "ollama")
    monkeypatch.delenv("CI", raising=False)
    reset_store_backends()
    object_id = _store_note()
    calls = []

    def _chat(**_kwargs: object) -> str:
        calls.append(_kwargs)
        return '{"summary": "routed review", "issues": [], "suggestions": []}'

    monkeypatch.setattr(provider_module, "_call_chat", _chat)

    run = run_reasoning(ReasoningMode.REVIEW, [object_id])

    assert run.status == "ok"
    assert run.result["summary"] == "routed review"
    assert len(calls) == 1


def test_ranking_uses_mock_result_when_provider_is_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("REASONING_PROVIDER", "llm")
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("CI", raising=False)
    reset_store_backends()
    object_id = _store_note()

    def _must_not_be_called(**_kwargs: object) -> str:  # pragma: no cover - guard
        raise AssertionError("ranking must not call the chat backend on a mock route")

    monkeypatch.setattr(provider_module, "_call_chat", _must_not_be_called)

    run = run_reasoning(ReasoningMode.RANKING, [object_id], question="Rank this")

    assert run.status == "ok"
    assert run.result["ranking"]


def test_ranking_honors_forced_real_provider_before_mock_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("REASONING_PROVIDER", "llm")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("LLM_FORCE_PROVIDER", "ollama")
    monkeypatch.delenv("CI", raising=False)
    reset_store_backends()
    object_id = _store_note()
    calls = []

    def _chat(**_kwargs: object) -> str:
        calls.append(_kwargs)
        return (
            '{"ranking": [{"object_uuid": "'
            + object_id
            + '", "score": 0.9, "reason": "routed ranking"}]}'
        )

    monkeypatch.setattr(provider_module, "_call_chat", _chat)

    run = run_reasoning(ReasoningMode.RANKING, [object_id], question="Rank this")

    assert run.status == "ok"
    assert run.result["ranking"][0]["reason"] == "routed ranking"
    assert len(calls) == 1
