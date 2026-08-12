"""Non-writing compatibility contract types for relation consumers."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class RelationEdge:
    src_uuid: str
    dst_uuid: str
    relation_type: str
    weight: float
    provenance: dict[str, Any]
    created_at: datetime


@dataclass
class GraphSlice:
    center: str
    edges: list[RelationEdge]


class RelationIndex:
    """Retained non-writing legacy import contract; durable access uses app.stores."""

    def link(self, src_uuid: str, dst_uuid: str, relation_type: str, weight: float, provenance: dict[str, Any]) -> None:
        raise NotImplementedError

    def neighborhood(self, center_uuid: str, max_hops: int = 2, limit: int = 100) -> GraphSlice:
        raise NotImplementedError

    def has_any(self, center_uuid: str) -> bool:
        raise NotImplementedError
