# SetEvaluator entrypoint:
#   app/agents/set_evaluator/agent.py:run_set_evaluator(...)
from __future__ import annotations

import pytest

from app.agents.set_evaluator.agent import run_set_evaluator
from app.reasoning.store import reset_reasoning_store
from app.stores import get_object_store
from tests.helpers.pkm_alpha_helper import load_pkm_alpha_subset_for_reasoning, reset_memory_stores


@pytest.fixture
def memory_object_store(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("REASONING_PROVIDER", "mock")
    monkeypatch.setenv("REASONING_ENABLE", "1")
    reset_memory_stores()
    yield get_object_store()
    reset_reasoning_store()
    reset_memory_stores()


def test_set_evaluator_ranks_pkm_alpha_candidates_with_reasons(memory_object_store) -> None:
    ids = load_pkm_alpha_subset_for_reasoning(memory_object_store)
    candidates = [ids["concept"], ids["project"], ids["research"]]

    result = run_set_evaluator(
        object_ids=candidates,
        question="Which note is the best basis for an evergreen about PKM zones and cognitive load?",
    )

    assert result is not None
    assert result.ranking
    assert len(result.ranking) == len(candidates)

    for item in result.ranking:
        reasons = getattr(item, "reasons", None) or [getattr(item, "explanation", "")]
        assert reasons
        assert all(isinstance(r, str) and r.strip() for r in reasons)
