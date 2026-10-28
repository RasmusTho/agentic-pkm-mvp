#!/usr/bin/env python3
"""Plan bounded process work units for the measured long full-suite module."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence

MAX_WORKERS = 4
TARGET_MODULE = "tests/deploy/test_deploy_channel_script.py"
SHARED_CHECKOUT_NODES = (
    f"{TARGET_MODULE}::test_rollback_dry_run_without_sha_parses_flag_and_skips_writes",
    f"{TARGET_MODULE}::test_rollback_with_explicit_sha_still_allows_flags",
)


def parse_collected_nodes(output: str, target: str) -> tuple[str, ...]:
    """Extract the exact collected node IDs for one requested test module."""

    if target != TARGET_MODULE:
        raise ValueError(f"node planner only accepts the measured module: {TARGET_MODULE}")
    prefix = f"{target}::"
    node_lines = tuple(
        line.strip()
        for line in output.splitlines()
        if line.strip().startswith("tests/") and "::" in line.strip()
    )
    unexpected = tuple(node for node in node_lines if not node.startswith(prefix))
    if unexpected:
        raise ValueError(
            "collection escaped the requested module: " + ", ".join(unexpected[:3])
        )
    if len(set(node_lines)) != len(node_lines):
        raise ValueError("collected node inventory contains duplicates")
    return node_lines


def plan_node_units(
    nodes: Sequence[str], target: str, *, max_workers: int = MAX_WORKERS
) -> tuple[tuple[str, ...], ...]:
    """Keep shared-checkout tests together and split the remaining nodes evenly."""

    if not 2 <= max_workers <= MAX_WORKERS:
        raise ValueError(f"worker cap must be between 2 and {MAX_WORKERS}")
    if target != TARGET_MODULE:
        raise ValueError(f"node planner only accepts the measured module: {TARGET_MODULE}")
    if not nodes:
        return ()
    if len(set(nodes)) != len(nodes):
        raise ValueError("collected node inventory contains duplicates")
    prefix = f"{target}::"
    if any(not node.startswith(prefix) for node in nodes):
        raise ValueError("collected node inventory escaped the requested module")

    required_shared = tuple(node for node in SHARED_CHECKOUT_NODES if node.startswith(prefix))
    missing_shared = tuple(node for node in required_shared if node not in nodes)
    if missing_shared:
        raise ValueError(
            "shared-checkout node inventory is incomplete: " + ", ".join(missing_shared)
        )

    shared = tuple(node for node in nodes if node in required_shared)
    remaining = tuple(node for node in nodes if node not in required_shared)
    units: list[tuple[str, ...]] = []
    if shared:
        units.append(shared)
    if remaining:
        bucket_count = min(max_workers - int(bool(shared)), len(remaining))
        for index in range(bucket_count):
            start = index * len(remaining) // bucket_count
            end = (index + 1) * len(remaining) // bucket_count
            units.append(remaining[start:end])

    flattened = tuple(node for unit in units for node in unit)
    if len(units) > max_workers or len(flattened) != len(nodes) or set(flattened) != set(nodes):
        raise ValueError("planned node work units do not cover collected nodes exactly once")
    if any(not unit for unit in units):
        raise ValueError("planned node work unit is empty")
    return tuple(units)


def write_plan(
    nodes: Sequence[str], target: str, output_dir: Path, *, max_workers: int = MAX_WORKERS
) -> tuple[str, ...]:
    """Write stable target files and an ordered execution-unit inventory."""

    units = plan_node_units(nodes, target, max_workers=max_workers)
    if not units:
        raise ValueError("cannot write node work units for an empty collection")
    output_dir.mkdir(parents=True, exist_ok=False)
    work_items: list[str] = []
    for index, unit in enumerate(units):
        item = f"deploy-node-unit-{index}"
        work_items.append(item)
        (output_dir / f"{item}.targets").write_text("\n".join(unit) + "\n", encoding="utf-8")
    (output_dir / "work-items").write_text("\n".join(work_items) + "\n", encoding="utf-8")
    (output_dir / "coverage.json").write_text(
        json.dumps(
            {
                "schema": "full-suite-collected-node-units.v1",
                "target": target,
                "max_workers": max_workers,
                "collected_node_count": len(nodes),
                "work_items": [
                    {"id": item, "nodes": list(unit)}
                    for item, unit in zip(work_items, units, strict=True)
                ],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return tuple(work_items)


def verify_node_results(
    expected: Sequence[str], target: str, lines: Sequence[str]
) -> tuple[str, ...]:
    """Require exactly one recognizable pytest result for each planned node."""

    statuses = {"PASSED", "FAILED", "ERROR", "SKIPPED", "XFAIL", "XPASS"}
    expected_set = set(expected)
    observed: list[str] = []
    for line in lines:
        stripped = line.strip()
        matched = False
        for node in expected_set:
            prefix = f"{node} "
            if stripped.startswith(prefix):
                matched = True
                status_parts = stripped[len(prefix):].split(maxsplit=1)
                status = status_parts[0] if status_parts else ""
                if status not in statuses:
                    raise ValueError("unrecognized pytest result for a collected node")
                observed.append(node)
                break
        if not matched and stripped.startswith(f"{target}::") and any(
            token in statuses for token in stripped.split()
        ):
            raise ValueError("unexpected pytest result for an unplanned node")
    if sorted(observed) != sorted(expected):
        missing = sorted(expected_set - set(observed))
        duplicate = sorted(node for node in set(observed) if observed.count(node) > 1)
        details = []
        if missing:
            details.append("missing=" + ", ".join(missing[:3]))
        if duplicate:
            details.append("duplicate=" + ", ".join(duplicate[:3]))
        raise ValueError("node execution evidence incomplete: " + "; ".join(details))
    return tuple(observed)


def verify_executed_nodes(coverage_path: Path, logs_dir: Path) -> tuple[str, ...]:
    """Require one pytest result line for every planned node in its own unit log."""

    try:
        coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read collected-node coverage receipt: {exc}") from exc
    if not isinstance(coverage, dict) or coverage.get("schema") != "full-suite-collected-node-units.v1":
        raise ValueError("collected-node coverage receipt has an unsupported schema")
    target = coverage.get("target")
    work_items = coverage.get("work_items")
    max_workers = coverage.get("max_workers")
    if target != TARGET_MODULE or not isinstance(work_items, list):
        raise ValueError("collected-node coverage receipt is malformed")
    if not isinstance(max_workers, int) or not 2 <= max_workers <= MAX_WORKERS:
        raise ValueError("collected-node coverage receipt exceeds the worker cap")

    expected_by_unit: dict[str, tuple[str, ...]] = {}
    for item in work_items:
        if not isinstance(item, dict):
            raise ValueError("collected-node work item is malformed")
        identifier = item.get("id")
        nodes = item.get("nodes")
        if (
            not isinstance(identifier, str)
            or not identifier.startswith("deploy-node-unit-")
            or not isinstance(nodes, list)
            or not nodes
            or not all(isinstance(node, str) and node.startswith(f"{target}::") for node in nodes)
        ):
            raise ValueError("collected-node work item is malformed")
        if identifier in expected_by_unit:
            raise ValueError("collected-node work item IDs contain duplicates")
        expected_by_unit[identifier] = tuple(nodes)
    expected_nodes = tuple(node for nodes in expected_by_unit.values() for node in nodes)
    if not expected_by_unit or len(expected_by_unit) > max_workers:
        raise ValueError("collected-node work unit count exceeds the worker cap")
    if len(set(expected_nodes)) != len(expected_nodes):
        raise ValueError("collected-node plan contains duplicate nodes")

    observed_by_unit: dict[str, tuple[str, ...]] = {}
    for identifier, expected_nodes_for_unit in expected_by_unit.items():
        log_path = logs_dir / f"{identifier}.log"
        try:
            lines = log_path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise ValueError(f"missing collected-node execution log: {identifier}") from exc
        try:
            observed_by_unit[identifier] = verify_node_results(expected_nodes_for_unit, target, lines)
        except ValueError as exc:
            raise ValueError(f"{identifier}: {exc}") from exc

    observed_nodes = tuple(node for nodes in observed_by_unit.values() for node in nodes)
    if len(observed_nodes) != len(expected_nodes) or set(observed_nodes) != set(expected_nodes):
        raise ValueError("node execution evidence does not match the planned inventory exactly once")
    return observed_nodes


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collected-output")
    parser.add_argument("--target")
    parser.add_argument("--output-dir")
    parser.add_argument("--verify-coverage")
    parser.add_argument("--logs-dir")
    parser.add_argument("--max-workers", type=int, default=MAX_WORKERS)
    args = parser.parse_args(argv)
    try:
        if args.verify_coverage:
            if not args.logs_dir or args.collected_output or args.target or args.output_dir:
                raise ValueError("node verification requires only --verify-coverage and --logs-dir")
            observed = verify_executed_nodes(Path(args.verify_coverage), Path(args.logs_dir))
            print(f"Verified one pytest result for each of {len(observed)} collected nodes.")
            return 0
        if not args.collected_output or not args.target or not args.output_dir or args.logs_dir:
            raise ValueError("node planning requires --collected-output, --target, and --output-dir")
        nodes = parse_collected_nodes(
            Path(args.collected_output).read_text(encoding="utf-8"), args.target
        )
        work_items = write_plan(
            nodes,
            args.target,
            Path(args.output_dir),
            max_workers=args.max_workers,
        )
    except (OSError, ValueError) as exc:
        action = "verification" if args.verify_coverage else "planning"
        print(f"full-suite node {action} failed: {exc}", file=sys.stderr)
        return 2
    print(
        f"Planned {len(nodes)} exact collected nodes across {len(work_items)} work units "
        f"(worker cap {args.max_workers})."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
