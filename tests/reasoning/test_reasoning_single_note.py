from __future__ import annotations

from uuid import UUID

import pytest

from app.agents.pipeline import _collect_relation_snapshots
from app.reasoning.provider import run_reasoning_claims_for_object
from app.reasoning.store import reset_reasoning_store
from app.stores import get_object_store
from tests.helpers.pkm_alpha_helper import load_pkm_alpha_subset_for_reasoning, reset_memory_stores

pytestmark = [pytest.mark.not_pg, pytest.mark.alpha_llm]


@pytest.fixture
def memory_object_store(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("REASONING_PROVIDER", "mock")
    reset_memory_stores()
    yield get_object_store()
    reset_reasoning_store()
    reset_memory_stores()


def run_reasoning_for_object(object_id: str):
    return run_reasoning_claims_for_object(object_id)


def test_reasoning_layer_produces_claims_and_evidence(memory_object_store, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REASONING_ENABLE", "1")
    ids = load_pkm_alpha_subset_for_reasoning(memory_object_store)
    research_id = ids["research"]

    result = run_reasoning_for_object(research_id)

    assert result.claims
    assert all(c.text for c in result.claims)
    assert result.evidence
