from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable, List, Protocol


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


def _norm_tokens(s: str) -> set[str]:
    return set("".join(ch.lower() if ch.isalnum() else " " for ch in s).split())


def get_reranker() -> BaseReranker:
    name = os.getenv("RERANK_PROVIDER", "none").strip().lower()
    if name in ("none", "", "off", "disabled"):
        return NoneReranker()
    if name in ("mock", "mock_ce", "mock-cross-encoder"):
        return MockCrossEncoderReranker()
    return NoneReranker()
