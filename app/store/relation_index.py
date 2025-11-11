from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Dict, Any

from app.db import conn_rw
from psycopg.types.json import Json


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
        with conn_rw() as conn:
            conn.execute(
                """
                insert into relations (
                    src_uuid, dst_uuid, relation_type,
                    weight, provenance, created_at
                )
                values (%s, %s, %s, %s, %s, %s)
                """,
                (
                    src_uuid,
                    dst_uuid,
                    relation_type,
                    weight,
                    Json(provenance),
                    datetime.now(timezone.utc),
                ),
            )

    def neighborhood(
        self,
        center_uuid: str,
        max_hops: int = 2,
        limit: int = 100,
    ) -> GraphSlice:
        # For now we only return direct neighbors (hop=1).
        # max_hops is reserved for future expansion / graph traversal.
        with conn_rw() as conn:
            rows = conn.execute(
                """
                select src_uuid,
                       dst_uuid,
                       relation_type,
                       weight,
                       provenance,
                       created_at
                from relations
                where src_uuid = %s
                   or dst_uuid = %s
                order by created_at desc
                limit %s
                """,
                (center_uuid, center_uuid, limit),
            ).fetchall()

        edges = [
            RelationEdge(
                src_uuid=r[0],
                dst_uuid=r[1],
                relation_type=r[2],
                weight=float(r[3]),
                provenance=r[4],
                created_at=r[5],
            )
            for r in rows
        ]

        return GraphSlice(center=center_uuid, edges=edges)

    def has_any(self, center_uuid: str) -> bool:
        with conn_rw() as conn:
            row = conn.execute(
                """
                select 1
                from relations
                where src_uuid = %s or dst_uuid = %s
                limit 1
                """,
                (center_uuid, center_uuid),
            ).fetchone()
        return bool(row)
