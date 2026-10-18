#!/usr/bin/env python3
"""Run a finite scoped pytest partition inventory and fail closed."""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.select_pr_tests import PR_MARKER_EXPRESSION

MAX_PARTITIONS = 4
MAX_SHARD_TIMEOUT_SECONDS = 3300
PROCESS_GROUP_GRACE_SECONDS = 1.0


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


def _terminate_process_group(process_group: int) -> None:
    """Terminate every descendant in one shard's private process group."""
    try:
        os.killpg(process_group, signal.SIGTERM)
    except (PermissionError, ProcessLookupError):
        return
    time.sleep(PROCESS_GROUP_GRACE_SECONDS)
    try:
        os.killpg(process_group, signal.SIGKILL)
    except (PermissionError, ProcessLookupError):
        pass


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
            start_new_session=True,
        )
        try:
            returncode = process.wait(timeout=timeout_seconds)
            _terminate_process_group(process.pid)
            return index, returncode, log_path, False
        except subprocess.TimeoutExpired:
            _terminate_process_group(process.pid)
            process.wait()
            log.write(f"\nPARTITION TIMED OUT after {timeout_seconds}s\n")
            log.flush()
            return index, 124, log_path, True


def _split_serial_boundary(
    targets: tuple[str, ...], serial_boundary: tuple[str, ...]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    roots = tuple(
        target for target in targets if "::" not in target and not target.endswith(".py")
    )
    if not serial_boundary or not all(
        any(path.startswith(f"{root}/") for root in roots) for path in serial_boundary
    ):
        raise ValueError(
            "serial boundary must be contained by a directory target in the last partition"
        )
    parallel: list[str] = []
    for target in targets:
        if target in serial_boundary:
            continue
        if any(target.startswith(f"{root}/") for root in roots):
            continue
        parallel.append(target)
    parallel.extend(f"--ignore={path}" for path in serial_boundary)
    return tuple(parallel), serial_boundary


def run_partitions(
    partitions: tuple[tuple[str, ...], ...],
    *,
    log_dir: Path,
    aggregate_log: Path,
    jobs: int,
    timeout_seconds: int,
    serial_last: bool,
    serial_boundary: tuple[str, ...],
) -> int:
    log_dir.mkdir(parents=True, exist_ok=True)
    results: dict[int, tuple[int, Path, bool]] = {}
    if serial_last and serial_boundary:
        raise ValueError("--serial-last and --serial-boundary-json are mutually exclusive")
    parallel_count = len(partitions) - 1 if serial_last else len(partitions)
    parallel_partitions = list(partitions[:parallel_count])
    boundary_targets: tuple[str, ...] = ()
    if serial_boundary:
        parallel_targets, boundary_targets = _split_serial_boundary(
            partitions[-1], serial_boundary
        )
        parallel_partitions[-1] = parallel_targets
    if parallel_count:
        with ThreadPoolExecutor(max_workers=min(jobs, parallel_count)) as executor:
            futures = {
                executor.submit(
                    _run_partition,
                    index,
                    targets,
                    log_dir=log_dir,
                    timeout_seconds=timeout_seconds,
                ): index
                for index, targets in enumerate(parallel_partitions)
            }
            for future in as_completed(futures):
                index, returncode, log_path, timed_out = future.result()
                results[index] = (returncode, log_path, timed_out)
                print(
                    f"PARTITION FINISHED ({returncode}): {index} "
                    f"targets={len(partitions[index])}",
                    flush=True,
                )
    if serial_last:
        index = len(partitions) - 1
        result_index, returncode, log_path, timed_out = _run_partition(
            index,
            partitions[index],
            log_dir=log_dir,
            timeout_seconds=timeout_seconds,
        )
        results[result_index] = (returncode, log_path, timed_out)
        print(
            f"PARTITION FINISHED ({returncode}): {index} "
            f"targets={len(partitions[index])}",
            flush=True,
        )
    boundary_index: int | None = None
    if boundary_targets:
        boundary_index = len(partitions)
        result_index, returncode, log_path, timed_out = _run_partition(
            boundary_index,
            boundary_targets,
            log_dir=log_dir,
            timeout_seconds=timeout_seconds,
        )
        results[result_index] = (returncode, log_path, timed_out)
        print(
            f"SERIAL BOUNDARY FINISHED ({returncode}): "
            f"targets={len(boundary_targets)}",
            flush=True,
        )
    expected_results = len(partitions) + (1 if boundary_index is not None else 0)
    if len(results) != expected_results:
        print(
            f"Partition runner incomplete: expected={expected_results} actual={len(results)}",
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
        if boundary_index is not None:
            returncode, log_path, timed_out = results[boundary_index]
            log = log_path.read_text(encoding="utf-8")
            aggregate.write(f"===== scoped serial boundary =====\n{log}")
            if log and not log.endswith("\n"):
                aggregate.write("\n")
            if returncode != 0 or timed_out:
                failed = True
                print(f"SERIAL BOUNDARY FAILED ({returncode})", file=sys.stderr)
                print(log, file=sys.stderr, end="" if log.endswith("\n") else "\n")
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--partitions-json", required=True)
    parser.add_argument("--expected-targets-json", required=True)
    parser.add_argument("--log-dir", required=True)
    parser.add_argument("--aggregate-log", required=True)
    parser.add_argument("--jobs", type=int, default=MAX_PARTITIONS)
    parser.add_argument(
        "--serial-last",
        action="store_true",
        help="Run the final host-sensitive partition after every parallel process exits.",
    )
    parser.add_argument(
        "--serial-boundary-json",
        default="[]",
        help="Run these host-sensitive paths alone after safe partition coverage exits.",
    )
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
        serial_boundary_value = json.loads(args.serial_boundary_json)
        serial_boundary = (
            _string_list(serial_boundary_value, name="serial boundary")
            if serial_boundary_value
            else ()
        )
    except (json.JSONDecodeError, ValueError) as exc:
        parser.error(str(exc))
    return run_partitions(
        partitions,
        log_dir=Path(args.log_dir),
        aggregate_log=Path(args.aggregate_log),
        jobs=args.jobs,
        timeout_seconds=args.shard_timeout_seconds,
        serial_last=args.serial_last,
        serial_boundary=serial_boundary,
    )


if __name__ == "__main__":
    raise SystemExit(main())
