"""Append-to-JSONL benchmark helper.

Runs one benchmark scenario via run_benchmark.run() and appends the result
as a single JSON line to the specified JSONL output file.

This is the accumulator companion to run_benchmark.py:
  - run_benchmark.py  → writes one pretty-printed JSON file per invocation
  - record_sample.py  → appends one compact JSON line per invocation to a JSONL accumulator

Usage:
    python ops/benchmarks/record_sample.py \\
      --storage-profile memory \\
      --runtime-placement local \\
      --model-profile mock \\
      --seed-dir docs/examples/vault_test_seed \\
      --output ops/benchmarks/baselines/samples.jsonl
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from ops.benchmarks.run_benchmark import main as _run_main, run  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Append one PKM benchmark run to a JSONL accumulator file. "
            "Measurement only — no thresholds enforced."
        ),
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
        required=True,
        help="JSONL file to append the run result to (created if absent)",
    )
    args = parser.parse_args()

    result = run(args)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(result, separators=(",", ":")) + "\n")

    print(f"Appended run {result['run_id']} to {out_path}")


if __name__ == "__main__":
    main()
