"""Tests for ops.benchmarks.run_benchmark — the PKM runtime benchmark runner.

TDD: these tests define the contract before implementation.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict

# ---------------------------------------------------------------------------
# Metric name contract (must match docs/plans/BENCHMARK_PROTOCOL.md)
# ---------------------------------------------------------------------------

PROTOCOL_METRIC_NAMES = {
    "ingest_full_ms",
    "index_write_ms",
    "ask_query_ms",
    # Phase-2 metrics (runtime instrumentation) — not yet captured by runner
    # but included in the protocol spec for completeness:
    # "watcher_tick_ms", "outbox_write_ms", "worker_pickup_ms",
    # "panel_intent_ms", "promote_done_ms",
}

PHASE1_REQUIRED_METRICS = {"ingest_full_ms", "index_write_ms", "ask_query_ms"}

SEED_DIR = Path(__file__).resolve().parents[2] / "docs" / "examples" / "vault_test_seed"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_benchmark_module(*extra_args: str, env_override: dict | None = None) -> Dict[str, Any]:
    """Run the benchmark as a subprocess and return parsed JSON."""
    env = {**os.environ, "STORE_BACKEND": "memory", "LLM_PROVIDER": "mock"}
    if env_override:
        env.update(env_override)

    cmd = [
        sys.executable,
        "-m",
        "ops.benchmarks.run_benchmark",
        "--storage-profile",
        "memory",
        "--model-profile",
        "mock",
        "--seed-dir",
        str(SEED_DIR),
    ] + list(extra_args)

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=env,
        cwd=str(Path(__file__).resolve().parents[2]),
        timeout=300,
    )
    assert result.returncode == 0, f"Runner failed:\nstdout={result.stdout}\nstderr={result.stderr}"
    return json.loads(result.stdout)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBenchmarkOutputStructure:
    """The runner must emit valid JSON matching the protocol spec."""

    def test_top_level_keys(self) -> None:
        data = _run_benchmark_module()
        assert "run_id" in data
        assert "timestamp" in data
        assert "scenario" in data
        assert "metrics" in data
        assert "warnings" in data

    def test_scenario_tags(self) -> None:
        data = _run_benchmark_module()
        scenario = data["scenario"]
        assert scenario["storage_profile"] == "memory"
        assert scenario["runtime_placement"] == "local"
        assert scenario["model_profile"] == "mock"

    def test_metrics_are_list(self) -> None:
        data = _run_benchmark_module()
        assert isinstance(data["metrics"], list)
        assert len(data["metrics"]) > 0

    def test_each_metric_has_required_fields(self) -> None:
        data = _run_benchmark_module()
        for m in data["metrics"]:
            assert "name" in m, f"metric missing 'name': {m}"
            assert "value_ms" in m, f"metric missing 'value_ms': {m}"
            assert "tags" in m, f"metric missing 'tags': {m}"
            assert "timestamp" in m, f"metric missing 'timestamp': {m}"
            assert isinstance(m["value_ms"], (int, float))
            assert m["value_ms"] >= 0

    def test_warnings_is_list(self) -> None:
        data = _run_benchmark_module()
        assert isinstance(data["warnings"], list)


class TestMetricNames:
    """Metric names must match the protocol spec."""

    def test_phase1_metrics_present(self) -> None:
        data = _run_benchmark_module()
        emitted_names = {m["name"] for m in data["metrics"]}
        for required in PHASE1_REQUIRED_METRICS:
            assert required in emitted_names, f"Missing required metric: {required}"

    def test_no_unknown_metric_names(self) -> None:
        data = _run_benchmark_module()
        emitted_names = {m["name"] for m in data["metrics"]}
        # All emitted names must be in the protocol set
        unknown = emitted_names - PROTOCOL_METRIC_NAMES
        assert not unknown, f"Unknown metric names not in protocol: {unknown}"


class TestMetricTags:
    """Each metric carries the scenario tags."""

    def test_tags_include_scenario_triple(self) -> None:
        data = _run_benchmark_module()
        for m in data["metrics"]:
            tags = m["tags"]
            assert "storage_profile" in tags
            assert "runtime_placement" in tags
            assert "model_profile" in tags


class TestGracefulDegradation:
    """Runner must not crash when services are unavailable."""

    def test_missing_seed_dir_exits_nonzero(self) -> None:
        """A completely missing seed dir is a user error, not a graceful skip."""
        cmd = [
            sys.executable,
            "-m",
            "ops.benchmarks.run_benchmark",
            "--seed-dir",
            "/nonexistent/path",
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).resolve().parents[2]),
            timeout=30,
        )
        assert result.returncode != 0

    def test_empty_seed_dir_produces_warnings(self, tmp_path: Path) -> None:
        """An empty seed dir should produce output with warnings, not crash."""
        cmd = [
            sys.executable,
            "-m",
            "ops.benchmarks.run_benchmark",
            "--storage-profile",
            "memory",
            "--model-profile",
            "mock",
            "--seed-dir",
            str(tmp_path),
        ]
        env = {**os.environ, "STORE_BACKEND": "memory", "LLM_PROVIDER": "mock"}
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env=env,
            cwd=str(Path(__file__).resolve().parents[2]),
            timeout=30,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        # Should still have valid structure, just empty/warning metrics
        assert "warnings" in data
        assert len(data["warnings"]) > 0 or len(data["metrics"]) == 0
