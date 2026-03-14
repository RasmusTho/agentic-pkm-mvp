from __future__ import annotations

import argparse
import os
from dataclasses import dataclass, field
from typing import Sequence

import psycopg
from psycopg.rows import dict_row

from app.agents.chunker.graph import invoke as chunk_invoke
from app.agents.indexer.graph import invoke as index_invoke
from app.agents.reviewer.graph import invoke as review_invoke
from app.agents.set_evaluator.graph import invoke as evaluate_invoke
from app.agents.projector.graph import invoke as project_invoke


def _dsn() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError("DATABASE_URL is required for backfill jobs")
    return url.replace("postgresql+psycopg://", "postgresql://")


def _fetch_ids(sql: str, params: Sequence[object], limit: int) -> list[str]:
    with psycopg.connect(_dsn(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (*params, limit))
            rows = cur.fetchall()
            return [str(next(iter(row.values()))) for row in rows]


@dataclass
class BackfillSummary:
    chunked: list[str] = field(default_factory=list)
    indexed: list[str] = field(default_factory=list)
    reviewed: list[str] = field(default_factory=list)
    evaluated: list[str] = field(default_factory=list)
    projected: list[str] = field(default_factory=list)


class BackfillJob:
    def __init__(self, trace_id: str, limit: int, set_name: str, dry_run: bool) -> None:
        self.trace_id = trace_id
        self.limit = limit
        self.set_name = set_name
        self.dry_run = dry_run
        self.summary = BackfillSummary()

    def run(self) -> BackfillSummary:
        self._process_chunks()
        self._process_embeddings()
        self._process_reviews()
        self._process_evaluations()
        self._process_projection()
        return self.summary

    def _process_chunks(self) -> None:
        sql = (
            "SELECT o.id "
            "FROM objects o "
            "WHERE NOT EXISTS (SELECT 1 FROM chunks c WHERE c.object_id = o.id) "
            "ORDER BY o.id LIMIT %s"
        )
        object_ids = _fetch_ids(sql, tuple(), self.limit)
        for oid in object_ids:
            if self.dry_run:
                print(f"[dry-run] chunk: {oid}")
                continue
            chunk_invoke(oid, trace_id=self.trace_id)
            self.summary.chunked.append(oid)

    def _process_embeddings(self) -> None:
        sql = (
            "SELECT o.id "
            "FROM objects o "
            "WHERE EXISTS (SELECT 1 FROM chunks c WHERE c.object_id = o.id) "
            "AND NOT EXISTS (SELECT 1 FROM embeddings e WHERE e.object_id = o.id) "
            "ORDER BY o.id LIMIT %s"
        )
        object_ids = _fetch_ids(sql, tuple(), self.limit)
        for oid in object_ids:
            if self.dry_run:
                print(f"[dry-run] index: {oid}")
                continue
            index_invoke(oid, trace_id=self.trace_id)
            self.summary.indexed.append(oid)

    def _process_reviews(self) -> None:
        sql = (
            "SELECT o.id "
            "FROM objects o "
            "WHERE NOT EXISTS (SELECT 1 FROM decisions d WHERE d.object_id = o.id AND d.key = 'review') "
            "ORDER BY o.id LIMIT %s"
        )
        object_ids = _fetch_ids(sql, tuple(), self.limit)
        for oid in object_ids:
            if self.dry_run:
                print(f"[dry-run] review: {oid}")
                continue
            review_invoke(oid, trace_id=self.trace_id)
            self.summary.reviewed.append(oid)

    def _process_evaluations(self) -> None:
        sql = (
            "SELECT o.id "
            "FROM objects o "
            "WHERE NOT EXISTS (SELECT 1 FROM decisions d WHERE d.object_id = o.id AND d.key = 'evaluate') "
            "ORDER BY o.id LIMIT %s"
        )
        object_ids = _fetch_ids(sql, tuple(), self.limit)
        for oid in object_ids:
            if self.dry_run:
                print(f"[dry-run] evaluate: {oid}")
                continue
            evaluate_invoke(oid, trace_id=self.trace_id)
            self.summary.evaluated.append(oid)

    def _process_projection(self) -> None:
        sql = (
            "SELECT d.object_id "
            "FROM decisions d "
            "WHERE d.key = 'evaluate' "
            "AND COALESCE((d.value ->> 'promote')::boolean, false) = true "
            "AND NOT EXISTS ("
            "  SELECT 1 FROM membership m "
            "  JOIN sets s ON s.id = m.set_id "
            "  WHERE s.name = %s AND m.object_id = d.object_id"
            ") "
            "ORDER BY d.created_at DESC LIMIT %s"
        )
        object_ids = _fetch_ids(sql, (self.set_name,), self.limit)
        for oid in object_ids:
            if self.dry_run:
                print(f"[dry-run] project: {oid}")
                continue
            project_invoke(oid, trace_id=self.trace_id, set_name=self.set_name)
            self.summary.projected.append(oid)


def run_backfill(*, trace_id: str, limit: int, set_name: str, dry_run: bool) -> BackfillSummary:
    job = BackfillJob(trace_id=trace_id, limit=limit, set_name=set_name, dry_run=dry_run)
    return job.run()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Backfill ingestion hygiene pipeline")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--trace-id", required=True)
    parser.add_argument("--set-name", default="published")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> BackfillSummary:
    parser = _build_parser()
    args = parser.parse_args(argv)
    summary = run_backfill(
        trace_id=args.trace_id,
        limit=args.limit,
        set_name=args.set_name,
        dry_run=args.dry_run,
    )
    if args.dry_run:
        return summary
    if summary.chunked or summary.indexed or summary.reviewed or summary.evaluated or summary.projected:
        print(
            "backfill summary:",
            {
                "chunked": len(summary.chunked),
                "indexed": len(summary.indexed),
                "reviewed": len(summary.reviewed),
                "evaluated": len(summary.evaluated),
                "projected": len(summary.projected),
            },
        )
    else:
        print("backfill summary: no changes")
    return summary


if __name__ == "__main__":
    main()
