# Planner entrypoint:
#   app/planner/provider.py:get_planner(...).plan(...)
# Orchestrator entrypoint:
#   app/orchestrator/runtime.py:Orchestrator.run_plan(...)
from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.orchestrator.runtime import Orchestrator
from app.planner.provider import PlannerInput, get_planner
from app.reasoning.store import reset_reasoning_store
from app.stores import get_object_store
from tests.helpers.pkm_alpha_helper import load_pkm_alpha_subset_for_reasoning, reset_memory_stores

QUESTION = "Based on my existing notes, how should I refine my PKM zone model to reduce cognitive load in my daily work?"
pytestmark = [pytest.mark.not_pg, pytest.mark.alpha_llm]


@pytest.fixture
def memory_object_store(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("REASONING_ENABLE", "1")
    reset_memory_stores()
    yield get_object_store()
    reset_reasoning_store()
    reset_memory_stores()


@pytest.fixture
def settings_runtime(monkeypatch: pytest.MonkeyPatch):
    class RuntimeToggles:
        def enable_planner_and_reasoning(self) -> None:
            monkeypatch.setenv("PLANNER_ENABLE", "1")
            monkeypatch.setenv("ORCHESTRATOR_ENABLE", "1")
            monkeypatch.setenv("REASONING_ENABLE", "1")

    return RuntimeToggles()


@dataclass
class SourceRef:
    object_id: str
    step_id: str


def _load_note_text(object_id: str) -> str:
    store = get_object_store()
    try:
        obj = store.get(UUID(object_id))
    except Exception:
        obj = None
    payload = obj.get("payload") if obj else {}
    if isinstance(payload, dict):
        return str(payload.get("text") or payload.get("content") or "")
    return ""


def run_planner_for_question(question: str, object_id: str):
    planner = get_planner()
    text = _load_note_text(object_id)
    plan_input = PlannerInput(
        object_uuid=object_id,
        goal=question,
        text=text,
        relations=[],
        metadata={},
    )
    return planner.plan(plan_input)


def run_planner_orchestrator_for_question(question: str, object_id: str):
    plan = run_planner_for_question(question, object_id)
    orchestrator = Orchestrator()
    results = orchestrator.run_plan(plan)
    reasons = [step.reason or step.explanation or step.description for step in plan.steps]
    sources = [SourceRef(object_id=object_id, step_id=step.id) for step in plan.steps]
    return SimpleNamespace(
        answer=f"Plan executed for: {question}",
        reasons=reasons,
        analysis=reasons,
        sources=sources,
        plan=plan,
        results=results,
    )


def test_planner_produces_multi_step_plan_with_reasons(memory_object_store, settings_runtime) -> None:
    ids = load_pkm_alpha_subset_for_reasoning(memory_object_store)
    settings_runtime.enable_planner_and_reasoning()

    plan = run_planner_for_question(QUESTION, ids["project"])

    assert plan is not None
    assert plan.steps
    assert len(plan.steps) >= 2
    for step in plan.steps:
        text = getattr(step, "reason", None) or getattr(step, "explanation", "")
        assert isinstance(text, str) and text.strip()


def test_planner_orchestrator_flow_produces_reasoned_answer(memory_object_store, settings_runtime) -> None:
    ids = load_pkm_alpha_subset_for_reasoning(memory_object_store)
    settings_runtime.enable_planner_and_reasoning()

    result = run_planner_orchestrator_for_question(QUESTION, ids["concept"])

    assert result is not None
    assert getattr(result, "answer", None)
    assert getattr(result, "reasons", None) or getattr(result, "analysis", None) or getattr(result, "trace", None)
    sources = getattr(result, "sources", []) or []
    assert any(getattr(src, "object_id", None) in ids.values() for src in sources)
