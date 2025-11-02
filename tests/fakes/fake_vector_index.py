from __future__ import annotations

from typing import Sequence, List
from app.store.vector_index import ScoredNeighbor


class FakeVectorIndex:
    def __init__(self) -> None:
        self._embeddings: dict[str, Sequence[float]] = {}

    def upsert_embedding(self, uuid: str, embedding: Sequence[float]) -> None:
        self._embeddings[uuid] = list(embedding)

    def similar(self, uuid: str, k: int = 5) -> List[ScoredNeighbor]:
        result: List[ScoredNeighbor] = []
        for other_uuid in self._embeddings.keys():
            if other_uuid == uuid:
                continue
            result.append(ScoredNeighbor(uuid=other_uuid, score=1.0))
        return result[:k]

    def search_by_text(self, query: str, k: int = 5) -> List[ScoredNeighbor]:
        return []
