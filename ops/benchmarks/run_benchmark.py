"""PKM Runtime Benchmark Runner.

Minimal CLI entry point that measures the canonical ingest -> index -> ASK
chain on seed data and emits structured JSON per the benchmark protocol
(docs/plans/BENCHMARK_PROTOCOL.md).

Measurement only — no thresholds enforced, no CI gates.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List
from uuid import uuid4

# ---------------------------------------------------------------------------
# Metric names (must match docs/plans/BENCHMARK_PROTOCOL.md)
# ---------------------------------------------------------------------------

METRIC_INGEST_FULL = "ingest_full_ms"
METRIC_INDEX_WRITE = "index_write_ms"
METRIC_ASK_QUERY = "ask_query_ms"

ALL_PHASE1_METRICS = {METRIC_INGEST_FULL, METRIC_INDEX_WRITE, METRIC_ASK_QUERY}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_tags(scenario: Dict[str, str], **extra: str) -> Dict[str, str]:
    return {**scenario, **extra}


def _ms_since(start: float) -> float:
    return (time.perf_counter() - start) * 1000.0


# ---------------------------------------------------------------------------
# Individual benchmark stages
# ---------------------------------------------------------------------------


def _bench_ingest(
    seed_files: List[Path],
    scenario: Dict[str, str],
    tmp_dir: Path,
) -> tuple[List[Dict[str, Any]], List[str]]:
    """Ingest seed files and measure per-file + total timing."""
    metrics: List[Dict[str, Any]] = []
    warnings: List[str] = []

    try:
        from app.ingest.vault_root import ingest_vault_root  # noqa: E402
        from app.stores import reset_store_backends  # noqa: E402
    except ImportError as exc:
        warnings.append(f"{METRIC_INGEST_FULL} skipped: {exc}")
        return metrics, warnings

    try:
        reset_store_backends()
    except Exception:
        pass

    vault_dir = tmp_dir / "vault"
    vault_dir.mkdir(exist_ok=True)
    for seed_file in seed_files:
        (vault_dir / seed_file.name).write_text(
            seed_file.read_text(encoding="utf-8"), encoding="utf-8"
        )

    start = time.perf_counter()
    try:
        count = ingest_vault_root(vault_dir, limit=len(seed_files))
    except Exception as exc:
        warnings.append(f"{METRIC_INGEST_FULL} failed: {exc}")
        return metrics, warnings
    elapsed = _ms_since(start)

    metrics.append(
        {
            "name": METRIC_INGEST_FULL,
            "value_ms": round(elapsed, 3),
            "tags": _make_tags(scenario, seed_count=str(count)),
            "timestamp": _now_iso(),
        }
    )
    return metrics, warnings


def _bench_index_write(
    scenario: Dict[str, str],
) -> tuple[List[Dict[str, Any]], List[str]]:
    """Measure embedding + vector index upsert for a synthetic document."""
    metrics: List[Dict[str, Any]] = []
    warnings: List[str] = []

    try:
        from app.components.llm.fabric import LLMTaskIntent, get_embeddings_client  # noqa: E402
        from app.stores.memory import MemoryVectorIndex  # noqa: E402
    except ImportError as exc:
        warnings.append(f"{METRIC_INDEX_WRITE} skipped: {exc}")
        return metrics, warnings

    index = MemoryVectorIndex()
    samples = 8
    timings: List[float] = []
    for i in range(samples):
        payload_text = f"Benchmark index write sample {i}. Contains varied terms for embedding."
        start = time.perf_counter()
        try:
            client = get_embeddings_client(
                LLMTaskIntent(task_kind="embed", strict_identity_required=True)
            )
            vec = client.embed_text(payload_text)
            identity = client.identity
            index.upsert(
                uuid4(),
                kind="benchmark",
                source_ref=f"benchmark/{i}",
                payload={"title": f"bench-{i}"},
                embedding=list(vec),
                model=identity.model,
                identity=identity,
            )
        except Exception as exc:
            warnings.append(f"{METRIC_INDEX_WRITE} failed on sample {i}: {exc}")
            return metrics, warnings
        timings.append(_ms_since(start))

    if timings:
        avg = sum(timings) / len(timings)
        metrics.append(
            {
                "name": METRIC_INDEX_WRITE,
                "value_ms": round(avg, 3),
                "tags": _make_tags(scenario, samples=str(samples)),
                "timestamp": _now_iso(),
            }
        )
    return metrics, warnings


def _bench_ask_query(
    scenario: Dict[str, str],
) -> tuple[List[Dict[str, Any]], List[str]]:
    """Measure hybrid search latency over the current in-memory store."""
    metrics: List[Dict[str, Any]] = []
    warnings: List[str] = []

    try:
        from app.retrieval.hybrid import hybrid_search  # noqa: E402
    except ImportError as exc:
        warnings.append(f"{METRIC_ASK_QUERY} skipped: {exc}")
        return metrics, warnings

    queries = [
        "knowledge strategy",
        "evergreen note promotion",
        "review cadence evidence",
        "summary request",
    ]
    timings: List[float] = []
    for q in queries:
        start = time.perf_counter()
        try:
            hybrid_search(q, k=5)
        except Exception as exc:
            warnings.append(f"{METRIC_ASK_QUERY} failed for query '{q}': {exc}")
            continue
        timings.append(_ms_since(start))

    if timings:
        avg = sum(timings) / len(timings)
        metrics.append(
            {
                "name": METRIC_ASK_QUERY,
                "value_ms": round(avg, 3),
                "tags": _make_tags(scenario, queries=str(len(queries))),
                "timestamp": _now_iso(),
            }
        )
    else:
        warnings.append(f"{METRIC_ASK_QUERY} skipped: no successful queries")
    return metrics, warnings


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run(args: argparse.Namespace) -> Dict[str, Any]:
    """Execute the benchmark and return the result dict."""
    seed_dir = Path(args.seed_dir)
    if not seed_dir.exists():
        print(f"Error: seed directory does not exist: {seed_dir}", file=sys.stderr)
        sys.exit(1)

    seed_files = sorted(seed_dir.glob("*.md"))

    scenario = {
        "storage_profile": args.storage_profile,
        "runtime_placement": args.runtime_placement,
        "model_profile": args.model_profile,
    }

    # Set environment for memory/mock profiles
    if args.storage_profile == "memory":
        os.environ.setdefault("STORE_BACKEND", "memory")
    if args.model_profile == "mock":
        os.environ.setdefault("LLM_PROVIDER", "mock")
        os.environ.setdefault(
            "LLM_MOCK_RESPONSE",
            '{"type":"note","trust":"own","tags":["topic/test"],"confidence":0.95}',
        )

    all_metrics: List[Dict[str, Any]] = []
    all_warnings: List[str] = []

    import tempfile

    with tempfile.TemporaryDirectory(prefix="pkm_bench_") as tmp_str:
        tmp_dir = Path(tmp_str)

        # Set a temp ingest status path to avoid polluting real state
        os.environ["INGEST_STATUS_PATH"] = str(tmp_dir / "ingest_status.json")

        if not seed_files:
            all_warnings.append("No .md files found in seed directory")
        else:
            # Stage 1: Ingest
            m, w = _bench_ingest(seed_files, scenario, tmp_dir)
            all_metrics.extend(m)
            all_warnings.extend(w)

            # Stage 2: Index write
            m, w = _bench_index_write(scenario)
            all_metrics.extend(m)
            all_warnings.extend(w)

            # Stage 3: ASK query
            m, w = _bench_ask_query(scenario)
            all_metrics.extend(m)
            all_warnings.extend(w)

    result = {
        "run_id": str(uuid4()),
        "timestamp": _now_iso(),
        "scenario": scenario,
        "metrics": all_metrics,
        "warnings": all_warnings,
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="PKM Runtime Benchmark Runner — measurement only, no thresholds enforced.",
    )
    parser.add_argument(
        "--storage-profile",
        default="memory",
        choices=["memory", "pg"],
        help="Store backend profile (default: memory)",
    )
    parser.add_argument(
        "--runtime-placement",
        default="local",
        choices=["local", "docker", "colima"],
        help="Runtime placement (default: local)",
    )
    parser.add_argument(
        "--model-profile",
        default="mock",
        choices=["mock", "local", "cloud"],
        help="LLM/embedding provider profile (default: mock)",
    )
    parser.add_argument(
        "--seed-dir",
        default="docs/examples/vault_test_seed",
        help="Path to seed vault directory (default: docs/examples/vault_test_seed)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Write JSON output to file instead of stdout",
    )
    args = parser.parse_args()
    result = run(args)

    output_str = json.dumps(result, indent=2)
    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output_str, encoding="utf-8")
    else:
        print(output_str)


if __name__ == "__main__":
    main()
