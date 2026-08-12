from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, NoReturn



_MVR05A4_HINT = (
    "The legacy RelationIndex SQL does not match the Alembic-owned relations table. "
    "MVR-05A4 (#4578) must replace or remove this producer before it can write; "
    "refusing before SQL so no binding-less child row is attempted."
)


def _raise_pending_binding_key() -> NoReturn:
    raise RuntimeError(_MVR05A4_HINT)


@dataclass
class RelationEdge:
    src_uuid: str
    dst_uuid: str
    relation_type: str
    weight: float
    provenance: Dict[str, Any]
    created_at: datetime


@dataclass
class GraphSlice:
    center: str
    edges: List[RelationEdge]


class RelationIndex:
    """
    RelationIndex (a.k.a. KnowledgeGraphStore) captures associative / provenance links
    between objects. This is the seed for graph-RAG.

    Current backend: a Postgres table like relations(src_uuid text, dst_uuid text,
    relation_type text, weight float8, provenance jsonb, created_at timestamptz).
    Future backend: graph / document store.
    """

    def link(
        self,
        src_uuid: str,
        dst_uuid: str,
        relation_type: str,
        weight: float,
        provenance: Dict[str, Any],
    ) -> None:
        _raise_pending_binding_key()

    def neighborhood(
        self,
        center_uuid: str,
        max_hops: int = 2,
        limit: int = 100,
    ) -> GraphSlice:
        # For now we only return direct neighbors (hop=1).
        # max_hops is reserved for future expansion / graph traversal.
        _raise_pending_binding_key()

    def has_any(self, center_uuid: str) -> bool:
        _raise_pending_binding_key()
