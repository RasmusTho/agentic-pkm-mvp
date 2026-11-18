"""Post-merge heavy-test profile run on the ygg `test` VM (#6158).

`scripts/select_pr_tests.py :: HEAVY_PR_DEFERRED_TARGETS` defers heavy targets
from the required PR check. After a candidate's native `test` deployment
commits, the host controller runs this fixed profile on the VM and dispatches
its bounded verdict to `.github/workflows/post-merge-heavy-tests.yml`.

The profile runs inside the admitted image against the exact candidate tree
at `/work`, with the selector's own heavy targets, the PR marker expression and
the 120-second thread watchdog, matching the GitHub-hosted run it replaces.
It does not gate channel advancement or rewrite `postmerge-pg.v1`.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from typing import Any
from uuid import UUID

PROFILE_VERSION = "postmerge-heavy.v1"
TEST_TIMEOUT = 120
PROFILE_DEADLINE = 3600
RESULT_PREFIX = "YGGDRASIL_HEAVY_ACCEPTANCE="
# A docker-gated test that skips on the VM would be silent coverage loss
# against the GitHub-hosted run, which always has the docker CLI.
DOCKER_SKIP_REASON = "docker executable not found"
MAX_FAILURES = 20
MAX_NODEID = 200
MAX_WORKERS = 4
PROCESS_GROUP_GRACE_SECONDS = 0.25
HEAVY_TARGET = "tests/deploy"
VERDICTS = ("passed", "failed", "refused")
COUNT_KEYS = ("selected", "passed", "failed", "skipped", "docker_skipped")


class HeavyAcceptanceError(RuntimeError):
    def __init__(self, reason: str = "heavy_acceptance_refused") -> None:
        super().__init__(reason)
        self.reason = reason


def identity(sha: str, digest: str, channel: str, operation_id: str) -> dict[str, str]:
    if (
        re.fullmatch(r"[0-9a-f]{40}", sha) is None
        or re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is None
        or channel not in {"dev", "test"}
        or str(UUID(operation_id)) != operation_id
    ):
        raise HeavyAcceptanceError("heavy_identity_refused")
    return {
        "profile_version": PROFILE_VERSION,
        "source_sha": sha,
        "image_digest": digest,
        "channel": channel,
        "operation_id": operation_id,
    }


def _bounded_failures(value: Any) -> list[str]:
    if (
        not isinstance(value, list)
        or len(value) > MAX_FAILURES
        or any(
            not isinstance(item, str)
            or not item
            or len(item) > MAX_NODEID
            or re.search(r"[\x00-\x1f]", item)
            for item in value
        )
    ):
        raise HeavyAcceptanceError("heavy_evidence_refused")
    return list(value)


def classify(summary: Any, expected: dict[str, str]) -> dict[str, Any]:
    """Turn an in-container summary into a bounded verdict; never a vacuous pass."""
    if (
        not isinstance(summary, dict)
        or set(summary)
        != set(expected) | {"targets", "exit_status", "failures", "report_hash", *COUNT_KEYS}
        or any(summary.get(key) != value for key, value in expected.items())
        or not isinstance(summary["targets"], list)
        or not summary["targets"]
        or any(
            not isinstance(t, str) or re.fullmatch(r"tests/[A-Za-z0-9_./-]+", t) is None
            for t in summary["targets"]
        )
        or type(summary["exit_status"]) is not int
        or any(type(summary[key]) is not int or summary[key] < 0 for key in COUNT_KEYS)
        or re.fullmatch(r"[0-9a-f]{64}", str(summary["report_hash"])) is None
    ):
        raise HeavyAcceptanceError("heavy_evidence_refused")
    failures = _bounded_failures(summary["failures"])
    passed = (
        summary["exit_status"] == 0
        and summary["failed"] == 0
        and summary["docker_skipped"] == 0
        and summary["selected"] > 0
        and summary["passed"] > 0
        and not failures
    )
    return {
        **expected,
        "result": "passed" if passed else "failed",
        "targets": summary["targets"],
        "failures": failures,
        "report_hash": summary["report_hash"],
        **{key: summary[key] for key in COUNT_KEYS},
    }


def refusal(reason: str) -> dict[str, Any]:
    if re.fullmatch(r"[a-z0-9_]{1,64}", reason) is None:
        reason = "heavy_acceptance_refused"
    return {"profile_version": PROFILE_VERSION, "result": "refused", "reason": reason}


def _load_selector(root: Path) -> Any:
    spec = importlib.util.spec_from_file_location(
        "heavy_select_pr_tests", root / "scripts/select_pr_tests.py"
    )
    if spec is None or spec.loader is None:
        raise HeavyAcceptanceError("heavy_selector_unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(spec.name, None)
        raise
    return module


def pytest_arguments(
    marker: str, targets: list[str], *, cache_dir: str = "/tmp/heavy-acceptance-cache"
) -> list[str]:
    return [
        "-q",
        "-m",
        marker,
        *targets,
        "--tb=short",
        "-p",
        "timeout",
        "--timeout=" + str(TEST_TIMEOUT),
        "--timeout-method=thread",
        "-o",
        "cache_dir=" + cache_dir,
    ]


class HeavyResults:
    """Count outcomes; a failure, error or docker-gated skip cannot pass."""

    def __init__(self) -> None:
        self.nodes: set[str] = set()
        self.passed: set[str] = set()
        self.failed: list[str] = []
        self.skipped = 0
        self.docker_skipped = 0
        self.watchdog = False

    def pytest_collection_finish(self, session: Any) -> None:
        self.nodes = {item.nodeid for item in session.items}
        self.watchdog = (
            session.config.getoption("timeout") == TEST_TIMEOUT
            and session.config.getoption("timeout_method") == "thread"
        )

    def pytest_runtest_logreport(self, report: Any) -> None:
        if report.failed:
            if report.nodeid not in self.failed:
                self.failed.append(report.nodeid)
        elif report.skipped and not hasattr(report, "wasxfail"):
            self.skipped += 1
            if DOCKER_SKIP_REASON in str(report.longrepr):
                self.docker_skipped += 1
        elif report.when == "call" and report.passed:
            self.passed.add(report.nodeid)

    def pytest_collectreport(self, report: Any) -> None:
        if report.failed:
            self.failed.append(report.nodeid or "collection")

    def summary(self, exit_status: int) -> dict[str, Any]:
        if not self.watchdog:
            raise HeavyAcceptanceError("heavy_watchdog_missing")
        report_hash = hashlib.sha256(
            json.dumps([sorted(self.passed), self.failed], separators=(",", ":")).encode()
        ).hexdigest()
        return {
            "exit_status": exit_status,
            "selected": len(self.nodes),
            "passed": len(self.passed),
            "failed": len(self.failed),
            "skipped": self.skipped,
            "docker_skipped": self.docker_skipped,
            "failures": [node[:MAX_NODEID] for node in self.failed[:MAX_FAILURES]],
            "report_hash": report_hash,
        }


def _terminate_process_group(process_group: int) -> None:
    """Terminate one owned worker and every child it created."""

    try:
        os.killpg(process_group, signal.SIGTERM)
    except (PermissionError, ProcessLookupError):
        return
    time.sleep(PROCESS_GROUP_GRACE_SECONDS)
    try:
        os.killpg(process_group, signal.SIGKILL)
    except (PermissionError, ProcessLookupError):
        pass


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise HeavyAcceptanceError("heavy_deadline_exceeded")
    return remaining


def _collect_nodes(root: Path, marker: str, target: str, deadline: float) -> tuple[str, ...]:
    """Collect the authoritative candidate node inventory once for aggregation."""

    process = subprocess.Popen(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-m", marker, target],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=os.environ.copy(),
        start_new_session=True,
    )
    try:
        try:
            output, _ = process.communicate(timeout=_remaining(deadline))
        except subprocess.TimeoutExpired:
            _terminate_process_group(process.pid)
            process.wait()
            raise HeavyAcceptanceError("heavy_deadline_exceeded") from None
    finally:
        _terminate_process_group(process.pid)
    if process.returncode not in (0, 5):
        raise HeavyAcceptanceError("heavy_collection_failed")
    nodes = tuple(
        sorted(
            line.strip()
            for line in output.splitlines()
            if line.strip().startswith(target + "/") and "::" in line.strip()
        )
    )
    if not nodes:
        raise HeavyAcceptanceError("heavy_selection_empty")
    if len(set(nodes)) != len(nodes):
        raise HeavyAcceptanceError("heavy_collection_duplicate")
    return nodes


def _load_partition_tools(root: Path) -> Any:
    """Load the existing source-root partition model only during execution."""

    path = root / "scripts" / "run_scoped_test_partitions.py"
    if not path.is_file():
        raise HeavyAcceptanceError("heavy_partition_tools_unavailable")
    spec = importlib.util.spec_from_file_location("heavy_run_scoped_partitions", path)
    if spec is None or spec.loader is None:
        raise HeavyAcceptanceError("heavy_partition_tools_unavailable")
    inserted = str(root)
    sys.path.insert(0, inserted)
    try:
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    except Exception as exc:
        raise HeavyAcceptanceError("heavy_partition_tools_unavailable") from exc
    finally:
        if sys.path and sys.path[0] == inserted:
            sys.path.pop(0)


def _partition_targets(
    root: Path,
    marker: str,
    targets: tuple[str, ...],
    expected_nodes: tuple[str, ...],
    deadline: float,
) -> tuple[tuple[str, ...], ...]:
    """Reuse the bounded source-root planner and authenticate its file inventory."""

    tools = _load_partition_tools(root)
    if tools.PR_MARKER_EXPRESSION != marker:
        raise HeavyAcceptanceError("heavy_selector_mismatch")
    tools.COLLECTION_TIMEOUT_SECONDS = max(1, int(_remaining(deadline)))
    previous_cwd = Path.cwd()
    try:
        os.chdir(root)
        try:
            partitions = tuple(
                tools._expand_and_balance_parallel(
                    tuple((target,) for target in targets),
                    jobs=MAX_WORKERS,
                    expected_targets=targets,
                )
            )
            expected_files = tuple(tools._deploy_test_files(HEAVY_TARGET))
        finally:
            os.chdir(previous_cwd)
    except (OSError, RuntimeError, ValueError, StopIteration) as exc:
        try:
            os.chdir(previous_cwd)
        except OSError:
            pass
        raise HeavyAcceptanceError("heavy_partition_plan_refused") from exc
    if not partitions or len(partitions) > MAX_WORKERS:
        raise HeavyAcceptanceError("heavy_partition_plan_refused")
    flattened = tuple(item for partition in partitions for item in partition)
    expected_node_set = set(expected_nodes)
    covered_nodes: list[str] = []
    for item in flattened:
        if not item or item.startswith("-"):
            raise HeavyAcceptanceError("heavy_partition_coverage_refused")
        if "::" in item:
            if item not in expected_node_set:
                raise HeavyAcceptanceError("heavy_partition_coverage_refused")
            covered_nodes.append(item)
            continue
        if not item.endswith(".py") or item not in expected_files:
            raise HeavyAcceptanceError("heavy_partition_coverage_refused")
        covered_nodes.extend(node for node in expected_nodes if node.split("::", 1)[0] == item)
    if Counter(covered_nodes) != Counter(expected_nodes):
        raise HeavyAcceptanceError("heavy_partition_coverage_refused")
    if not all(partition for partition in partitions):
        raise HeavyAcceptanceError("heavy_partition_plan_refused")
    return partitions


def _worker_summary(
    manifest: dict[str, Any], targets: list[str], result_path: Path
) -> dict[str, Any]:
    expected = identity(
        manifest["source_sha"],
        manifest["image_digest"],
        manifest["channel"],
        manifest["operation_id"],
    )
    import pytest

    plugin = HeavyResults()
    marker = manifest.get("marker")
    if not isinstance(marker, str) or not marker:
        raise HeavyAcceptanceError("heavy_selector_unavailable")
    exit_status = int(
        pytest.main(
            pytest_arguments(marker, targets, cache_dir=str(result_path.parent / "cache")),
            plugins=[plugin],
        )
    )
    summary = {**expected, "targets": [HEAVY_TARGET], **plugin.summary(exit_status)}
    result_path.write_text(
        json.dumps(
            {
                "summary": summary,
                "nodes": sorted(plugin.nodes),
                "passed_nodes": sorted(plugin.passed),
                "failed_nodes": list(plugin.failed),
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return summary


def _read_worker_result(
    path: Path, expected: dict[str, str]
) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HeavyAcceptanceError("heavy_worker_result_missing") from exc
    if not isinstance(payload, dict):
        raise HeavyAcceptanceError("heavy_worker_result_refused")
    summary = payload.get("summary")
    nodes = payload.get("nodes")
    passed_nodes = payload.get("passed_nodes")
    failed_nodes = payload.get("failed_nodes")
    if (
        not isinstance(summary, dict)
        or not isinstance(nodes, list)
        or not isinstance(passed_nodes, list)
        or not isinstance(failed_nodes, list)
        or any(not isinstance(node, str) for node in (*nodes, *passed_nodes, *failed_nodes))
    ):
        raise HeavyAcceptanceError("heavy_worker_result_refused")
    classify(summary, expected)
    if (
        len(nodes) != summary["selected"]
        or len(set(nodes)) != len(nodes)
        or len(passed_nodes) != summary["passed"]
        or len(failed_nodes) != summary["failed"]
        or not set(passed_nodes).issubset(nodes)
        or not set(failed_nodes).issubset(nodes)
        or set(passed_nodes) & set(failed_nodes)
    ):
        raise HeavyAcceptanceError("heavy_worker_result_refused")
    if summary["passed"] + summary["failed"] + summary["skipped"] > summary["selected"]:
        raise HeavyAcceptanceError("heavy_worker_result_refused")
    return summary, payload


def _run_partitions(
    manifest: dict[str, Any],
    root: Path,
    marker: str,
    targets: tuple[str, ...],
    expected_nodes: tuple[str, ...],
    deadline: float,
) -> dict[str, Any]:
    """Run owned child processes under one shared deadline and strict aggregation."""

    partitions = _partition_targets(root, marker, targets, expected_nodes, deadline)
    work_dir = Path(tempfile.mkdtemp(prefix="heavy-acceptance-", dir="/tmp"))
    processes: list[tuple[subprocess.Popen[str], Path, Path]] = []
    try:
        manifest_path = work_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps({**manifest, "marker": marker}, sort_keys=True), encoding="utf-8"
        )
        for index, partition in enumerate(partitions):
            target_path = work_dir / f"partition-{index}.targets"
            result_path = work_dir / f"partition-{index}.json"
            log_path = work_dir / f"partition-{index}.log"
            target_path.write_text("\n".join(partition) + "\n", encoding="utf-8")
            log = log_path.open("w", encoding="utf-8")
            environment = os.environ.copy()
            existing_pythonpath = environment.get("PYTHONPATH")
            environment["PYTHONPATH"] = str(root) + (
                os.pathsep + existing_pythonpath if existing_pythonpath else ""
            )
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "app.ops.heavy_acceptance",
                    "--manifest",
                    str(manifest_path),
                    "--worker-targets-file",
                    str(target_path),
                    "--worker-result-file",
                    str(result_path),
                ],
                cwd=root,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
                env=environment,
                start_new_session=True,
            )
            log.close()
            processes.append((process, result_path, log_path))

        timed_out = False
        while any(process.poll() is None for process, _, _ in processes):
            if time.monotonic() >= deadline:
                timed_out = True
                break
            time.sleep(0.05)
        if timed_out or time.monotonic() > deadline:
            raise HeavyAcceptanceError("heavy_deadline_exceeded")
        for process, _, _ in processes:
            if process.poll() is None:
                process.wait()

        expected = identity(
            manifest["source_sha"],
            manifest["image_digest"],
            manifest["channel"],
            manifest["operation_id"],
        )
        observed_nodes: list[str] = []
        passed_nodes: list[str] = []
        failed_nodes: list[str] = []
        failures: list[str] = []
        skipped = docker_skipped = 0
        exit_status = 0
        for process, result_path, _ in processes:
            _remaining(deadline)
            summary, payload = _read_worker_result(result_path, expected)
            observed_nodes.extend(payload["nodes"])
            passed_nodes.extend(payload["passed_nodes"])
            failed_nodes.extend(payload["failed_nodes"])
            failures.extend(summary["failures"])
            skipped += summary["skipped"]
            docker_skipped += summary["docker_skipped"]
            exit_status = max(exit_status, summary["exit_status"])
            if process.returncode != 0:
                exit_status = 1
        if (
            tuple(sorted(observed_nodes)) != tuple(sorted(expected_nodes))
            or len(set(observed_nodes)) != len(observed_nodes)
            or len(set(passed_nodes)) != len(passed_nodes)
            or len(set(failed_nodes)) != len(failed_nodes)
        ):
            raise HeavyAcceptanceError("heavy_node_coverage_refused")
        report_hash = hashlib.sha256(
            json.dumps([sorted(passed_nodes), failed_nodes], separators=(",", ":")).encode()
        ).hexdigest()
        aggregate = {
            **expected,
            "targets": list(targets),
            "exit_status": 0 if exit_status == 0 else 1,
            "failures": failures[:MAX_FAILURES],
            "report_hash": report_hash,
            "selected": len(observed_nodes),
            "passed": len(set(passed_nodes)),
            "failed": len(set(failed_nodes)),
            "skipped": skipped,
            "docker_skipped": docker_skipped,
        }
        _remaining(deadline)
        classify(aggregate, expected)
        return aggregate
    finally:
        for process, _, _ in processes:
            if process.poll() is None:
                _terminate_process_group(process.pid)
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
        shutil.rmtree(work_dir, ignore_errors=False)


def run(manifest: dict[str, Any], *, root: Path | None = None) -> dict[str, Any]:
    root = Path.cwd() if root is None else root  # The container's workdir is the exact tree.
    selector = _load_selector(root)
    targets = tuple(selector.HEAVY_PR_DEFERRED_TARGETS)
    if targets != (HEAVY_TARGET,):
        raise HeavyAcceptanceError("heavy_selection_unexpected")
    marker = selector.PR_MARKER_EXPRESSION
    deadline = time.monotonic() + PROFILE_DEADLINE
    expected_nodes = _collect_nodes(root, marker, HEAVY_TARGET, deadline)
    return _run_partitions(manifest, root, marker, targets, expected_nodes, deadline)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--worker-targets-file", type=Path)
    parser.add_argument("--worker-result-file", type=Path)
    args = parser.parse_args(argv)
    try:
        manifest = json.loads(args.manifest.read_text())
        if (args.worker_targets_file is None) != (args.worker_result_file is None):
            raise HeavyAcceptanceError("heavy_worker_arguments_refused")
        if args.worker_targets_file is not None:
            targets = [
                line.strip()
                for line in args.worker_targets_file.read_text().splitlines()
                if line.strip()
            ]
            _worker_summary(manifest, targets, args.worker_result_file)
            return 0
        summary = run(manifest)
        print(RESULT_PREFIX + json.dumps(summary, sort_keys=True))
        return 0
    except HeavyAcceptanceError as exc:
        print("heavy acceptance refused: " + exc.reason, file=sys.stderr)
        print(RESULT_PREFIX + "refused")
        return 78
    except Exception as exc:
        print("heavy acceptance refused: " + type(exc).__name__, file=sys.stderr)
        print(RESULT_PREFIX + "refused")
        return 78


if __name__ == "__main__":
    raise SystemExit(main())
