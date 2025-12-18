from __future__ import annotations
from typing import Iterable, Protocol, TypedDict, Optional
from uuid import UUID

from app.components.embeddings import EmbeddingIdentity


class Decision(TypedDict):
    id: str
    object_id: str
    agent: str
    kind: str
    key: str
    value: dict


class DecisionsStore(Protocol):
    def put(self, *, object_id: str, agent: str, kind: str, key: str, value: dict) -> dict: ...
    def latest(self, *, object_id: str, key: str) -> Optional[Decision]: ...


class ObjectsStore(Protocol):
    def upsert(self, *, kind: str, payload: dict, source_ref: str | None = None, path: str | None = None) -> dict: ...


class ObjectStore(Protocol):
    def get(self, object_id: UUID) -> dict | None: ...
    def put(self, object_id: UUID, *, kind: str, source_ref: str, payload: dict) -> None: ...
    def list_by_kind(self, kind: str, *, limit: int = 100) -> Iterable[dict]: ...


class VectorIndex(Protocol):
    def upsert(
        self,
        object_id: UUID,
        *,
        kind: str,
        source_ref: str,
        payload: dict,
        embedding: list[float],
        model: str,
        identity: EmbeddingIdentity | None = None,
    ) -> None: ...

    def search(self, vector: list[float], *, k: int = 5, identity: EmbeddingIdentity | None = None) -> list: ...

    def get_identity(self) -> EmbeddingIdentity | None: ...


class RelationIndex(Protocol):
    def link(self, src: UUID, dst: UUID, *, rel: str, payload: dict | None = None) -> None: ...
    def neighbors(self, src: UUID, *, rel: str, k: int = 20) -> list[UUID]: ...
    def has_any(self, src: UUID) -> bool: ...
