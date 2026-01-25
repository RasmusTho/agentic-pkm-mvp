from __future__ import annotations

import os
import pytest
from uuid import UUID

from app.llm.trace_inspect import load_trace
from app.reasoning.provider import run_reasoning, ReasoningMode
from app.agents.set_evaluator.agent import run_set_evaluator
from app.stores import get_object_store
from app.reasoning.store import reset_reasoning_store
from tests.helpers.pkm_alpha_helper import load_pkm_alpha_subset_for_reasoning, reset_memory_stores

pytestmark = [pytest.mark.alpha_llm_live, pytest.mark.alpha_llm]


def _prime_store(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("STORE_BACKEND", "memory")
    reset_memory_stores()
    return get_object_store()


def _preview_has_content(preview) -> bool:
    """Return True if an LLM trace preview represents non-empty content.

    Historically, tests assumed response_preview was a string. The trace layer now uses
    safe_preview() which returns a dict (e.g., {"sha256": ..., "chars": N}). We accept both
    shapes to keep the live LLM assertions stable across preview implementations.
    """
    if preview is None:
        return False
    if isinstance(preview, dict):
        try:
            return int(preview.get("chars", 0)) > 0
        except Exception:
            return False
    try:
        return bool(str(preview).strip()) and str(preview).strip() != "{}"
    except Exception:
        return False


@pytest.mark.alpha_llm_live
def test_reasoning_single_note_live_llm_has_non_empty_response_preview(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    if os.getenv("ALPHA_LLM_LIVE", "0") != "1":
        pytest.skip("Set ALPHA_LLM_LIVE=1 to run live LLM trace assertions")
    if os.getenv("CI") == "1":
        pytest.skip("Live LLM tests are opt-in only")
    trace_path = tmp_path / "llm-trace-live.jsonl"
    monkeypatch.setenv("LLM_TRACE_ENABLE", "1")
    monkeypatch.setenv("LLM_TRACE_PATH", str(trace_path))
    monkeypatch.setenv("LLM_PROVIDER", "llm")
    monkeypatch.setenv("REASONING_PROVIDER", "llm")
    monkeypatch.setenv("REASONING_ENABLE", "1")

    store = _prime_store(monkeypatch)
    ids = load_pkm_alpha_subset_for_reasoning(store)
    obj_id = ids["research"]

    run = run_reasoning(ReasoningMode.CLAIMS, [obj_id], trace_id="T-live-claims")
    assert run.status == "ok"

    records = load_trace(trace_path)
    reasoning_records = [r for r in records if r.agent == "reasoning"]
    assert reasoning_records, "Expected at least one reasoning trace record"
    assert any("reasoning.claims" in r.kind for r in reasoning_records)
    previews = [r.response_preview for r in reasoning_records]
    assert any(_preview_has_content(p) for p in previews), previews


@pytest.mark.alpha_llm_live
def test_set_evaluator_live_llm_has_non_empty_response_preview(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    if os.getenv("ALPHA_LLM_LIVE", "0") != "1":
        pytest.skip("Set ALPHA_LLM_LIVE=1 to run live LLM trace assertions")
    if os.getenv("CI") == "1":
        pytest.skip("Live LLM tests are opt-in only")
    trace_path = tmp_path / "llm-trace-live-set.jsonl"
    monkeypatch.setenv("LLM_TRACE_ENABLE", "1")
    monkeypatch.setenv("LLM_TRACE_PATH", str(trace_path))
    monkeypatch.setenv("LLM_PROVIDER", "llm")
    monkeypatch.setenv("REASONING_PROVIDER", "llm")
    monkeypatch.setenv("REASONING_ENABLE", "1")

    store = _prime_store(monkeypatch)
    ids = load_pkm_alpha_subset_for_reasoning(store)
    candidates = [ids["concept"], ids["project"]]

    result = run_set_evaluator(candidates, question="Which note is more actionable?", trace_id="T-live-set")
    assert result.ranking

    records = load_trace(trace_path)
    set_eval_records = [r for r in records if r.agent == "set_evaluator"]
    assert set_eval_records, "Expected at least one set_evaluator trace record"
    assert any("reasoning.ranking" in r.kind or "set_eval" in r.kind for r in set_eval_records)
    previews = [r.response_preview for r in set_eval_records]
    assert any(_preview_has_content(p) for p in previews), previews

    reset_reasoning_store()
    reset_memory_stores()
