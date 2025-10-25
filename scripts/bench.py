from __future__ import annotations

import argparse
import random
import statistics
import time
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import uuid4

import psycopg

from app.search.vector_index import PgVectorIndex
from app.settings import settings


@dataclass
class BenchmarkResult:
    label: str
    p50_ms: float
    p95_ms: float


def _random_vector(dim: int) -> list[float]:
    return [random.random() for _ in range(dim)]


def run_benchmark(count: int, dim: int, k: int) -> BenchmarkResult:
    with psycopg.connect(settings.psycopg_dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE embeddings, objects RESTART IDENTITY CASCADE")
    index = PgVectorIndex(settings.psycopg_dsn)
    object_ids = []
    for _ in range(count):
        object_id = uuid4()
        vector = _random_vector(dim)
        payload = {"title": f"Synthetic {object_id}"}
        index.upsert(
            object_id=object_id,
            kind="synthetic",
            source_ref="bench",
            payload=payload,
            embedding=vector,
            model=settings.embed_model,
        )
        object_ids.append((object_id, vector))

    latencies: list[float] = []
    for _object_id, vector in random.sample(object_ids, min(len(object_ids), 50)):
        start = time.perf_counter()
        index.query(embedding=vector, k=k)
        elapsed = (time.perf_counter() - start) * 1000
        latencies.append(elapsed)

    latencies.sort()
    p50 = statistics.median(latencies) if latencies else 0.0
    p95 = (
        statistics.quantiles(latencies, n=100)[94]
        if len(latencies) >= 100
        else max(latencies, default=0.0)
    )
    return BenchmarkResult(label="pgvector (lists=100, ivfflat)", p50_ms=p50, p95_ms=p95)


def format_table(results: Sequence[BenchmarkResult]) -> str:
    lines = ["Backend | p50 (ms) | p95 (ms)", "--------|----------|---------"]
    for result in results:
        lines.append(f"{result.label} | {result.p50_ms:.2f} | {result.p95_ms:.2f}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark pgvector query latency.")
    parser.add_argument(
        "--count",
        type=int,
        default=2000,
        help="Number of synthetic vectors to insert (default: 2000).",
    )
    parser.add_argument(
        "--dim",
        type=int,
        default=1536,
        help="Vector dimensionality (default: 1536).",
    )
    parser.add_argument(
        "--k",
        type=int,
        default=10,
        help="Number of neighbors to query (default: 10).",
    )
    args = parser.parse_args()

    result = run_benchmark(count=args.count, dim=args.dim, k=args.k)
    print(format_table([result]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
