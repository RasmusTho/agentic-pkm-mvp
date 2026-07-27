"""PLANNING-mode dispatch in ``run_reasoning``.

Regression coverage for the defect where ``ReasoningMode.PLANNING`` was a
first-class enum member with no branch in ``run_reasoning``, so every
``ReasoningFacade.plan()`` call fell through to the terminal
``"mode planning not implemented"`` return.
"""

from __future__ import annotations

import json
from uuid import uuid4

import pytest

from app.reasoning.models import ReasoningMode
from app.reasoning import provider as provider_module
from app.reasoning.provider import run_reasoning
from app.stores import get_object_store, reset_store_backends


def _mock_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("REASONING_PROVIDER", "mock")
    monkeypatch.delenv("CI", raising=False)


def _llm_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("REASONING_PROVIDER", "llm")
    monkeypatch.delenv("CI", raising=False)


def test_planning_mode_returns_structured_plan_on_mock_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_env(monkeypatch)
    reset_store_backends()

    run = run_reasoning(ReasoningMode.PLANNING, [], question="Summarize this thread")

    assert run.status == "ok"
    assert run.error is None
    assert run.mode == ReasoningMode.PLANNING
    assert isinstance(run.result, dict)
    assert run.result.get("plan")
    assert run.result.get("steps")
    # The old terminal fallthrough must no longer be reachable for PLANNING.
    assert "not implemented" not in (run.error or "")


def test_planning_mode_includes_object_context_on_mock_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_env(monkeypatch)
    reset_store_backends()
    store = get_object_store()
    object_id = uuid4()
    store.put(object_id, kind="note", source_ref="p.md", payload={"text": "Planning source note"})

    run = run_reasoning(ReasoningMode.PLANNING, [str(object_id)], question="Plan the rollout")

    assert run.status == "ok"
    assert run.object_uuids == [str(object_id)]


def test_planning_mode_does_not_call_backend_when_provider_is_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # With no LLM_PROVIDER the route resolves to the mock client, which returns
    # a decide-shaped blob unrelated to planning. Match ASK_ANSWER and short-
    # circuit instead of parsing that as a failed plan.
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setenv("REASONING_PROVIDER", "llm")
    monkeypatch.delenv("CI", raising=False)
    reset_store_backends()

    def _must_not_be_called(**_kwargs: object) -> str:  # pragma: no cover - guard
        raise AssertionError("planning must not call the backend on a mock route")

    monkeypatch.setattr(provider_module, "_call_chat", _must_not_be_called)

    run = run_reasoning(ReasoningMode.PLANNING, [], question="Ship the thing")

    assert run.status == "ok"
    assert run.result["plan"]
    assert run.result["steps"]


def test_planning_mode_calls_chat_backend_and_parses_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _llm_env(monkeypatch)
    reset_store_backends()

    calls: list[dict[str, object]] = []

    def _fake_call_chat(**kwargs: object) -> str:
        calls.append(kwargs)
        return json.dumps(
            {"plan": "Ship it in two passes.", "steps": ["Draft the change", "Validate and ship"]}
        )

    monkeypatch.setattr(provider_module, "_call_chat", _fake_call_chat)

    run = run_reasoning(ReasoningMode.PLANNING, [], question="Ship the thing")

    assert run.status == "ok"
    assert run.result == {
        "plan": "Ship it in two passes.",
        "steps": ["Draft the change", "Validate and ship"],
    }
    assert len(calls) == 1
    # PLANNING routes on the router's dedicated "plan" task kind
    # (app/components/llm/router.py routes "plan" to default_reasoning).
    assert calls[0]["task_kind"] == "plan"
    pack = calls[0]["pack"]
    assert isinstance(pack, dict)
    assert "Ship the thing" in pack["user"]


def test_planning_mode_reports_provider_failure_without_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _llm_env(monkeypatch)
    reset_store_backends()

    def _boom(**_kwargs: object) -> str:
        raise RuntimeError("backend exploded")

    monkeypatch.setattr(provider_module, "_call_chat", _boom)

    run = run_reasoning(ReasoningMode.PLANNING, [], question="Ship the thing")

    assert run.status == "failed"
    assert "backend exploded" in (run.error or "")
    assert run.result == {"plan": "", "steps": []}


def test_planning_mode_reports_non_json_response_as_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _llm_env(monkeypatch)
    reset_store_backends()

    monkeypatch.setattr(provider_module, "_call_chat", lambda **_kwargs: "not json at all")

    run = run_reasoning(ReasoningMode.PLANNING, [], question="Ship the thing")

    assert run.status == "failed"
    assert run.error
    assert run.result == {"plan": "", "steps": []}


def test_planning_mode_requires_a_goal(monkeypatch: pytest.MonkeyPatch) -> None:
    _llm_env(monkeypatch)
    reset_store_backends()

    def _must_not_be_called(**_kwargs: object) -> str:  # pragma: no cover - guard
        raise AssertionError("planning must not call the chat backend without a goal")

    monkeypatch.setattr(provider_module, "_call_chat", _must_not_be_called)

    run = run_reasoning(ReasoningMode.PLANNING, [], question="   ")

    assert run.status == "failed"
    assert run.error
    assert run.result == {"plan": "", "steps": []}
