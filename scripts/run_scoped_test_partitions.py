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
from scripts.plan_full_suite_node_shards import (
    MEASURED_NODE_MODULES, NATIVE_ADMISSION_MODULE, TARGET_MODULE, plan_node_units, verify_node_results,
)

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


def _optional_string_list(value: object, *, name: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a JSON list")
    return _string_list(value, name=name) if value else ()


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


def _is_deploy_target(target: str) -> bool:
    path = _target_file(target)
    return path == "tests/deploy" or path.startswith("tests/deploy/")


def _strictly_covers(ancestor: str, descendant: str) -> bool:
    """Return whether one positional pytest target makes another redundant."""

    if ancestor == descendant or ancestor.startswith("-") or descendant.startswith("-"):
        return False
    ancestor_file = _target_file(ancestor)
    descendant_file = _target_file(descendant)
    if "::" not in ancestor and ancestor_file.endswith(".py"):
        return ancestor_file == descendant_file and "::" in descendant
    return (
        "::" not in ancestor
        and not ancestor_file.endswith(".py")
        and descendant_file.startswith(f"{ancestor_file}/")
    )


def _effective_targets(targets: Sequence[str]) -> tuple[str, ...]:
    """Normalize authenticated ancestor/descendant overlap to one execution."""

    return tuple(
        target
        for target in targets
        if not any(_strictly_covers(other, target) for other in targets)
    )


def _deploy_test_files(path: str) -> tuple[str, ...]:
    """Expand one authenticated deploy target to stable current-head files."""

    target = Path(_target_file(path))
    if target.suffix == ".py":
        return (str(target),)
    if not target.is_dir():
        raise ValueError(f"deploy target is not a current-head file or directory: {path}")
    files = tuple(
        str(candidate)
        for candidate in sorted(target.rglob("*.py"))
        if candidate.name.startswith("test_") or candidate.name.endswith("_test.py")
    )
    if not files:
        raise ValueError(f"deploy target has no current-head test files: {path}")
    return files


def validate_execution_units(
    units_value: object, expected_value: object
) -> tuple[tuple[str, ...], ...]:
    """Authenticate a derived work-unit plan against selected targets.

    The selected-target inventory remains the authority. Non-deploy targets
    are preserved exactly, except the complete tests/ops directory may expand
    to whole modules. Deploy directories also require the complete current-head file
    inventory exactly once.  Runner-generated options are never accepted as
    evidence of target coverage.
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
    if any(target.startswith("-") for target in actual):
        raise ValueError("execution-unit inventory must not contain pytest options")

    if "tests/ops" in expected and "tests/ops" not in actual:
        # Ops-only plans expand this one root into whole modules. Authenticate
        # the complete inventory before accepting the unchanged serial runner.
        ops_files = _deploy_test_files("tests/ops")
        expected = tuple(dict.fromkeys(
            item for target in expected
            for item in (ops_files if target == "tests/ops" else (target,))
            if target == "tests/ops" or not target.startswith("tests/ops/")
        ))

    expected_deploy = tuple(
        target for target in expected if _is_deploy_target(target)
    )
    expected_non_deploy = tuple(target for target in expected if target not in expected_deploy)
    actual_deploy = tuple(
        target for target in actual if _is_deploy_target(target)
    )
    actual_non_deploy = tuple(target for target in actual if target not in actual_deploy)
    if Counter(actual_non_deploy) != Counter(expected_non_deploy):
        raise ValueError(
            "execution-unit inventory is incomplete or does not preserve "
            "non-deploy targets exactly once"
        )
    if Counter(_effective_targets(actual_non_deploy)) != Counter(
        _effective_targets(expected_non_deploy)
    ):
        raise ValueError("execution-unit effective coverage escapes selected targets")

    expected_deploy_files = {
        file_path
        for target in expected_deploy
        for file_path in _deploy_test_files(target)
    }
    if any("::" in target or not _target_file(target).endswith(".py") for target in actual_deploy):
        raise ValueError("deploy execution units must use stable file targets")
    if Counter(_target_file(target) for target in actual_deploy) != Counter(
        expected_deploy_files
    ):
        raise ValueError(
            "deploy execution-unit inventory does not match current-head files exactly once"
        )
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


def _collect_parallel_nodes(targets: Sequence[str]) -> tuple[str, ...]:
    """Collect the parallel inventory once for node splitting and atomic weights."""
    command = [
        "pytest",
        "--collect-only",
        "-q",
        "-m",
        PR_MARKER_EXPRESSION,
        *targets,
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
            f"parallel work-unit collection timed out after {COLLECTION_TIMEOUT_SECONDS}s"
        ) from exc
    finally:
        _terminate_process_group(process.pid)
    if process.returncode not in (0, 5):
        raise RuntimeError(
            f"parallel work-unit collection failed ({process.returncode})\n{output}"
        )
    nodes = tuple(sorted(
        line.strip()
        for line in output.splitlines()
        if line.strip().startswith("tests/") and "::" in line.strip()
    ))
    if len(set(nodes)) != len(nodes):
        raise ValueError("collected parallel node inventory contains duplicates")
    return nodes


def _serial_safe_candidates(
    targets: Sequence[str], serial_boundary: tuple[str, ...]
) -> tuple[tuple[tuple[str, ...], ...], tuple[str, ...]]:
    """Remove boundary files and bind every exclusion to its covering root."""

    if len(set(serial_boundary)) != len(serial_boundary):
        raise ValueError("serial boundary contains duplicates")
    if any("::" in path or not path.endswith(".py") for path in serial_boundary):
        raise ValueError("serial boundary entries must be stable test files")

    candidates: list[tuple[str, ...]] = []
    covered: set[str] = set()
    for target in targets:
        path = _target_file(target)
        if path in serial_boundary:
            covered.add(path)
            continue
        is_directory = "::" not in target and not path.endswith(".py")
        exclusions = tuple(
            boundary
            for boundary in serial_boundary
            if is_directory and boundary.startswith(f"{path}/")
        )
        covered.update(exclusions)
        candidates.append((target, *(f"--ignore={path}" for path in exclusions)))
    if covered != set(serial_boundary):
        missing = sorted(set(serial_boundary) - covered)
        raise ValueError(
            "serial boundary is not fully covered by the execution plan: "
            + ", ".join(missing)
        )
    return tuple(candidates), serial_boundary


def _expand_and_balance_parallel(
    candidates: Sequence[Sequence[str]],
    *,
    jobs: int,
    expected_targets: Sequence[str] = (),
) -> tuple[tuple[str, ...], ...]:
    """Split the measured module safely, then balance bounded atomic candidates."""

    positional_targets = tuple(
        target
        for candidate in candidates
        for target in candidate
        if not target.startswith("-")
    )
    effective_targets = set(_effective_targets(positional_targets))
    candidates = tuple(
        candidate
        for candidate in candidates
        if next(target for target in candidate if not target.startswith("-"))
        in effective_targets
    )

    # One collection includes the same serial exclusions as execution. Directory
    # roots remain atomic; their case count is a packing weight, not a new shard.
    collected = _collect_parallel_nodes(tuple(
        argument for candidate in candidates for argument in candidate
    )) if candidates else ()

    def nodes_for_target(target: str) -> tuple[str, ...]:
        return tuple(node for node in collected if node == target or _strictly_covers(target, node))

    expanded: list[tuple[str, ...]] = []
    seen_targets: set[str] = set()
    node_weight: dict[str, int] = {}
    for candidate in candidates:
        positional = tuple(target for target in candidate if not target.startswith("-"))
        options = tuple(target for target in candidate if target.startswith("-"))
        if len(positional) != 1:
            raise ValueError("each execution candidate must contain one positional target")
        target = positional[0]
        if target == NATIVE_ADMISSION_MODULE and jobs > 1 and nodes_for_target(target):
            if options:
                raise ValueError("native admission node candidates must not contain pytest options")
            refined = plan_node_units(nodes_for_target(target), target, max_workers=2)
            for unit in refined:
                node_weight[unit[0]] = len(unit)
        elif _is_deploy_target(target):
            if options:
                raise ValueError("deploy execution candidates must not contain pytest options")
            nodes = nodes_for_target(target)
            files = _deploy_test_files(target)
            deploy_units: list[tuple[str, ...]] = []
            for file_path in files:
                file_nodes = tuple(node for node in nodes if _target_file(node) == file_path)
                if file_path == TARGET_MODULE and file_nodes and jobs > 1:
                    units = plan_node_units(file_nodes, TARGET_MODULE, max_workers=jobs)
                    deploy_units.extend(units)
                    for unit in units:
                        node_weight[unit[0]] = len(unit)
                else:
                    deploy_units.append((file_path,))
                    node_weight[file_path] = max(1, len(file_nodes))
            refined = tuple(deploy_units)
        else:
            refined = (tuple(candidate),)
            node_weight[target] = max(1, len(nodes_for_target(target)))
        for item in refined:
            positional_target = next(value for value in item if not value.startswith("-"))
            if positional_target in seen_targets:
                raise ValueError("expanded execution plan contains overlapping work")
            seen_targets.add(positional_target)
            expanded.append(item)
    expected_deploy_files = {
        file_path
        for target in expected_targets
        if _is_deploy_target(target)
        for file_path in _deploy_test_files(target)
    }
    actual_deploy_files = {
        _target_file(target)
        for candidate in expanded
        for target in candidate
        if _is_deploy_target(target)
    }
    if expected_deploy_files and actual_deploy_files != expected_deploy_files:
        raise ValueError(
            "expanded deploy file inventory does not match selected coverage exactly once"
        )
    if not expanded:
        return ()
    buckets: list[list[str]] = [[] for _ in range(min(jobs, len(expanded)))]
    weights = [0] * len(buckets)

    def candidate_weight(candidate: tuple[str, ...]) -> int:
        positional = next(target for target in candidate if not target.startswith("-"))
        return node_weight.get(positional, 1)

    for candidate in sorted(expanded, key=lambda item: (-candidate_weight(item), item)):
        index = min(range(len(buckets)), key=lambda item: (weights[item], item))
        buckets[index].extend(candidate)
        weights[index] += candidate_weight(candidate)
    return tuple(tuple(bucket) for bucket in buckets if bucket)


def _report_partition_result(
    result: tuple[int, int, Path, bool], targets: Sequence[str], *, label: str
) -> tuple[int, int, Path, bool]:
    """Validate collected-node evidence and surface a completed failure now."""

    index, returncode, log_path, timed_out = result
    for module in MEASURED_NODE_MODULES:
        nodes = tuple(target for target in targets if target.startswith(f"{module}::"))
        if not nodes:
            continue
        try:
            verify_node_results(nodes, module, log_path.read_text(encoding="utf-8").splitlines())
        except (OSError, ValueError) as exc:
            with log_path.open("a", encoding="utf-8") as log:
                log.write(f"\nCollected-node verification failed: {exc}\n")
            returncode = returncode or 1
    if returncode != 0 or timed_out:
        log = log_path.read_text(encoding="utf-8")
        print(f"{label} FAILED ({returncode}): {index}", file=sys.stderr, flush=True)
        print(log, file=sys.stderr, end="" if log.endswith("\n") else "\n", flush=True)
    return index, returncode, log_path, timed_out


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
        candidates, boundary_targets = _serial_safe_candidates(
            tuple(target for partition in source_partitions for target in partition),
            serial_boundary,
        )
        parallel_partitions = list(
            _expand_and_balance_parallel(
                candidates,
                jobs=jobs,
                expected_targets=expected_targets,
            )
        )
    elif execution_units:
        candidates = tuple(
            (target,)
            for partition in parallel_partitions
            for target in partition
        )
        parallel_partitions = list(
            _expand_and_balance_parallel(
                candidates,
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
                index = futures[future]
                index, returncode, log_path, timed_out = _report_partition_result(
                    future.result(), parallel_partitions[index], label="PARTITION"
                )
                results[index] = (returncode, log_path, timed_out)
                print(
                    f"PARTITION FINISHED ({returncode}): {index} "
                    f"targets={len(parallel_partitions[index])}",
                    flush=True,
                )
    serial_last_index: int | None = None
    if serial_last:
        serial_last_index = len(parallel_partitions)
        result_index, returncode, log_path, timed_out = _run_partition(
            serial_last_index,
            source_partitions[-1],
            log_dir=log_dir,
            timeout_seconds=timeout_seconds,
        )
        result_index, returncode, log_path, timed_out = _report_partition_result(
            (result_index, returncode, log_path, timed_out), source_partitions[-1],
            label="SERIAL PARTITION",
        )
        results[result_index] = (returncode, log_path, timed_out)
        print(
            f"SERIAL PARTITION FINISHED ({returncode}): {serial_last_index} "
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
        result_index, returncode, log_path, timed_out = _report_partition_result(
            (result_index, returncode, log_path, timed_out), boundary_targets,
            label="SERIAL BOUNDARY",
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
        if serial_last_index is not None:
            returncode, log_path, timed_out = results[serial_last_index]
            log = log_path.read_text(encoding="utf-8")
            aggregate.write(f"===== scoped serial partition =====\n{log}")
            if log and not log.endswith("\n"):
                aggregate.write("\n")
            if returncode != 0 or timed_out:
                failed = True
        if boundary_index is not None:
            returncode, log_path, timed_out = results[boundary_index]
            log = log_path.read_text(encoding="utf-8")
            aggregate.write(f"===== scoped serial boundary =====\n{log}")
            if log and not log.endswith("\n"):
                aggregate.write("\n")
            if returncode != 0 or timed_out:
                failed = True
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
        expected_targets_value = json.loads(args.expected_targets_json)
        partitions = validate_inventory(
            json.loads(args.partitions_json), expected_targets_value
        )
        serial_boundary = _optional_string_list(
            json.loads(args.serial_boundary_json),
            name="serial boundary",
        )
        execution_units_value = json.loads(args.execution_units_json)
        if not isinstance(execution_units_value, list):
            raise ValueError("execution-unit inventory must be a JSON list")
        execution_units = validate_execution_units(
            execution_units_value, expected_targets_value
        ) if execution_units_value else ()
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
