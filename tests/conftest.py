from __future__ import annotations

import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

import app.search as search_module  # noqa: E402
import app.search.service as search_service_module  # noqa: E402
from app.search import get_vector_index as original_get_vector_index  # noqa: E402
from app.search.vector_index import VectorResult  # noqa: E402


@dataclass
class StoredObject:
    kind: str | None
    source_ref: str | None
    payload: dict[str, Any]
    embedding: list[float]
    model: str


class StubVectorIndex:
    def __init__(self) -> None:
        self.store: dict[UUID, StoredObject] = {}

    def upsert(
        self,
        *,
        object_id: UUID,
        kind: str | None,
        source_ref: str | None,
        payload: dict[str, Any],
        embedding: Sequence[float],
        model: str,
    ) -> None:
        self.store[object_id] = StoredObject(
            kind=kind,
            source_ref=source_ref,
            payload=dict(payload),
            embedding=list(embedding),
            model=model,
        )

    def query(
        self,
        *,
        embedding: Sequence[float],
        k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[VectorResult]:
        if not self.store:
            return []
        query_vec = list(embedding)
        results: list[VectorResult] = []
        for object_id, stored in self.store.items():
            if filters and not all(stored.payload.get(k) == v for k, v in filters.items()):
                continue
            score = sum(a * b for a, b in zip(query_vec, stored.embedding, strict=False))
            results.append(
                VectorResult(object_id=object_id, score=score, payload=stored.payload)
            )
        results.sort(key=lambda item: item.score, reverse=True)
        return results[:k]


@pytest.fixture
def stub_index(monkeypatch) -> StubVectorIndex:
    index = StubVectorIndex()

    def _get_index() -> StubVectorIndex:
        return index

    monkeypatch.setattr(search_module, "get_vector_index", _get_index)
    monkeypatch.setattr(search_service_module, "get_vector_index", _get_index)
    if hasattr(original_get_vector_index, "cache_clear"):
        original_get_vector_index.cache_clear()
    return index
