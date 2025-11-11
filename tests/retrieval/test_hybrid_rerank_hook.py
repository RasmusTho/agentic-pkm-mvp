from __future__ import annotations

import importlib

import pytest

pytestmark = pytest.mark.not_pg


@pytest.fixture(autouse=True)
def clear_rerank_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("RERANK_ENABLE", "RERANK_TOP_K", "RERANK_PROVIDER"):
        monkeypatch.delenv(key, raising=False)


def test_hook_is_inert_by_default() -> None:
    mod = importlib.import_module("app.retrieval.hybrid_rerank_hook")
    importlib.reload(mod)
    items = [
        {"id": "a", "text": "alpha beta", "score": 0.9},
        {"id": "b", "text": "beta gamma", "score": 0.8},
        {"id": "c", "text": "gamma delta", "score": 0.7},
    ]
    out = mod.apply_optional_rerank("beta", items)
    assert [o["id"] for o in out] == ["a", "b", "c"]


def test_hook_reorders_when_enabled_with_mock_ce(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RERANK_ENABLE", "1")
    monkeypatch.setenv("RERANK_PROVIDER", "mock_ce")
    mod = importlib.import_module("app.retrieval.hybrid_rerank_hook")
    importlib.reload(mod)
    items = [
        {"id": "a", "text": "alpha beta", "score": 0.9},
        {"id": "b", "text": "beta gamma", "score": 0.8},
        {"id": "c", "text": "gamma delta", "score": 0.7},
    ]
    out = mod.apply_optional_rerank("beta gamma", items)
    assert [o["id"] for o in out][:3] == ["b", "a", "c"]


def test_hook_respects_top_k(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RERANK_ENABLE", "true")
    monkeypatch.setenv("RERANK_PROVIDER", "mock_ce")
    monkeypatch.setenv("RERANK_TOP_K", "2")
    mod = importlib.import_module("app.retrieval.hybrid_rerank_hook")
    importlib.reload(mod)
    items = [
        {"id": "a", "text": "alpha beta", "score": 0.9},
        {"id": "b", "text": "beta gamma", "score": 0.8},
        {"id": "c", "text": "gamma delta", "score": 0.7},
    ]
    out = mod.apply_optional_rerank("beta gamma", items)
    assert [o["id"] for o in out][:2] == ["b", "a"]
    assert {o["id"] for o in out} == {"a", "b", "c"}
