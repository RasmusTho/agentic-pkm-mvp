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


def test_ce_local_provider(monkeypatch: pytest.MonkeyPatch):
    provider = _reload()
    monkeypatch.setenv("RERANK_PROVIDER", "ce_local")
    importlib.reload(provider)
    reranker = provider.get_reranker()
    items = [
        provider.RerankItem(id="a", text="alpha zero beta gamma"),
        provider.RerankItem(id="b", text="beta gamma delta"),
        provider.RerankItem(id="c", text="unrelated content"),
    ]
    res = reranker.rerank("beta gamma alpha", items)
    assert [r.id for r in res][:2] == ["a", "b"]


def test_ce_http_provider(monkeypatch: pytest.MonkeyPatch):
    provider = _reload()
    monkeypatch.setenv("RERANK_PROVIDER", "ce_http")
    monkeypatch.setenv("RERANK_HTTP_ENDPOINT", "https://rerank.local")

    class DummyResponse:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self):
            return self._payload

    def fake_post(url, json, timeout):
        assert url == "https://rerank.local"
        assert json["query"] == "beta gamma"
        return DummyResponse({"scores": [{"id": "b", "score": 0.91}, {"id": "a", "score": 0.5}]})

    monkeypatch.setattr(provider.httpx, "post", fake_post)
    importlib.reload(provider)
    reranker = provider.get_reranker()
    items = [
        provider.RerankItem(id="a", text="alpha beta"),
        provider.RerankItem(id="b", text="beta gamma"),
        provider.RerankItem(id="c", text="gamma delta"),
    ]
    res = reranker.rerank("beta gamma", items)
    assert [r.id for r in res][:2] == ["b", "a"]


def test_ce_http_fallback_to_mock(monkeypatch: pytest.MonkeyPatch):
    provider = _reload()
    monkeypatch.setenv("RERANK_PROVIDER", "ce_http")
    monkeypatch.setenv("RERANK_HTTP_ENDPOINT", "https://rerank.local")

    def fake_post(url, json, timeout):
        raise RuntimeError("network down")

    monkeypatch.setattr(provider.httpx, "post", fake_post)
    importlib.reload(provider)
    reranker = provider.get_reranker()
    items = [
        provider.RerankItem(id="a", text="alpha beta"),
        provider.RerankItem(id="b", text="beta gamma"),
        provider.RerankItem(id="c", text="gamma delta"),
    ]
    res = reranker.rerank("beta gamma", items)
    assert [r.id for r in res][:2] == ["b", "a"]
