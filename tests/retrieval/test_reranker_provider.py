from __future__ import annotations

import contextlib
import importlib
import os

import pytest

pytestmark = pytest.mark.not_pg


def _reload():
    with contextlib.suppress(KeyError):
        del os.environ["RERANK_PROVIDER"]
    import app.retrieval.rerank.provider as provider

    importlib.reload(provider)
    return provider


def test_none_reranker_keeps_order():
    provider = _reload()
    os.environ["RERANK_PROVIDER"] = "none"
    importlib.reload(provider)
    reranker = provider.get_reranker()
    items = [
        provider.RerankItem(id="a", text="alpha beta"),
        provider.RerankItem(id="b", text="beta gamma"),
        provider.RerankItem(id="c", text="gamma delta"),
    ]
    res = reranker.rerank("theta", items)
    assert [r.id for r in res] == ["a", "b", "c"]
    assert all(r.score == 0.0 for r in res)


def test_mock_ce_reranker_orders_by_overlap():
    provider = _reload()
    os.environ["RERANK_PROVIDER"] = "mock_ce"
    importlib.reload(provider)
    reranker = provider.get_reranker()
    items = [
        provider.RerankItem(id="a", text="alpha beta"),
        provider.RerankItem(id="b", text="beta gamma"),
        provider.RerankItem(id="c", text="gamma delta"),
    ]
    res = reranker.rerank("beta gamma", items)
    assert [r.id for r in res] == ["b", "a", "c"]
    assert res[0].score >= res[1].score >= res[2].score


def test_top_k_is_respected():
    provider = _reload()
    os.environ["RERANK_PROVIDER"] = "mock_ce"
    importlib.reload(provider)
    reranker = provider.get_reranker()
    items = [
        provider.RerankItem(id="a", text="alpha beta"),
        provider.RerankItem(id="b", text="beta gamma"),
        provider.RerankItem(id="c", text="gamma delta"),
    ]
    res = reranker.rerank("beta gamma", items, top_k=2)
    assert len(res) == 2
