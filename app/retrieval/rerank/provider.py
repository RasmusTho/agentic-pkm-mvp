from __future__ import annotations

import math
import os
from collections import Counter
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
    Deterministic token + phrase heuristic used in CI.
    """

    def __init__(self, *, model: str | None = None) -> None:
        self.model = model or os.getenv("RERANK_CE_LOCAL_MODEL", "ce-local-mini")

    def rerank(self, query: str, items: Iterable[RerankItem], top_k: int | None = None) -> List[RerankResult]:
        q_tokens = _tokenize(query)
        query_counts = Counter(q_tokens)
        unique_terms = set(query_counts)
        query_phrases = _ngram_phrases(q_tokens)
        idf_weights = {term: 1.0 + math.log1p(len(q_tokens) / query_counts[term]) for term in unique_terms} if q_tokens else {}

        ranked: list[tuple[float, float, int, str]] = []
        for idx, item in enumerate(items):
            doc_tokens = _tokenize(item.text)
            doc_counts = Counter(doc_tokens)
            term_score = 0.0
            matched_terms = 0
            for term, q_freq in query_counts.items():
                doc_freq = doc_counts.get(term, 0)
                if not doc_freq:
                    continue
                matched_terms += 1
                capped = min(doc_freq, 3)
                freq_bonus = 1.0 + min(q_freq, 3) * 0.1
                weight = idf_weights.get(term, 1.0)
                term_score += weight * capped * freq_bonus

            phrase_bonus = 0.0
            if doc_tokens and query_phrases:
                doc_phrase_set = _ngram_phrases(doc_tokens)
                overlap_phrases = doc_phrase_set.intersection(query_phrases)
                for phrase in overlap_phrases:
                    length = phrase.count(" ") + 1
                    phrase_bonus += 0.25 * length

            overlap_ratio = matched_terms / max(1, len(unique_terms))
            length_norm = 1.0
            if len(doc_tokens) > 80:
                length_norm = 1.0 / (1.0 + math.log(len(doc_tokens) / 80))

            base_score = (term_score * length_norm) + phrase_bonus + 0.4 * overlap_ratio
            orig_score = 0.0
            if isinstance(item.meta, dict):
                orig = item.meta.get("score")
                if orig is not None:
                    try:
                        orig_score = float(orig)
                    except (TypeError, ValueError):
                        orig_score = 0.0
            ranked.append((base_score, orig_score, idx, item.id))

        ranked.sort(key=lambda row: (-row[0], -row[1], row[2]))
        res = [RerankResult(id=entry[3], score=entry[0]) for entry in ranked]
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


def _tokenize(text: str) -> list[str]:
    if not text:
        return []
    normalized = "".join(ch.lower() if ch.isalnum() else " " for ch in text)
    return [tok for tok in normalized.split() if tok]


def _ngram_phrases(tokens: list[str], max_n: int = 3) -> set[str]:
    phrases: set[str] = set()
    length = len(tokens)
    for n in range(2, max_n + 1):
        if length < n:
            break
        for idx in range(length - n + 1):
            phrases.add(" ".join(tokens[idx : idx + n]))
    return phrases


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
