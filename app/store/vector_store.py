from __future__ import annotations

from dataclasses import dataclass
from typing import List, Sequence, Tuple
import psycopg

from app.db import conn_rw


@dataclass
class ScoredNeighbor:
    uuid: str
    score: float


class VectorIndex:
    """
    VectorIndex exposes semantic similarity and text search over embeddings.

    Current backend: pgvector inside Postgres.
    Future: dedicated vector DB / search service.
    """

    def upsert_embedding(self, uuid: str, embedding: Sequence[float]) -> None:
        with conn_rw() as conn:
            # assumes a table like embeddings(uuid text primary key, vec vector)
            conn.execute(
                """
                insert into embeddings (uuid, vec)
                values (%s, %s)
                on conflict (uuid) do update set
                    vec = excluded.vec
                """,
                (
                    uuid,
                    embedding,  # psycopg should map Python sequence -> pgvector type via adapter
                ),
            )

    def similar(self, uuid: str, k: int = 5) -> List[ScoredNeighbor]:
        with conn_rw() as conn:
            # nearest neighbors by vector distance to given uuid
            rows = conn.execute(
                """
                select e2.uuid,
                       1 - (e1.vec <-> e2.vec) as score
                from embeddings e1, embeddings e2
                where e1.uuid = %s
                  and e2.uuid <> e1.uuid
                order by e1.vec <-> e2.vec
                limit %s
                """,
                (uuid, k),
            ).fetchall()

        return [ScoredNeighbor(uuid=r[0], score=float(r[1])) for r in rows]

    def search_by_text(self, query: str, k: int = 5) -> List[ScoredNeighbor]:
        # This assumes somewhere upstream we can embed `query` to a vector.
        # For now we leave placeholder: caller should have produced the query embedding.
        raise NotImplementedError("text->embedding pipeline not wired yet")