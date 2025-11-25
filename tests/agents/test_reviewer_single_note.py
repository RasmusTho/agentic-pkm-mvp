from __future__ import annotations

import pytest

from app.agents.reviewer.agent import run as reviewer_run
from app.obs.log import with_trace_id
from app.stores import get_object_store
from tests.helpers.pkm_alpha_helper import load_pkm_alpha_subset_for_reasoning, reset_memory_stores

pytestmark = pytest.mark.not_pg


@pytest.fixture
def memory_object_store(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("REASONING_PROVIDER", "mock")
    reset_memory_stores()
    yield get_object_store()
    reset_memory_stores()
    try:
        import app.agents.reviewer.agent as reviewer_agent

        reviewer_agent._REVIEW_COUNTER["n"] = 0
    except Exception:
        pass


def run_reviewer_for_object(object_id: str) -> dict:
    return reviewer_run(object_id, trace_id=with_trace_id(None))


def test_reviewer_returns_reasoned_feedback(memory_object_store) -> None:
    ids = load_pkm_alpha_subset_for_reasoning(memory_object_store)
    project_id = ids["project"]

    review = run_reviewer_for_object(project_id)

    assert review is not None
    suggestions = review.get("suggestions") or review.get("reasons") or []
    analysis = review.get("analysis") or []
    assert suggestions or analysis or review.get("reasons")
    assert len(suggestions) > 0
    assert isinstance(review.get("allow"), bool)
