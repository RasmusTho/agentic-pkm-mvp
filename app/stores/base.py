from __future__ import annotations
import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Protocol, TypedDict, Optional
from uuid import UUID

from app.components.embeddings import EmbeddingIdentity

# Short stable hash length for the identity component of a generation() token
# (ADR-0059 D2, #3403). Long enough to be collision-safe for cache-freshness
# purposes (not a security boundary); short enough to keep the token compact.
_IDENTITY_HASH_LEN = 12


def identity_generation_component(identity: EmbeddingIdentity | None) -> str:
    """Short stable hash of an embedding identity for use in ``generation()`` tokens.

    Empty-string identity serializes to a fixed hash so "no identity" is a
    distinct, stable component rather than an absent one. Every
    ``VectorIndex.generation()`` implementation uses this so a repin
    (identity change without any row rewrite) always moves the token
    (ADR-0059 D2).
    """
    payload = json.dumps(asdict(identity), sort_keys=True) if identity is not None else ""
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:_IDENTITY_HASH_LEN]


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
    def put_if_absent(
        self, object_id: UUID, *, kind: str, source_ref: str, payload: dict
    ) -> bool: ...
    def count_objects(self, kind: str | None = None) -> int: ...
    def list_objects(
        self, kind: str | None = None, *, limit: int | None = 100
    ) -> Iterable[dict]: ...
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
        reconcilable_fallback: bool = False,
    ) -> None: ...

    def search(self, vector: list[float], *, k: int = 5, identity: EmbeddingIdentity | None = None) -> list: ...

    def get_identity(self) -> EmbeddingIdentity | None: ...

    def purge_vectors(self, object_id: UUID, *, view: str) -> int: ...

    def count_vectors(self) -> int: ...

    def all_rows(self) -> Iterable[dict]: ...

    def generation(self) -> str:
        """Cheap, opaque store-generation token (G1res-1, #2981; identity-aware
        per ADR-0059 D2, #3403).

        Changes whenever a durable upsert or purge commits, AND whenever the
        stored embedding identity changes (e.g. an ADR-0052 repin) even
        without any row rewrite (see ``identity_generation_component``).
        Equality of two tokens means the durable index has not changed —
        neither its rows nor its embedding identity — between the two reads.
        Serving-path caches compare this against the token captured at their
        last rebuild to detect staleness without a full row scan. The token
        is opaque to consumers: never parse its structure, only compare it.
        """
        ...


@dataclass(frozen=True)
class RelationMembership:
    object_id: UUID
    relation_type: str
    value: str
    payload: dict[str, Any] = field(default_factory=dict)


class RelationIndex(Protocol):
    def link(self, src: UUID, dst: UUID, *, rel: str, payload: dict | None = None) -> None: ...
    def neighbors(self, src: UUID, *, rel: str, k: int = 20) -> list[UUID]: ...
    def has_any(self, src: UUID) -> bool: ...
    def add_membership(self, src: UUID, *, rel: str, value: str, payload: dict | None = None) -> None: ...
    def memberships(self, src: UUID, *, rel: str | None = None) -> list[RelationMembership]: ...
