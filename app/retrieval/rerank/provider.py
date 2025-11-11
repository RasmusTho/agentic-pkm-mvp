from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable, List, Protocol

import httpx


@dataclass(frozen=True)
class RerankItem:
    id: str
    text: str
    vec: list[float] | None = None
    meta: dict | None = None


@dataclass(frozen=True)
class RerankResult:
    id: str
    score: float


class BaseReranker(Protocol):
    def rerank(self, query: str, items: Iterable[RerankItem], top_k: int | None = None) -> List[RerankResult]:
        ...


class NoneReranker:
    def rerank(self, query: str, items: Iterable[RerankItem], top_k: int | None = None) -> List[RerankResult]:
        out = [RerankResult(id=i.id, score=0.0) for i in items]
        return out[: top_k or len(out)]


class MockCrossEncoderReranker:
    def rerank(self, query: str, items: Iterable[RerankItem], top_k: int | None = None) -> List[RerankResult]:
        q_tokens = _norm_tokens(query)
        scored: list[tuple[float, str]] = []
        for i in items:
            t_tokens = _norm_tokens(i.text)
            overlap = len(q_tokens.intersection(t_tokens))
            len_penalty = 1.0 + 0.01 * max(0, len(t_tokens) - 50)
            score = overlap / len_penalty
            scored.append((score, i.id))
        scored.sort(key=lambda x: x[0], reverse=True)
        res = [RerankResult(id=id_, score=score) for score, id_ in scored]
        return res[: top_k or len(res)]


class LocalCrossEncoderReranker:
    """
    Deterministic token overlap + positional bonus used in CI.
    """

    def __init__(self, *, model: str | None = None) -> None:
        self.model = model or os.getenv("RERANK_CE_LOCAL_MODEL", "ce-local-mini")

    def rerank(self, query: str, items: Iterable[RerankItem], top_k: int | None = None) -> List[RerankResult]:
        q_tokens = _norm_tokens(query)
        ranked: list[tuple[float, str]] = []
        for idx, item in enumerate(items):
            tokens = _norm_tokens(item.text)
            overlap = len(tokens.intersection(q_tokens))
            prefix_bonus = 0.1 * max(0, len(item.text.split()) - 40)
            recency_penalty = 0.01 * idx
            score = overlap - prefix_bonus - recency_penalty
            ranked.append((score, item.id))
        ranked.sort(key=lambda tup: tup[0], reverse=True)
        res = [RerankResult(id=id_, score=score) for score, id_ in ranked]
        return res[: top_k or len(res)]


def _fallback_rerank(query: str, items: Iterable[RerankItem], top_k: int | None = None) -> List[RerankResult]:
    return MockCrossEncoderReranker().rerank(query, items, top_k=top_k)


class HttpCrossEncoderReranker:
    """
    Simple HTTP JSON API client guarded by environment variables.
    """

    def __init__(self, *, endpoint: str | None = None, timeout: float | None = None) -> None:
        alt = os.getenv("CE_HTTP_URL", "").strip()
        self.endpoint = endpoint or os.getenv("RERANK_HTTP_ENDPOINT", "").strip() or alt
        if not self.endpoint:
            raise RuntimeError("RERANK_HTTP_ENDPOINT is required for ce_http provider")
        self.timeout = timeout or float(os.getenv("RERANK_HTTP_TIMEOUT", "2.5"))

    def rerank(self, query: str, items: Iterable[RerankItem], top_k: int | None = None) -> List[RerankResult]:
        payload = {
            "query": query,
            "items": [{"id": i.id, "text": i.text} for i in items],
            "top_k": top_k,
        }
        try:
            resp = httpx.post(self.endpoint, json=payload, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json() or {}
            scores = data.get("scores") or []
            results: list[RerankResult] = []
            seen: set[str] = set()
            for entry in scores:
                item_id = str(entry.get("id") or "")
                if not item_id:
                    continue
                seen.add(item_id)
                results.append(
                    RerankResult(
                        id=item_id,
                        score=float(entry.get("score", 0.0)),
                    )
                )
            tail = [
                RerankResult(id=item.id, score=0.0)
                for item in payload["items"]
                if item["id"] not in seen
            ]
            results.extend(tail)
            if top_k:
                results = results[:top_k]
            return results
        except Exception:
            return _fallback_rerank(query, items, top_k=top_k)


def _norm_tokens(s: str) -> set[str]:
    return set("".join(ch.lower() if ch.isalnum() else " " for ch in s).split())


def select_provider(name: str | None = None) -> BaseReranker:
    spec = (name or os.getenv("RERANK_PROVIDER", "none")).strip().lower()
    try:
        if spec in ("none", "", "off", "disabled"):
            return NoneReranker()
        if spec in ("mock", "mock_ce", "mock-cross-encoder"):
            return MockCrossEncoderReranker()
        if spec in ("ce_local", "local"):
            return LocalCrossEncoderReranker()
        if spec in ("ce_http", "http"):
            return HttpCrossEncoderReranker()
    except Exception:
        return MockCrossEncoderReranker()
    return NoneReranker()


def get_reranker() -> BaseReranker:
    return select_provider()
