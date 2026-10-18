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
COLLECTION_TIMEOUT_SECONDS = 300


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


def _target_file(target: str) -> str:
    return target.split("::", 1)[0]


def _target_covers(expected: str, actual: str) -> bool:
    """Return whether an execution target is inside an authenticated target."""

    if actual.startswith("--"):
        return True
    expected_file = _target_file(expected)
    actual_file = _target_file(actual)
    if expected_file == actual_file:
        return True
    return (
        "::" not in expected
        and not expected_file.endswith(".py")
        and actual_file.startswith(f"{expected_file}/")
    )


def validate_execution_units(
    units_value: object, expected_value: object
) -> tuple[tuple[str, ...], ...]:
    """Authenticate a derived work-unit plan against selected targets.

    The selected-target inventory remains the authority.  Work units may be
    concrete files or collected node IDs below a selected directory, but they
    may never introduce a path outside that inventory or repeat one collected
    node.
    """

    expected = _string_list(expected_value, name="expected targets")
    if len(set(expected)) != len(expected):
        raise ValueError("expected targets contain duplicates")
    if not isinstance(units_value, list) or not units_value:
        raise ValueError("execution-unit inventory must be a non-empty JSON list")
    if len(units_value) > MAX_PARTITIONS:
        raise ValueError(f"execution-unit inventory exceeds {MAX_PARTITIONS} shards")
    units = tuple(
        _string_list(unit, name=f"execution unit {index}")
        for index, unit in enumerate(units_value)
    )
    actual = tuple(target for unit in units for target in unit)
    if len(set(actual)) != len(actual):
        raise ValueError("execution-unit inventory contains duplicate work")
    if any(
        not any(_target_covers(expected_target, target) for expected_target in expected)
        for target in actual
    ):
        raise ValueError("execution-unit inventory escapes selected targets")
    if any(
        not any(_target_covers(expected_target, target) for target in actual)
        for expected_target in expected
    ):
        raise ValueError("execution-unit inventory is incomplete")
    return units


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


def _collect_deploy_nodes(target: str, *, cache: dict[str, tuple[str, ...]]) -> tuple[str, ...]:
    """Collect deploy nodes once so a slow file can be split across workers."""

    path = _target_file(target)
    if path in cache:
        return cache[path]
    command = [
        "pytest",
        "--collect-only",
        "-q",
        "-m",
        PR_MARKER_EXPRESSION,
        target,
    ]
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=os.environ.copy(),
        start_new_session=True,
    )
    try:
        output, _ = process.communicate(timeout=COLLECTION_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as exc:
        _terminate_process_group(process.pid)
        process.wait()
        raise RuntimeError(
            f"deploy work-unit collection timed out after {COLLECTION_TIMEOUT_SECONDS}s: {target}"
        ) from exc
    finally:
        _terminate_process_group(process.pid)
    if process.returncode not in (0, 5):
        raise RuntimeError(
            f"deploy work-unit collection failed ({process.returncode}): {target}\n{output}"
        )
    nodes = tuple(
        sorted(
            {
                line.strip()
                for line in output.splitlines()
                if line.strip().startswith(path) and "::" in line.strip()
            }
        )
    )
    cache[path] = nodes
    return nodes


def _expand_and_balance_parallel(
    partitions: Sequence[Sequence[str]],
    *,
    jobs: int,
    expected_targets: Sequence[str] = (),
) -> tuple[tuple[str, ...], ...]:
    """Refine deploy files into nodes, then balance all parallel work units."""

    cache: dict[str, tuple[str, ...]] = {}
    expanded: list[str] = []
    seen_nodes: set[str] = set()
    for partition in partitions:
        for target in partition:
            path = _target_file(target)
            if path.startswith("tests/deploy/") or path == "tests/deploy":
                nodes = _collect_deploy_nodes(target, cache=cache)
                candidates = nodes or (target,)
            else:
                candidates = (target,)
            for candidate in candidates:
                if candidate in seen_nodes:
                    continue
                seen_nodes.add(candidate)
                expanded.append(candidate)
    expected_deploy_nodes: set[str] = set()
    for target in expected_targets:
        path = _target_file(target)
        if path == "tests/deploy" or path.startswith("tests/deploy/"):
            expected_deploy_nodes.update(_collect_deploy_nodes(target, cache=cache))
    actual_deploy_nodes = {
        target
        for target in expanded
        if _target_file(target).startswith("tests/deploy/") and "::" in target
    }
    if expected_deploy_nodes and actual_deploy_nodes != expected_deploy_nodes:
        raise ValueError(
            "expanded deploy node inventory does not match selected coverage exactly once"
        )
    if not expanded:
        return ()
    buckets: list[list[str]] = [[] for _ in range(min(jobs, len(expanded)))]
    weights = [0] * len(buckets)
    for candidate in sorted(expanded):
        index = min(range(len(buckets)), key=lambda item: (weights[item], item))
        buckets[index].append(candidate)
        weights[index] += 1
    return tuple(tuple(bucket) for bucket in buckets if bucket)


def _split_serial_boundary(
    targets: tuple[str, ...], serial_boundary: tuple[str, ...]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    roots = tuple(
        target for target in targets if "::" not in target and not target.endswith(".py")
    )
    target_files = {target.split("::", 1)[0] for target in targets}
    if not serial_boundary or not all(
        path in target_files or any(path.startswith(f"{root}/") for root in roots)
        for path in serial_boundary
    ):
        raise ValueError(
            "serial boundary must be contained by a directory target in the last partition"
        )
    parallel: list[str] = []
    for target in targets:
        if target.split("::", 1)[0] in serial_boundary:
            continue
        if any(target.startswith(f"{root}/") for root in roots):
            continue
        parallel.append(target)
    parallel.extend(
        f"--ignore={path}"
        for path in serial_boundary
        if any(path.startswith(f"{root}/") for root in roots)
    )
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
    execution_units: tuple[tuple[str, ...], ...] = (),
    expected_targets: tuple[str, ...] = (),
) -> int:
    log_dir.mkdir(parents=True, exist_ok=True)
    results: dict[int, tuple[int, Path, bool]] = {}
    if serial_last and serial_boundary:
        raise ValueError("--serial-last and --serial-boundary-json are mutually exclusive")
    source_partitions = execution_units or partitions
    parallel_count = len(source_partitions) - 1 if serial_last else len(source_partitions)
    parallel_partitions = list(source_partitions[:parallel_count])
    boundary_targets: tuple[str, ...] = ()
    if serial_boundary:
        if not source_partitions:
            raise ValueError("serial boundary requires an execution partition")
        parallel_targets, boundary_targets = _split_serial_boundary(
            source_partitions[-1], serial_boundary
        )
        if execution_units:
            if parallel_targets:
                parallel_partitions.append(parallel_targets)
            parallel_partitions = list(
                _expand_and_balance_parallel(
                    parallel_partitions,
                    jobs=min(jobs, MAX_PARTITIONS - 1 if boundary_targets else MAX_PARTITIONS),
                    expected_targets=expected_targets,
                )
            )
        elif parallel_partitions:
            parallel_partitions[-1] = parallel_targets
    elif execution_units:
        parallel_partitions = list(
            _expand_and_balance_parallel(
                parallel_partitions,
                jobs=jobs,
                expected_targets=expected_targets,
            )
        )
    runnable_partitions: list[tuple[int, tuple[str, ...]]] = []
    for index, targets in enumerate(parallel_partitions):
        if targets:
            runnable_partitions.append((index, targets))
            continue
        log_path = log_dir / f"partition-{index}.log"
        log_path.write_text(
            "Partition coverage moved entirely to the serial boundary.\n",
            encoding="utf-8",
        )
        results[index] = (0, log_path, False)
    if runnable_partitions:
        with ThreadPoolExecutor(max_workers=min(jobs, len(runnable_partitions))) as executor:
            futures = {
                executor.submit(
                    _run_partition,
                    index,
                    targets,
                    log_dir=log_dir,
                    timeout_seconds=timeout_seconds,
                ): index
                for index, targets in runnable_partitions
            }
            for future in as_completed(futures):
                index, returncode, log_path, timed_out = future.result()
                results[index] = (returncode, log_path, timed_out)
                print(
                    f"PARTITION FINISHED ({returncode}): {index} "
                    f"targets={len(parallel_partitions[index])}",
                    flush=True,
                )
    if serial_last:
        index = len(parallel_partitions)
        result_index, returncode, log_path, timed_out = _run_partition(
            index,
            source_partitions[-1],
            log_dir=log_dir,
            timeout_seconds=timeout_seconds,
        )
        results[result_index] = (returncode, log_path, timed_out)
        print(
            f"PARTITION FINISHED ({returncode}): {index} "
            f"targets={len(source_partitions[-1])}",
            flush=True,
        )
    boundary_index: int | None = None
    if boundary_targets:
        boundary_index = len(parallel_partitions)
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
    expected_results = len(parallel_partitions) + int(serial_last) + int(
        boundary_index is not None
    )
    if len(results) != expected_results:
        print(
            f"Partition runner incomplete: expected={expected_results} actual={len(results)}",
            file=sys.stderr,
        )
        return 1
    failed = False
    with aggregate_log.open("w", encoding="utf-8") as aggregate:
        for index in range(len(parallel_partitions)):
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
    parser.add_argument(
        "--execution-units-json",
        default="[]",
        help="Derived balanced work units authenticated against the selected targets.",
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
        execution_units_value = json.loads(args.execution_units_json)
        execution_units = (
            validate_execution_units(execution_units_value, json.loads(args.expected_targets_json))
            if execution_units_value
            else ()
        )
    except (json.JSONDecodeError, ValueError) as exc:
        parser.error(str(exc))
    try:
        return run_partitions(
            partitions,
            log_dir=Path(args.log_dir),
            aggregate_log=Path(args.aggregate_log),
            jobs=args.jobs,
            timeout_seconds=args.shard_timeout_seconds,
            serial_last=args.serial_last,
            serial_boundary=serial_boundary,
            execution_units=execution_units,
            expected_targets=tuple(json.loads(args.expected_targets_json)),
        )
    except (RuntimeError, ValueError) as exc:
        print(f"Execution-unit planning failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
