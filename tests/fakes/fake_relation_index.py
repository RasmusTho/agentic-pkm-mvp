from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Any, List
from app.store.relation_index import RelationEdge, GraphSlice


class FakeRelationIndex:
    def __init__(self) -> None:
        self._edges: list[RelationEdge] = []

    def link(
        self,
        src_uuid: str,
        dst_uuid: str,
        relation_type: str,
        weight: float,
        provenance: Dict[str, Any],
    ) -> None:
        self._edges.append(
            RelationEdge(
                src_uuid=src_uuid,
                dst_uuid=dst_uuid,
                relation_type=relation_type,
                weight=weight,
                provenance=provenance,
                created_at=datetime.now(timezone.utc),
            )
        )

    def neighborhood(
        self,
        center_uuid: str,
        max_hops: int = 2,
        limit: int = 100,
    ) -> GraphSlice:
        filtered = [
            e
            for e in self._edges
            if e.src_uuid == center_uuid or e.dst_uuid == center_uuid
        ]
        filtered.sort(key=lambda e: e.created_at, reverse=True)
        return GraphSlice(center=center_uuid, edges=filtered[:limit])
