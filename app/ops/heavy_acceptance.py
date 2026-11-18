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
from types import SimpleNamespace
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
    """Count v1 outcomes separately from exact per-node completion."""

    def __init__(self) -> None:
        self.nodes: set[str] = set()
        self.passed: set[str] = set()
        self.failed: list[str] = []
        self.skipped = 0
        self.docker_skipped = 0
        self.skipped_nodes: set[str] = set()
        self.phase_results: list[dict[str, Any]] = []
        self.terminal_results: list[str] = []
        self._reports: dict[str, list[Any]] = {}
        self.watchdog = False

    def pytest_collection_finish(self, session: Any) -> None:
        self.nodes = {item.nodeid for item in session.items}
        self.watchdog = (
            session.config.getoption("timeout") == TEST_TIMEOUT
            and session.config.getoption("timeout_method") == "thread"
        )

    def pytest_runtest_logreport(self, report: Any) -> None:
        self._reports.setdefault(report.nodeid, []).append(report)
        xfail = hasattr(report, "wasxfail")
        docker_skipped = (
            report.skipped and not xfail and DOCKER_SKIP_REASON in str(report.longrepr)
        )
        self.phase_results.append(
            {
                "nodeid": report.nodeid,
                "when": report.when,
                "outcome": report.outcome,
                "xfail": xfail,
                "docker_skipped": docker_skipped,
            }
        )
        # Preserve the original v1 bookkeeping, including phase overlap.
        if report.failed:
            if report.nodeid not in self.failed:
                self.failed.append(report.nodeid)
        elif report.skipped and not hasattr(report, "wasxfail"):
            self.skipped += 1
            self.skipped_nodes.add(report.nodeid)
            if DOCKER_SKIP_REASON in str(report.longrepr):
                self.docker_skipped += 1
        elif report.when == "call" and report.passed:
            self.passed.add(report.nodeid)

    def pytest_runtest_logfinish(self, nodeid: str, location: Any) -> None:
        reports = self._reports.get(nodeid, ())
        call = next((report for report in reports if report.when == "call"), None)
        if any(report.failed for report in reports):
            status = "ERROR"
        elif any(report.skipped and hasattr(report, "wasxfail") for report in reports):
            status = "XFAIL"
        elif call is not None and call.passed and hasattr(call, "wasxfail"):
            status = "XPASS"
        elif call is not None and call.passed:
            status = "PASSED"
        elif any(report.skipped for report in reports):
            status = "SKIPPED"
        else:
            status = "ERROR"
        self.terminal_results.append(f"{nodeid} {status}")

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


def _group_exists(process_group: int) -> bool:
    try:
        os.killpg(process_group, 0)
    except ProcessLookupError:
        return False
    except PermissionError as exc:
        raise HeavyAcceptanceError("heavy_cleanup_refused") from exc
    return True


def _terminate_process_group(process_group: int) -> None:
    """Attempt both owned-group signals; retain uncertain signal failures."""

    signal_error: OSError | None = None
    try:
        os.killpg(process_group, signal.SIGTERM)
    except ProcessLookupError:
        return
    except OSError as exc:
        signal_error = exc
    time.sleep(PROCESS_GROUP_GRACE_SECONDS)
    try:
        os.killpg(process_group, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except OSError as exc:
        signal_error = signal_error or exc
    if signal_error is not None:
        raise HeavyAcceptanceError("heavy_cleanup_refused") from signal_error


def _assert_process_group_absent(process_group: int) -> None:
    for _ in range(40):
        try:
            os.killpg(process_group, 0)
        except ProcessLookupError:
            return
        except PermissionError as exc:
            raise HeavyAcceptanceError("heavy_cleanup_refused") from exc
        time.sleep(0.05)
    raise HeavyAcceptanceError("heavy_cleanup_leaked")


def _cleanup_owned_process(process: subprocess.Popen[str]) -> bool:
    """Attempt every cleanup step; an unknown observation remains non-green."""

    leaked_descendant = False
    cleanup_error: HeavyAcceptanceError | None = None
    try:
        leaked_descendant = process.poll() is not None and _group_exists(process.pid)
    except (HeavyAcceptanceError, OSError):
        cleanup_error = HeavyAcceptanceError("heavy_cleanup_refused")
    try:
        _terminate_process_group(process.pid)
    except (HeavyAcceptanceError, OSError):
        cleanup_error = cleanup_error or HeavyAcceptanceError("heavy_cleanup_refused")
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        cleanup_error = cleanup_error or HeavyAcceptanceError("heavy_cleanup_refused")
        try:
            process.kill()
            process.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            cleanup_error = cleanup_error or HeavyAcceptanceError("heavy_cleanup_refused")
    except OSError:
        cleanup_error = cleanup_error or HeavyAcceptanceError("heavy_cleanup_refused")
    try:
        _assert_process_group_absent(process.pid)
    except HeavyAcceptanceError as exc:
        cleanup_error = cleanup_error or exc
    except OSError:
        cleanup_error = cleanup_error or HeavyAcceptanceError("heavy_cleanup_refused")
    if cleanup_error is not None:
        raise cleanup_error
    return leaked_descendant


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise HeavyAcceptanceError("heavy_deadline_exceeded")
    return remaining


def _collect_nodes(root: Path, marker: str, target: str, deadline: float) -> tuple[str, ...]:
    """Collect once, retaining collection ownership and leak disposition."""

    command = [sys.executable, "-m", "pytest", "--collect-only", "-q", "-m", marker, target]
    environment = os.environ.copy()
    _remaining(deadline)
    process = subprocess.Popen(
        command,
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=environment,
        start_new_session=True,
    )
    # The local process handle owns this PGID before any fallible follow-up.
    try:
        try:
            output, _ = process.communicate(timeout=_remaining(deadline))
        except subprocess.TimeoutExpired:
            raise HeavyAcceptanceError("heavy_deadline_exceeded") from None
    finally:
        active_error = sys.exc_info()[1]
        cleanup_error: HeavyAcceptanceError | None = None
        leaked_group = False
        try:
            leaked_group = _cleanup_owned_process(process)
        except HeavyAcceptanceError as exc:
            cleanup_error = exc
        if active_error is None:
            if cleanup_error is not None:
                raise cleanup_error
            if leaked_group:
                raise HeavyAcceptanceError("heavy_cleanup_leaked")
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
    _remaining(deadline)
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
    cached_scripts = {
        name: module
        for name, module in sys.modules.items()
        if name == "scripts" or name.startswith("scripts.")
    }
    cached_partition_module = sys.modules.get(spec.name)
    sys.modules.pop(spec.name, None)
    for name in cached_scripts:
        sys.modules.pop(name, None)
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
        for name in tuple(sys.modules):
            if name == "scripts" or name.startswith("scripts."):
                sys.modules.pop(name, None)
        sys.modules.update(cached_scripts)
        sys.modules.pop(spec.name, None)
        if cached_partition_module is not None:
            sys.modules[spec.name] = cached_partition_module


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
    expected_node_set = set(expected_nodes)

    def bounded_collect(requested: tuple[str, ...]) -> tuple[str, ...]:
        positional = tuple(item for item in requested if not item.startswith("-"))
        return tuple(
            node
            for node in expected_nodes
            if any(node == target or tools._strictly_covers(target, node) for target in positional)
        )

    tools._collect_parallel_nodes = bounded_collect
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
    try:
        partition_tools = _load_partition_tools(Path.cwd())
        partition_tools.verify_node_results(
            tuple(sorted(plugin.nodes)), HEAVY_TARGET, tuple(plugin.terminal_results)
        )
    except (HeavyAcceptanceError, ValueError) as exc:
        raise HeavyAcceptanceError("heavy_terminal_evidence_refused") from exc
    summary = {**expected, "targets": [HEAVY_TARGET], **plugin.summary(exit_status)}
    result_path.write_text(
        json.dumps(
            {
                "summary": summary,
                "nodes": sorted(plugin.nodes),
                "passed_nodes": sorted(plugin.passed),
                "failed_nodes": list(plugin.failed),
                "skipped_nodes": sorted(plugin.skipped_nodes),
                "phase_results": list(plugin.phase_results),
                "terminal_results": list(plugin.terminal_results),
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return summary


def _read_worker_result(
    path: Path,
    expected: dict[str, str],
    expected_nodes: tuple[str, ...],
    *,
    partition_tools: Any,
) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HeavyAcceptanceError("heavy_worker_result_missing") from exc
    if not isinstance(payload, dict) or set(payload) != {
        "summary", "nodes", "passed_nodes", "failed_nodes", "skipped_nodes",
        "phase_results", "terminal_results",
    }:
        raise HeavyAcceptanceError("heavy_worker_result_refused")
    summary = payload["summary"]
    nodes = payload["nodes"]
    phases = payload["phase_results"]
    terminal_results = payload["terminal_results"]
    if (
        not isinstance(nodes, list)
        or any(
            not isinstance(node, str) or not node or re.search(r"[\x00-\x1f]", node)
            for node in nodes
        )
        or len(set(nodes)) != len(nodes)
        or tuple(sorted(nodes)) != tuple(sorted(expected_nodes))
        or not isinstance(phases, list)
        or not isinstance(terminal_results, list)
        or len(terminal_results) != len(expected_nodes)
        or any(not isinstance(line, str) for line in terminal_results)
    ):
        raise HeavyAcceptanceError("heavy_worker_result_refused")
    # This validates the public schema, not a partition's eligibility to pass.
    # An XFAIL-only partition may have zero v1 counters beside a passing peer.
    classify(summary, expected)
    projection = HeavyResults()
    projection.nodes = set(nodes)
    # The producer checks the real watchdog before writing its payload.
    # This replay authenticates only the observed phase projection.
    projection.watchdog = True
    for phase in phases:
        if (
            not isinstance(phase, dict)
            or set(phase) != {"nodeid", "when", "outcome", "xfail", "docker_skipped"}
            or not isinstance(phase["nodeid"], str)
            or phase["nodeid"] not in projection.nodes
            or not isinstance(phase["when"], str)
            or phase["when"] not in {"setup", "call", "teardown"}
            or not isinstance(phase["outcome"], str)
            or phase["outcome"] not in {"passed", "failed", "skipped"}
            or type(phase["xfail"]) is not bool
            or type(phase["docker_skipped"]) is not bool
            or (
                phase["docker_skipped"]
                and (phase["outcome"] != "skipped" or phase["xfail"])
            )
        ):
            raise HeavyAcceptanceError("heavy_worker_result_refused")
        report = SimpleNamespace(
            nodeid=phase["nodeid"],
            when=phase["when"],
            outcome=phase["outcome"],
            passed=phase["outcome"] == "passed",
            failed=phase["outcome"] == "failed",
            skipped=phase["outcome"] == "skipped",
            longrepr=DOCKER_SKIP_REASON if phase["docker_skipped"] else "",
        )
        if phase["xfail"]:
            report.wasxfail = True
        projection.pytest_runtest_logreport(report)
    for node in nodes:
        reports = projection._reports.get(node, ())
        whens = [report.when for report in reports]
        expected_phases = (
            ["setup", "call", "teardown"]
            if reports and reports[0].passed
            else ["setup", "teardown"]
        )
        if whens != expected_phases:
            raise HeavyAcceptanceError("heavy_worker_result_refused")
    try:
        completed = partition_tools.verify_node_results(
            expected_nodes, HEAVY_TARGET, tuple(terminal_results)
        )
    except (TypeError, ValueError) as exc:
        raise HeavyAcceptanceError("heavy_worker_result_refused") from exc
    # The qualified oracle returns exact raw node identities, including spaces.
    # Do not parse its display lines or infer mutually exclusive v1 buckets.
    for node in completed:
        projection.pytest_runtest_logfinish(node, None)
    projected_summary = {
        **expected,
        "targets": [HEAVY_TARGET],
        **projection.summary(summary["exit_status"]),
    }
    if (
        summary != projected_summary
        or payload["passed_nodes"] != sorted(projection.passed)
        or payload["failed_nodes"] != projection.failed
        or payload["skipped_nodes"] != sorted(projection.skipped_nodes)
        or terminal_results != projection.terminal_results
    ):
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

    _remaining(deadline)
    partitions = _partition_targets(root, marker, targets, expected_nodes, deadline)
    _remaining(deadline)
    partition_tools = _load_partition_tools(root)
    work_dir = Path(tempfile.mkdtemp(prefix="heavy-acceptance-", dir="/tmp"))
    processes: list[tuple[subprocess.Popen[str], Path, tuple[str, ...]]] = []
    aggregate: dict[str, Any] | None = None
    try:
        manifest_path = work_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps({**manifest, "marker": marker}, sort_keys=True), encoding="utf-8"
        )
        for index, partition in enumerate(partitions):
            expected_partition_nodes = tuple(
                node
                for item in partition
                for node in expected_nodes
                if node == item or node.split("::", 1)[0] == item
            )
            target_path = work_dir / f"partition-{index}.targets"
            result_path = work_dir / f"partition-{index}.json"
            log_path = work_dir / f"partition-{index}.log"
            target_path.write_text("\n".join(partition) + "\n", encoding="utf-8")
            environment = os.environ.copy()
            existing_pythonpath = environment.get("PYTHONPATH")
            environment["PYTHONPATH"] = str(root) + (
                os.pathsep + existing_pythonpath if existing_pythonpath else ""
            )
            command = [
                sys.executable,
                "-m",
                "app.ops.heavy_acceptance",
                "--manifest",
                str(manifest_path),
                "--worker-targets-file",
                str(target_path),
                "--worker-result-file",
                str(result_path),
            ]
            with log_path.open("w", encoding="utf-8") as log:
                # File preparation and log opening may consume the envelope.
                _remaining(deadline)
                process = subprocess.Popen(
                    command,
                    cwd=root,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    text=True,
                    env=environment,
                    start_new_session=True,
                )
                # Own the group before the context manager can close the log.
                processes.append((process, result_path, expected_partition_nodes))

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
        skipped = docker_skipped = 0
        aggregate_failed = False
        skipped_nodes: list[str] = []
        terminal_results: list[str] = []
        for process, result_path, partition in processes:
            _remaining(deadline)
            summary, payload = _read_worker_result(
                result_path, expected, partition, partition_tools=partition_tools
            )
            observed_nodes.extend(payload["nodes"])
            passed_nodes.extend(payload["passed_nodes"])
            failed_nodes.extend(payload["failed_nodes"])
            skipped_nodes.extend(payload["skipped_nodes"])
            terminal_results.extend(payload["terminal_results"])
            skipped += summary["skipped"]
            docker_skipped += summary["docker_skipped"]
            if summary["exit_status"] != 0 or process.returncode != 0:
                aggregate_failed = True
        if (
            tuple(sorted(observed_nodes)) != tuple(sorted(expected_nodes))
            or len(set(observed_nodes)) != len(observed_nodes)
            or len(set(passed_nodes)) != len(passed_nodes)
            or len(set(failed_nodes)) != len(failed_nodes)
            or len(set(skipped_nodes)) != len(skipped_nodes)
            or len(terminal_results) != len(expected_nodes)
        ):
            raise HeavyAcceptanceError("heavy_node_coverage_refused")
        try:
            partition_tools.verify_node_results(
                expected_nodes, HEAVY_TARGET, tuple(terminal_results)
            )
        except (TypeError, ValueError) as exc:
            raise HeavyAcceptanceError("heavy_node_coverage_refused") from exc
        report_hash = hashlib.sha256(
            json.dumps([sorted(passed_nodes), failed_nodes], separators=(",", ":")).encode()
        ).hexdigest()
        aggregate = {
            **expected,
            "targets": list(targets),
            "exit_status": 1 if aggregate_failed else 0,
            "failures": [node[:MAX_NODEID] for node in failed_nodes[:MAX_FAILURES]],
            "report_hash": report_hash,
            "selected": len(observed_nodes),
            "passed": len(set(passed_nodes)),
            "failed": len(set(failed_nodes)),
            "skipped": skipped,
            "docker_skipped": docker_skipped,
        }
    finally:
        cleanup_error: HeavyAcceptanceError | None = None
        leaked_group = False
        active_error = sys.exc_info()[1]
        for process, _, _ in processes:
            try:
                leaked_group = _cleanup_owned_process(process) or leaked_group
            except HeavyAcceptanceError as exc:
                cleanup_error = cleanup_error or exc
        shutil.rmtree(work_dir, ignore_errors=False)
        if cleanup_error is not None and active_error is None:
            raise cleanup_error
        if leaked_group and active_error is None:
            raise HeavyAcceptanceError("heavy_cleanup_leaked")
    if aggregate is None:
        raise HeavyAcceptanceError("heavy_worker_result_refused")
    # Cleanup is part of the single acceptance envelope.  A result that was
    # green before slow cleanup is not green after the shared deadline.
    _remaining(deadline)
    classify(aggregate, expected)
    return aggregate


def _require_reaping_parent() -> None:
    """Refuse a direct PID1 parent that cannot provide orphan reaping."""

    if os.getpid() == 1:
        raise HeavyAcceptanceError("heavy_pid1_unqualified")


def run(manifest: dict[str, Any], *, root: Path | None = None) -> dict[str, Any]:
    root = Path.cwd() if root is None else root  # The container's workdir is the exact tree.
    _require_reaping_parent()
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
