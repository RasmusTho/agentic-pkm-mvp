from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List
import math


@dataclass
class ScoredNeighbor:
    uuid: str
    score: float


class VectorIndex:
    """
    Semantic similarity / embedding index.
    SoT v4.4 contract.

    Current state:
    - Minimal in-memory fallback so tests and agents can rely on a stable API.
    - Real backend will normally be pgvector in Postgres.
    - Agents MUST talk to this interface, not directly to pgvector.

    Responsibilities:
    - Store (uuid -> embedding)
    - Return nearest neighbors by cosine similarity
    - Allow text search via search_by_text (placeholder for now)
    """

    # naive in-memory embeddings store for now
    _embeddings: Dict[str, List[float]] = {}

    @classmethod
    def upsert_embedding(cls, uuid: str, embedding: List[float]) -> None:
        """
        Register or update the embedding for an object uuid.
        In production this will persist to pgvector.
        """
        cls._embeddings[uuid] = embedding

    @classmethod
    def _cosine(cls, a: List[float], b: List[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        if na == 0.0 or nb == 0.0:
            return 0.0
        return dot / (na * nb)

    @classmethod
    def similar(cls, uuid: str, k: int = 5) -> List[ScoredNeighbor]:
        """
        Return up to k most similar neighbors to the given uuid
        (excluding itself), scored by cosine similarity.
        """
        if uuid not in cls._embeddings:
            return []
        base = cls._embeddings[uuid]
        scored: List[ScoredNeighbor] = []
        for other_id, emb in cls._embeddings.items():
            if other_id == uuid:
                continue
            score = cls._cosine(base, emb)
            scored.append(ScoredNeighbor(uuid=other_id, score=score))
        scored.sort(key=lambda x: x.score, reverse=True)
        return scored[:k]

    @classmethod
    def search_by_text(cls, query: str, k: int = 5) -> List[ScoredNeighbor]:
        """
        Placeholder text search -> embedding -> nearest.
        In production this will embed `query` using the same model and do ANN lookup.
        For now, returns empty list so callers can handle 'no result'.
        """
        # We don't have text->embedding at this layer yet.
        # We keep the method to freeze the contract.
        return []
