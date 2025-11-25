from __future__ import annotations

import os
from uuid import uuid4

import pytest

from app.reasoning.models import ReasoningMode
from app.reasoning.provider import run_reasoning
from app.stores import get_object_store, reset_store_backends


def _set_mock_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("REASONING_PROVIDER", "mock")
    os.environ.pop("CI", None)


def test_run_reasoning_claims_mode_ok_non_empty_result(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_mock_env(monkeypatch)
    reset_store_backends()
    store = get_object_store()
    object_id = uuid4()
    sample_text = "Alpha memo states that solar storage reduces peak load and cites grid stability data."
    store.put(object_id, kind="note", source_ref="a.md", payload={"text": sample_text})

    run = run_reasoning(ReasoningMode.CLAIMS, [str(object_id)])

    assert run.status == "ok"
    assert isinstance(run.result, dict)
    assert "claims" in run.result and "evidence" in run.result
    assert len(run.result.get("claims") or []) >= 1 or len(run.result.get("evidence") or []) >= 1
    assert run.object_uuids == [str(object_id)]


def test_run_reasoning_claims_mode_failed_when_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_mock_env(monkeypatch)
    reset_store_backends()
    store = get_object_store()
    object_id = uuid4()
    store.put(object_id, kind="note", source_ref="b.md", payload={"text": "Unrecognized text for mock reasoner"})

    run = run_reasoning(ReasoningMode.CLAIMS, [str(object_id)])

    assert run.status == "failed"
    assert run.error
    assert run.object_uuids == [str(object_id)]


def test_run_reasoning_review_mode_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_mock_env(monkeypatch)
    reset_store_backends()
    store = get_object_store()
    object_id = uuid4()
    store.put(object_id, kind="note", source_ref="c.md", payload={"text": "Short note for review"})

    run = run_reasoning(ReasoningMode.REVIEW, [str(object_id)])

    assert run.status == "ok"
    assert isinstance(run.result, dict)
    assert run.result.get("summary") or run.result.get("suggestions") or run.result.get("issues")


def test_run_reasoning_ranking_mode_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_mock_env(monkeypatch)
    reset_store_backends()
    store = get_object_store()
    ids = [uuid4(), uuid4()]
    store.put(ids[0], kind="note", source_ref="d.md", payload={"text": "First candidate text"})
    store.put(ids[1], kind="note", source_ref="e.md", payload={"text": "Second candidate text"})

    run = run_reasoning(ReasoningMode.RANKING, [str(ids[0]), str(ids[1])], question="Pick best")

    assert run.status == "ok"
    assert isinstance(run.result, dict)
    ranking = run.result.get("ranking") or []
    assert ranking
    assert all("object_uuid" in entry for entry in ranking)
    assert any((entry.get("reason") or "").strip() for entry in ranking)


def test_run_reasoning_ranking_mode_failed_when_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_mock_env(monkeypatch)
    reset_store_backends()
    run = run_reasoning(ReasoningMode.RANKING, [], question="none")
    assert run.status == "failed"
    assert run.error
