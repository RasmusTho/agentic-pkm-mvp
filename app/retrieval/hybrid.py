from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, List, Optional

import numpy as np
from rank_bm25 import BM25Okapi
from rapidfuzz import process

from app.index.embeddings import embed_batches, embed_text
from app.retrieval.hook_adapter import maybe_rerank


@dataclass
class Document:
    doc_id: str
    text: str
    language: Optional[str] = None
    source_ref: Optional[str] = None
    payload: dict[str, Any] | None = None


class MemoryHybridStore:
    def __init__(self) -> None:
        self._docs: List[Document] = []
        self._bm25: Optional[BM25Okapi] = None
        self._tokenized: Optional[List[List[str]]] = None
        self._embeddings: Optional[np.ndarray] = None
        self._emb_norms: Optional[np.ndarray] = None

    def _invalidate(self) -> None:
        self._bm25 = None
        self._tokenized = None
        self._embeddings = None
        self._emb_norms = None

    def add_document(
        self,
        *,
        doc_id: str,
        text: str,
        language: Optional[str] = None,
        source_ref: Optional[str] = None,
        payload: Optional[dict[str, Any]] = None,
    ) -> None:
        self._docs.append(
            Document(
                doc_id=doc_id,
                text=text,
                language=language,
                source_ref=source_ref,
                payload=dict(payload or {}),
            )
        )
        self._invalidate()

    def set_documents(self, docs: List[dict]) -> None:
        self._docs = [
            Document(
                doc_id=str(doc["doc_id"]),
                text=str(doc["text"]),
                language=doc.get("language"),
                source_ref=doc.get("source_ref"),
                payload=dict(doc.get("payload") or {}),
            )
            for doc in docs
        ]
        self._invalidate()

    def all(self) -> List[Document]:
        return list(self._docs)

    def _ensure_indexes(self) -> None:
        if not self._docs:
            return
        if self._tokenized is None:
            self._tokenized = [
                _tokenize(doc.text, doc.language)
                for doc in self._docs
            ]
        if self._bm25 is None and self._tokenized:
            self._bm25 = BM25Okapi(self._tokenized)
        if self._embeddings is None:
            vectors: List[List[float]] = []
            for chunk in embed_batches((doc.text for doc in self._docs)):
                vectors.extend(chunk)
            if not vectors:
                self._embeddings = np.zeros((0, 0), dtype=np.float32)
                self._emb_norms = np.zeros(0, dtype=np.float32)
            else:
                self._embeddings = np.array(vectors, dtype=np.float32)
                norms = np.linalg.norm(self._embeddings, axis=1)
                norms[norms == 0] = 1e-9
                self._emb_norms = norms

    def bm25_scores(self, tokens: List[str]) -> np.ndarray:
        self._ensure_indexes()
        if not self._docs or self._bm25 is None:
            return np.zeros(len(self._docs))
        return np.array(self._bm25.get_scores(tokens), dtype=np.float32)

    def embedding_scores(self, query_vector: np.ndarray) -> np.ndarray:
        self._ensure_indexes()
        if self._embeddings is None or self._emb_norms is None or not self._docs:
            return np.zeros(len(self._docs))
        q_norm = np.linalg.norm(query_vector)
        if q_norm == 0:
            return np.zeros(len(self._docs))
        q = query_vector / q_norm
        sims = (self._embeddings @ q) / self._emb_norms
        sims = np.clip(sims, -1, 1)
        return (sims + 1) / 2


_STORE = MemoryHybridStore()


def get_store() -> MemoryHybridStore:
    return _STORE


def _tokenize(text: str, language: Optional[str]) -> List[str]:
    return [tok for tok in text.lower().split() if tok]


def _normalize(scores: np.ndarray) -> np.ndarray:
    if not len(scores):
        return scores
    min_v = float(np.min(scores))
    max_v = float(np.max(scores))
    if math.isclose(max_v - min_v, 0.0):
        return np.zeros_like(scores)
    return (scores - min_v) / (max_v - min_v)


def _snippet(text: str, query: str, size: int = 300) -> str:
    if not text:
        return ""
    lowered = text.lower()
    target = query.lower().strip()
    idx = lowered.find(target) if target else -1
    if idx < 0 and target:
        best = process.extractOne(target, [lowered])
        if best and best[1] > 60:
            idx = lowered.find(best[0])
    if idx < 0:
        for token in target.split():
            pos = lowered.find(token)
            if pos >= 0:
                idx = pos
                break
    if idx < 0:
        return text[:size].strip()
    start = max(0, idx - 60)
    end = min(len(text), idx + size)
    return text[start:end].strip()


def hybrid_search(query: str, *, k: int = 8, language: Optional[str] = None) -> List[dict]:
    docs = _STORE.all()
    if not docs:
        return []
    tokens = _tokenize(query, language)
    bm25_raw = _STORE.bm25_scores(tokens)
    emb_vector = np.array(embed_text(query), dtype=np.float32)
    emb_raw = _STORE.embedding_scores(emb_vector)

    bm25_norm = _normalize(bm25_raw)
    emb_norm = _normalize(emb_raw)

    token_set = set(tokens)
    overlap_bonus = np.zeros(len(docs), dtype=np.float32)
    if token_set:
        for i, doc in enumerate(docs):
            doc_tokens = set(_tokenize(doc.text, doc.language))
            overlap_bonus[i] = len(token_set & doc_tokens) / max(1, len(token_set))

    combined = 0.5 * bm25_norm + 0.4 * emb_norm + 0.1 * overlap_bonus
    order = np.argsort(-combined)[:k]
    results: List[dict] = []
    for idx in order:
        doc = docs[int(idx)]
        score = float(np.clip(combined[int(idx)], 0.0, 1.0))
        snippet = _snippet(doc.text, query)
        payload = dict(doc.payload or {})
        results.append(
            {
                "id": doc.doc_id,
                "doc_id": doc.doc_id,
                "text": doc.text,
                "score": score,
                "snippet": snippet,
                "source_ref": doc.source_ref,
                "payload": payload,
            }
        )
    return maybe_rerank(query, results)


__all__ = ["hybrid_search", "get_store", "MemoryHybridStore", "Document"]
