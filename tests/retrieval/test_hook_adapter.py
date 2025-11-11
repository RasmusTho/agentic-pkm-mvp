from __future__ import annotations

import importlib
import os

import pytest

pytestmark = pytest.mark.not_pg


@pytest.fixture(autouse=True)
def clear_rerank_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("RERANK_ENABLE", "RERANK_PROVIDER", "RERANK_TOP_K"):
        monkeypatch.delenv(key, raising=False)


def test_default_path_preserves_order(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = importlib.import_module("app.retrieval.hook_adapter")
    importlib.reload(mod)
    items = [{"id": "a", "text": "x"}, {"id": "b", "text": "y"}, {"id": "c", "text": "z"}]
    out = mod.maybe_rerank("q", items)
    assert [o["id"] for o in out] == ["a", "b", "c"]


def test_enabled_uses_mock_ce_ordering(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RERANK_ENABLE", "1")
    monkeypatch.setenv("RERANK_PROVIDER", "mock_ce")
    mod = importlib.import_module("app.retrieval.hook_adapter")
    importlib.reload(mod)
    items = [
        {"id": "a", "text": "alpha beta"},
        {"id": "b", "text": "beta gamma"},
        {"id": "c", "text": "gamma delta"},
    ]
    out = mod.maybe_rerank("beta gamma", items)
    assert [o["id"] for o in out][:3] == ["b", "a", "c"]
