from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from app.ingest.chunker import ChunkConfig
from app.settings import settings


@dataclass(slots=True)
class PendingChunk:
    id: str
    text: str
    size: int
    doc_path: str
    trust: str = "provisional"


@dataclass(slots=True)
class PendingDocument:
    doc_path: str
    trust: str
    chunk_count: int
    first_seen: datetime


def _db_path() -> Path:
    return Path(settings.staging_db_path).expanduser()


def _connect() -> duckdb.DuckDBPyConnection:
    db_path = _db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS chunks_pending (
            chunk_id TEXT PRIMARY KEY,
            doc_path TEXT,
            trust TEXT,
            text TEXT,
            size INTEGER,
            config_size INTEGER,
            config_overlap INTEGER,
            created TIMESTAMP
        )
        """
    )
    return con


def stage_chunks(chunks: Iterable[PendingChunk], config: ChunkConfig | None = None) -> None:
    cfg = config or ChunkConfig()
    size, overlap = cfg.resolve()
    payload: list[tuple[str, str, str, str, int, int, int, datetime]] = []
    now = datetime.now(tz=UTC)
    for chunk in chunks:
        payload.append(
            (
                chunk.id,
                chunk.doc_path,
                chunk.trust,
                chunk.text,
                chunk.size,
                size,
                overlap,
                now,
            )
        )

    if not payload:
        return

    with _connect() as con:
        con.executemany(
            """
            INSERT OR REPLACE INTO chunks_pending (
                chunk_id,
                doc_path,
                trust,
                text,
                size,
                config_size,
                config_overlap,
                created
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            payload,
        )


def list_pending_documents(limit: int = 50) -> list[PendingDocument]:
    query = """
        SELECT doc_path, trust, COUNT(*) AS chunk_count, MIN(created) AS first_seen
        FROM chunks_pending
        WHERE trust = 'provisional'
        GROUP BY doc_path, trust
        ORDER BY first_seen
        LIMIT ?
        """
    with _connect() as con:
        rows = con.execute(query, [limit]).fetchall()
    return [PendingDocument(*row) for row in rows]


def promote_document(doc_path: str, new_trust: str = "reviewed") -> int:
    with _connect() as con:
        count = con.execute(
            "SELECT COUNT(*) FROM chunks_pending WHERE doc_path = ?",
            [doc_path],
        ).fetchone()[0]
        if not count:
            return 0
        con.execute("UPDATE chunks_pending SET trust = ? WHERE doc_path = ?", [new_trust, doc_path])
        return int(count)
