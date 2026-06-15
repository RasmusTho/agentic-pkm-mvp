"""Tests for ops.benchmarks.run_benchmark — the PKM runtime benchmark runner.

TDD: these tests define the contract before implementation.
"""

from __future__ import annotations

import argparse
import importlib.util
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

REPO_ROOT = Path(__file__).resolve().parents[2]
SEED_DIR = REPO_ROOT / "docs" / "examples" / "vault_test_seed"

BENCHMARK_ENV_KEYS = (
    "LLM_PROVIDER",
    "LLM_FORCE_PROVIDER",
    "EMBED_PROFILE",
    "LLM_MOCK_RESPONSE",
    "STORE_BACKEND",
    "INGEST_STATUS_PATH",
)


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


def _benchmark_args(
    seed_dir: Path,
    *,
    storage_profile: str = "memory",
    model_profile: str = "mock",
) -> argparse.Namespace:
    return argparse.Namespace(
        storage_profile=storage_profile,
        runtime_placement="local",
        model_profile=model_profile,
        seed_dir=str(seed_dir),
    )


def _seed_dir(tmp_path: Path) -> Path:
    seed_dir = tmp_path / "seed"
    seed_dir.mkdir()
    (seed_dir / "note.md").write_text("# Benchmark seed\n\nBody.\n", encoding="utf-8")
    return seed_dir


def _load_run_benchmark_module():
    spec = importlib.util.spec_from_file_location(
        "benchmark_runner_under_test",
        REPO_ROOT / "ops" / "benchmarks" / "run_benchmark.py",
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


class TestBenchmarkEnvironmentScoping:
    """Benchmark profile env overrides stay scoped to each in-process run."""

    def test_mock_profile_env_is_available_during_run_and_restored(
        self,
        monkeypatch,
        tmp_path: Path,
    ) -> None:
        run_benchmark = _load_run_benchmark_module()

        for key in BENCHMARK_ENV_KEYS:
            monkeypatch.delenv(key, raising=False)

        snapshots: list[dict[str, str | None]] = []

        def _capture_env(*_args, **_kwargs):
            snapshots.append({key: os.environ.get(key) for key in BENCHMARK_ENV_KEYS})
            return [], []

        monkeypatch.setattr(run_benchmark, "_bench_ingest", _capture_env)
        monkeypatch.setattr(run_benchmark, "_bench_index_write", _capture_env)
        monkeypatch.setattr(run_benchmark, "_bench_ask_query", _capture_env)

        run_benchmark.run(_benchmark_args(_seed_dir(tmp_path), model_profile="mock"))

        assert snapshots
        first_stage_env = snapshots[0]
        assert first_stage_env["LLM_PROVIDER"] == "mock"
        assert first_stage_env["LLM_FORCE_PROVIDER"] == "mock"
        assert first_stage_env["EMBED_PROFILE"] == "deterministic"
        assert first_stage_env["LLM_MOCK_RESPONSE"] == (
            '{"type":"note","trust":"own","tags":["topic/test"],"confidence":0.95}'
        )
        assert first_stage_env["STORE_BACKEND"] == "memory"
        assert first_stage_env["INGEST_STATUS_PATH"]

        for key in BENCHMARK_ENV_KEYS:
            assert os.environ.get(key) is None

    def test_sequential_local_profile_does_not_inherit_mock_provider_env(
        self,
        monkeypatch,
        tmp_path: Path,
    ) -> None:
        run_benchmark = _load_run_benchmark_module()

        seed_dir = _seed_dir(tmp_path)
        for key in BENCHMARK_ENV_KEYS:
            monkeypatch.delenv(key, raising=False)

        def _noop_stage(*_args, **_kwargs):
            return [], []

        monkeypatch.setattr(run_benchmark, "_bench_ingest", _noop_stage)
        monkeypatch.setattr(run_benchmark, "_bench_index_write", _noop_stage)
        monkeypatch.setattr(run_benchmark, "_bench_ask_query", _noop_stage)

        run_benchmark.run(_benchmark_args(seed_dir, model_profile="mock"))

        assert os.environ.get("LLM_PROVIDER") is None
        assert os.environ.get("LLM_FORCE_PROVIDER") is None
        assert os.environ.get("EMBED_PROFILE") is None
        assert os.environ.get("LLM_MOCK_RESPONSE") is None
        assert os.environ.get("STORE_BACKEND") is None
        assert os.environ.get("INGEST_STATUS_PATH") is None

        monkeypatch.setenv("LLM_PROVIDER", "ollama")
        monkeypatch.delenv("LLM_FORCE_PROVIDER", raising=False)
        monkeypatch.setenv("EMBED_PROFILE", "local")
        monkeypatch.delenv("LLM_MOCK_RESPONSE", raising=False)
        monkeypatch.setenv("STORE_BACKEND", "pg")
        monkeypatch.setenv("INGEST_STATUS_PATH", str(tmp_path / "caller-status.json"))

        local_run_snapshots: list[dict[str, str | None]] = []

        def _capture_local_env(*_args, **_kwargs):
            local_run_snapshots.append({key: os.environ.get(key) for key in BENCHMARK_ENV_KEYS})
            return [], []

        monkeypatch.setattr(run_benchmark, "_bench_ingest", _capture_local_env)
        monkeypatch.setattr(run_benchmark, "_bench_index_write", _capture_local_env)
        monkeypatch.setattr(run_benchmark, "_bench_ask_query", _capture_local_env)

        run_benchmark.run(
            _benchmark_args(seed_dir, storage_profile="pg", model_profile="local")
        )

        assert local_run_snapshots
        local_stage_env = local_run_snapshots[0]
        assert local_stage_env["LLM_PROVIDER"] == "ollama"
        assert local_stage_env["LLM_FORCE_PROVIDER"] is None
        assert local_stage_env["EMBED_PROFILE"] == "local"
        assert local_stage_env["LLM_MOCK_RESPONSE"] is None
        assert local_stage_env["STORE_BACKEND"] == "pg"
        assert os.environ["LLM_PROVIDER"] == "ollama"
        assert os.environ.get("LLM_FORCE_PROVIDER") is None
        assert os.environ["EMBED_PROFILE"] == "local"
        assert os.environ.get("LLM_MOCK_RESPONSE") is None
        assert os.environ["STORE_BACKEND"] == "pg"
        assert os.environ["INGEST_STATUS_PATH"] == str(tmp_path / "caller-status.json")
