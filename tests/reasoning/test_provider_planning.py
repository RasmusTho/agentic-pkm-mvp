"""PLANNING-mode dispatch in ``run_reasoning``.

Regression coverage for the defect where ``ReasoningMode.PLANNING`` was a
first-class enum member with no branch in ``run_reasoning``, so every
``ReasoningModeFacade.plan()`` call fell through to the terminal
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


def test_planning_mode_carries_object_uuids_on_mock_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The mock branch does not consume object text; it must still report the
    # object identities it was given. Prompt-level context is asserted on the
    # real backend path in test_planning_mode_sends_object_context_to_backend.
    _mock_env(monkeypatch)
    reset_store_backends()
    store = get_object_store()
    object_id = uuid4()
    store.put(object_id, kind="note", source_ref="p.md", payload={"text": "Planning source note"})

    run = run_reasoning(ReasoningMode.PLANNING, [str(object_id)], question="Plan the rollout")

    assert run.status == "ok"
    assert run.object_uuids == [str(object_id)]


def test_planning_mode_sends_object_context_to_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _llm_env(monkeypatch)
    reset_store_backends()
    store = get_object_store()
    object_id = uuid4()
    store.put(
        object_id,
        kind="note",
        source_ref="p.md",
        payload={"text": "Rollout depends on the migration landing first"},
    )

    captured: list[dict[str, object]] = []

    def _fake_call_chat(**kwargs: object) -> str:
        captured.append(kwargs)
        return json.dumps({"plan": "p", "steps": ["s"]})

    monkeypatch.setattr(provider_module, "_call_chat", _fake_call_chat)

    run = run_reasoning(ReasoningMode.PLANNING, [str(object_id)], question="Plan the rollout")

    assert run.status == "ok"
    pack = captured[0]["pack"]
    assert isinstance(pack, dict)
    user_prompt = pack["user"]
    assert "Context:" in user_prompt
    assert str(object_id) in user_prompt
    assert "migration landing first" in user_prompt


def test_planning_mode_uses_shared_model_access_router(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _llm_env(monkeypatch)
    reset_store_backends()
    routes = []
    calls = []

    class _Client:
        route = type(
            "Route",
            (),
            {
                "provider": "ollama",
                "model": "llama3.1:8b",
                "mode": "chat",
                "reason": "test",
                "degraded": False,
            },
        )()

        def chat(self, name, pack, **kwargs):
            calls.append((name, pack, kwargs))
            return json.dumps({"plan": "Bound plan", "steps": ["one step"]})

    def _get_chat_client_for_route(intent, *, selected_route=None):
        routes.append((intent, selected_route))
        return _Client()

    monkeypatch.setattr(
        provider_module, "get_chat_client_for_route", _get_chat_client_for_route
    )
    run = run_reasoning(
        ReasoningMode.PLANNING, [], question="Plan via the shared router"
    )

    assert run.status == "ok"
    assert run.result == {"plan": "Bound plan", "steps": ["one step"]}
    assert len(routes) == 1 and routes[0][0].task_kind == "plan"
    assert len(calls) == 1 and calls[0][0] == "plan"


def test_reasoning_failure_reports_bound_route_after_model_promotion(monkeypatch) -> None:
    initial_route = type("Route", (), {"provider": "openai", "model": "gpt-5.6-luna"})()
    bound_route = type("Route", (), {"provider": "openai", "model": "gpt-6-luna"})()

    class _Client:
        route = bound_route

        def chat(self, *_args, **_kwargs):
            raise RuntimeError("completion failed")

    monkeypatch.setattr(
        provider_module,
        "resolve_effective_reasoning_route",
        lambda **_kwargs: initial_route,
    )
    monkeypatch.setattr(
        provider_module,
        "get_chat_client_for_route",
        lambda *_args, **_kwargs: _Client(),
    )

    with pytest.raises(provider_module.ReasoningRouteExecutionError) as error:
        provider_module._call_chat_with_route(
            task_kind="plan",
            pack={"system": "", "user": "test"},
            agent=None,
            kind=None,
            trace_id=None,
        )

    assert error.value.route is bound_route


def test_planning_mode_rejects_non_object_json_without_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Valid JSON that is not an object must fail closed, not raise
    # AttributeError out of run_reasoning.
    _llm_env(monkeypatch)
    reset_store_backends()

    for payload in ('["a", "b"]', '"just a string"', "42"):

        def _fake_call_chat(_payload: str = payload, **_kwargs: object) -> str:
            return _payload

        monkeypatch.setattr(provider_module, "_call_chat", _fake_call_chat)

        run = run_reasoning(ReasoningMode.PLANNING, [], question="Ship the thing")

        assert run.status == "failed", payload
        assert run.error
        assert run.result == {"plan": "", "steps": []}


def test_planning_mode_normalizes_steps_to_a_list_of_strings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _llm_env(monkeypatch)
    reset_store_backends()

    monkeypatch.setattr(
        provider_module,
        "_call_chat",
        lambda **_k: json.dumps({"plan": "do it", "steps": [1, {"a": 2}]}),
    )

    run = run_reasoning(ReasoningMode.PLANNING, [], question="Ship the thing")

    assert run.status == "ok"
    assert run.result["steps"] == ["1", "{'a': 2}"]

    # A scalar `steps` must not leak through as a non-list.
    monkeypatch.setattr(
        provider_module,
        "_call_chat",
        lambda **_k: json.dumps({"plan": "do it", "steps": "not a list"}),
    )

    run = run_reasoning(ReasoningMode.PLANNING, [], question="Ship the thing")

    assert run.status == "ok"
    assert run.result["steps"] == []
    assert run.result["plan"] == "do it"


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
