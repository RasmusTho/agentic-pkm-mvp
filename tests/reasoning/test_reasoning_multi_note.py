# Reasoning multi-note entrypoint:
#   app/reasoning/multi.py:run_multi_note_reasoning(...)
from __future__ import annotations

import pytest

from app.reasoning.multi import run_multi_note_reasoning
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


def _reasoning_item_mentions_both_sources(item, ids: set[str]) -> bool:
    text_fields = []
    for attr in ("rationale", "text", "reason"):
        val = getattr(item, attr, None)
        if isinstance(val, str):
            text_fields.append(val)
    combined = " ".join(text_fields)
    return all(str(source_id) in combined for source_id in ids)


def test_reasoning_multi_note_synthesizes_across_pkm_alpha(memory_object_store) -> None:
    ids = load_pkm_alpha_subset_for_reasoning(memory_object_store)
    concept_id = ids["concept"]
    project_id = ids["project"]

    result = run_multi_note_reasoning([concept_id, project_id])

    assert result is not None
    assert result.inferences or result.claims
    assert any(
        _reasoning_item_mentions_both_sources(item, {concept_id, project_id})
        for item in (result.inferences or result.claims or [])
    )
