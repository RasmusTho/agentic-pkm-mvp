from __future__ import annotations

import contextlib
import importlib
import os

import pytest

pytestmark = pytest.mark.not_pg


def _reset_env() -> None:
    for key in ("RERANK_ENABLE", "RERANK_TOP_K", "RERANK_PROVIDER"):
        with contextlib.suppress(KeyError):
            del os.environ[key]


def test_hook_is_inert_by_default() -> None:
    _reset_env()
    mod = importlib.import_module("app.retrieval.hybrid_rerank_hook")
    importlib.reload(mod)
    items = [
        {"id": "a", "text": "alpha beta", "score": 0.9},
        {"id": "b", "text": "beta gamma", "score": 0.8},
        {"id": "c", "text": "gamma delta", "score": 0.7},
    ]
    out = mod.apply_optional_rerank("beta", items)
    assert [o["id"] for o in out] == ["a", "b", "c"]


def test_hook_reorders_when_enabled_with_mock_ce() -> None:
    _reset_env()
    os.environ["RERANK_ENABLE"] = "1"
    os.environ["RERANK_PROVIDER"] = "mock_ce"
    mod = importlib.import_module("app.retrieval.hybrid_rerank_hook")
    importlib.reload(mod)
    items = [
        {"id": "a", "text": "alpha beta", "score": 0.9},
        {"id": "b", "text": "beta gamma", "score": 0.8},
        {"id": "c", "text": "gamma delta", "score": 0.7},
    ]
    out = mod.apply_optional_rerank("beta gamma", items)
    assert [o["id"] for o in out][:3] == ["b", "a", "c"]


def test_hook_respects_top_k() -> None:
    _reset_env()
    os.environ["RERANK_ENABLE"] = "true"
    os.environ["RERANK_PROVIDER"] = "mock_ce"
    os.environ["RERANK_TOP_K"] = "2"
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
