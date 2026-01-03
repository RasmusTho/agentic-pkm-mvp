from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator, List, Optional

import numpy as np
from rank_bm25 import BM25Okapi
try:
    from rapidfuzz import process
except ImportError:
    process = None

from app.components.retrieval import embed_docs, embed_query
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
            texts = [doc.text for doc in self._docs]
            vectors, _ = embed_docs(texts)
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
        if query_vector.ndim != 1:
            raise ValueError("query embedding must be 1D")
        expected_dim = self._embeddings.shape[1] if self._embeddings.ndim == 2 else 0
        if expected_dim and query_vector.shape[0] != expected_dim:
            raise ValueError(
                f"hybrid query embedding dim mismatch: expected {expected_dim}, got {query_vector.shape[0]}"
            )
        q_norm = np.linalg.norm(query_vector)
        if q_norm == 0:
            return np.zeros(len(self._docs))
        q = query_vector / q_norm
        sims = (self._embeddings @ q) / self._emb_norms
        sims = np.clip(sims, -1, 1)
        return (sims + 1) / 2


_STORE = MemoryHybridStore()


def _resolve_domain_scope() -> str | None:
    raw = os.getenv("ASK_DOMAIN_SCOPE", "").strip()
    return raw or None


def _extract_domain(doc: Document) -> str | None:
    payload = doc.payload or {}
    raw = payload.get("domain")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    if doc.source_ref:
        path = Path(str(doc.source_ref))
        parts = [part for part in path.parts if part not in (path.anchor, "")]
        if parts:
            return parts[0]
    return None


def _bridge_domains(doc: Document) -> set[str]:
    payload = doc.payload or {}
    raw = payload.get("bridge_domains")
    if isinstance(raw, str):
        return {item.strip() for item in raw.split(",") if item.strip()}
    if isinstance(raw, (list, tuple, set)):
        return {str(item).strip() for item in raw if str(item).strip()}
    return set()


def _doc_in_scope(doc: Document, scope: str) -> bool:
    domain = _extract_domain(doc)
    if not domain:
        return False
    if domain == scope:
        return True
    return scope in _bridge_domains(doc)


def embed_text(text: str, language: Optional[str] = None) -> list[float]:
    """Backwards-compatible embedding helper for tests that patch this symbol."""
    vector, _ = embed_query(text)
    return vector


def embed_batches(texts: Iterable[str], batch_size: int = 32) -> Iterator[list[list[float]]]:
    """Backwards-compatible batch embedding helper for tests that patch this symbol."""
    del batch_size
    vectors, _ = embed_docs(texts)
    yield vectors


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
    if idx < 0 and target and process is not None:
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


def hybrid_search(query: str, *, k: int = 8, language: Optional[str] = None, query_vector: list[float] | None = None) -> List[dict]:
    docs = _STORE.all()
    if not docs:
        return []

    scope = _resolve_domain_scope()
    allowed_idx: set[int] | None = None
    if scope:
        allowed_idx = {idx for idx, doc in enumerate(docs) if _doc_in_scope(doc, scope)}
        if not allowed_idx:
            return []

    tokens = _tokenize(query, language)
    bm25_raw = _STORE.bm25_scores(tokens)
    emb_vector_raw = query_vector if query_vector is not None else embed_text(query)
    emb_vector = np.array(emb_vector_raw, dtype=np.float32)
    if emb_vector.ndim != 1 or not emb_vector.shape[0]:
        raise ValueError("embedding client returned invalid vector shape")
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
    order = np.argsort(-combined)
    if allowed_idx is not None:
        ordered = [int(idx) for idx in order if int(idx) in allowed_idx]
    else:
        ordered = [int(idx) for idx in order]
    ordered = ordered[:k]

    results: List[dict] = []
    for idx in ordered:
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
