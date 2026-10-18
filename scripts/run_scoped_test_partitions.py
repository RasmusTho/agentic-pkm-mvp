#!/usr/bin/env python3
"""Run a finite scoped pytest partition inventory and fail closed."""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.select_pr_tests import PR_MARKER_EXPRESSION

MAX_PARTITIONS = 4
MAX_SHARD_TIMEOUT_SECONDS = 3300


def _string_list(value: object, *, name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{name} must be a non-empty JSON list")
    if not all(isinstance(item, str) and item for item in value):
        raise ValueError(f"{name} entries must be non-empty strings")
    return tuple(value)


def validate_inventory(
    partitions_value: object, expected_value: object
) -> tuple[tuple[str, ...], ...]:
    expected = _string_list(expected_value, name="expected targets")
    if len(set(expected)) != len(expected):
        raise ValueError("expected targets contain duplicates")
    if not isinstance(partitions_value, list) or not partitions_value:
        raise ValueError("partition inventory must be a non-empty JSON list")
    if len(partitions_value) > MAX_PARTITIONS:
        raise ValueError(f"partition inventory exceeds {MAX_PARTITIONS} shards")
    partitions = tuple(
        _string_list(partition, name=f"partition {index}")
        for index, partition in enumerate(partitions_value)
    )
    actual = tuple(target for partition in partitions for target in partition)
    if Counter(actual) != Counter(expected):
        raise ValueError("partition union does not match expected targets exactly once")
    return partitions


def _run_partition(
    index: int, targets: Sequence[str], *, log_dir: Path, timeout_seconds: int
) -> tuple[int, int, Path, bool]:
    log_path = log_dir / f"partition-{index}.log"
    command = [
        "pytest",
        "-q",
        "-m",
        PR_MARKER_EXPRESSION,
        *targets,
        "-vv",
        "--tb=short",
        "--durations=20",
    ]
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            command,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
            env=os.environ.copy(),
        )
        try:
            return index, process.wait(timeout=timeout_seconds), log_path, False
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            log.write(f"\nPARTITION TIMED OUT after {timeout_seconds}s\n")
            log.flush()
            return index, 124, log_path, True


def run_partitions(
    partitions: tuple[tuple[str, ...], ...],
    *,
    log_dir: Path,
    aggregate_log: Path,
    jobs: int,
    timeout_seconds: int,
) -> int:
    log_dir.mkdir(parents=True, exist_ok=True)
    results: dict[int, tuple[int, Path, bool]] = {}
    with ThreadPoolExecutor(max_workers=min(jobs, len(partitions))) as executor:
        futures = {
            executor.submit(
                _run_partition, index, targets, log_dir=log_dir, timeout_seconds=timeout_seconds
            ): index
            for index, targets in enumerate(partitions)
        }
        for future in as_completed(futures):
            index, returncode, log_path, timed_out = future.result()
            results[index] = (returncode, log_path, timed_out)
            print(
                f"PARTITION FINISHED ({returncode}): {index} targets={len(partitions[index])}",
                flush=True,
            )
    if len(results) != len(partitions):
        print(
            f"Partition runner incomplete: expected={len(partitions)} actual={len(results)}",
            file=sys.stderr,
        )
        return 1
    failed = False
    with aggregate_log.open("w", encoding="utf-8") as aggregate:
        for index in range(len(partitions)):
            returncode, log_path, timed_out = results[index]
            log = log_path.read_text(encoding="utf-8")
            aggregate.write(f"===== scoped partition {index} =====\n{log}")
            if log and not log.endswith("\n"):
                aggregate.write("\n")
            if returncode != 0 or timed_out:
                failed = True
                print(f"PARTITION FAILED ({returncode}): {index}", file=sys.stderr)
                print(log, file=sys.stderr, end="" if log.endswith("\n") else "\n")
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--partitions-json", required=True)
    parser.add_argument("--expected-targets-json", required=True)
    parser.add_argument("--log-dir", required=True)
    parser.add_argument("--aggregate-log", required=True)
    parser.add_argument("--jobs", type=int, default=MAX_PARTITIONS)
    parser.add_argument("--shard-timeout-seconds", type=int, default=MAX_SHARD_TIMEOUT_SECONDS)
    args = parser.parse_args()
    if not 1 <= args.jobs <= MAX_PARTITIONS:
        parser.error(f"--jobs must be between 1 and {MAX_PARTITIONS}")
    if not 1 <= args.shard_timeout_seconds <= MAX_SHARD_TIMEOUT_SECONDS:
        parser.error(f"--shard-timeout-seconds must be between 1 and {MAX_SHARD_TIMEOUT_SECONDS}")
    try:
        partitions = validate_inventory(
            json.loads(args.partitions_json), json.loads(args.expected_targets_json)
        )
    except (json.JSONDecodeError, ValueError) as exc:
        parser.error(str(exc))
    return run_partitions(
        partitions,
        log_dir=Path(args.log_dir),
        aggregate_log=Path(args.aggregate_log),
        jobs=args.jobs,
        timeout_seconds=args.shard_timeout_seconds,
    )


if __name__ == "__main__":
    raise SystemExit(main())
