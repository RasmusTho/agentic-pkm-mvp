"""Tests for app.eval.benchmark – benchmark protocol framework."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from app.eval.benchmark import (
    BaselineComparison,
    BenchmarkResult,
    BenchmarkSuite,
    MetricValue,
)

pytestmark = pytest.mark.not_pg


# ── helpers ─────────────────────────────────────────────────────────────


def _make_suite(name: str = "test") -> BenchmarkSuite:
    return BenchmarkSuite(name=name)


def _register_dummy(suite: BenchmarkSuite, name: str = "dummy", *, value: float = 0.9):
    """Register a trivial scenario that returns a single metric."""

    @suite.scenario(name)
    def _fn(*, config: dict | None = None):
        return [MetricValue(name="score", value=value)]


# ── scenario registration & execution ──────────────────────────────────


class TestScenarioRegistration:
    def test_register_and_list(self):
        suite = _make_suite()
        _register_dummy(suite, "alpha")
        _register_dummy(suite, "beta")
        assert set(suite._scenarios) == {"alpha", "beta"}

    def test_run_all(self):
        suite = _make_suite()
        _register_dummy(suite, "a", value=1.0)
        _register_dummy(suite, "b", value=2.0)
        results = suite.run()
        assert len(results) == 2
        names = {r.scenario for r in results}
        assert names == {"a", "b"}

    def test_run_selective(self):
        suite = _make_suite()
        _register_dummy(suite, "a")
        _register_dummy(suite, "b")
        results = suite.run(["b"])
        assert len(results) == 1
        assert results[0].scenario == "b"

    def test_run_unknown_scenario_raises(self):
        suite = _make_suite()
        with pytest.raises(KeyError, match="nope"):
            suite.run(["nope"])

    def test_scenario_tags_propagated(self):
        suite = _make_suite()

        @suite.scenario("tagged", tags=["retrieval", "slow"])
        def _fn(*, config: dict | None = None):
            return [MetricValue(name="x", value=1.0)]

        results = suite.run(["tagged"])
        assert results[0].tags == ["retrieval", "slow"]


# ── metric collection & timing ─────────────────────────────────────────


class TestMetricsAndTiming:
    def test_metrics_collected(self):
        suite = _make_suite()

        @suite.scenario("multi")
        def _fn(*, config: dict | None = None):
            return [
                MetricValue(name="precision", value=0.85, unit="%"),
                MetricValue(name="latency", value=42.0, unit="ms", higher_is_better=False),
            ]

        [result] = suite.run(["multi"])
        assert len(result.metrics) == 2
        assert result.metrics[0].name == "precision"
        assert result.metrics[1].higher_is_better is False

    def test_duration_positive(self):
        suite = _make_suite()
        _register_dummy(suite)
        [result] = suite.run()
        assert result.duration_ms >= 0.0

    def test_timestamp_present(self):
        suite = _make_suite()
        _register_dummy(suite)
        [result] = suite.run()
        assert result.timestamp is not None

    def test_config_passed_through(self):
        suite = _make_suite()

        @suite.scenario("cfg")
        def _fn(*, config: dict | None = None):
            k = (config or {}).get("k", 5)
            return [MetricValue(name="k_used", value=float(k))]

        [result] = suite.run(["cfg"], config={"k": 10})
        assert result.config == {"k": 10}
        assert result.metrics[0].value == 10.0


# ── baseline save / load round-trip ────────────────────────────────────


class TestBaselinePersistence:
    def test_save_and_load(self, tmp_path: Path):
        suite = _make_suite()
        _register_dummy(suite, "s1", value=0.75)
        results = suite.run()

        bl_path = tmp_path / "baseline.json"
        suite.save_baseline(results, bl_path)
        assert bl_path.exists()

        suite2 = _make_suite()
        suite2.load_baseline(bl_path)
        assert suite2._baseline is not None
        assert "s1" in suite2._baseline
        assert suite2._baseline["s1"]["score"]["value"] == 0.75

    def test_round_trip_json_valid(self, tmp_path: Path):
        suite = _make_suite()
        _register_dummy(suite, "x", value=0.5)
        results = suite.run()
        bl_path = tmp_path / "bl.json"
        suite.save_baseline(results, bl_path)
        data = json.loads(bl_path.read_text())
        assert isinstance(data, dict)

    def test_load_via_constructor(self, tmp_path: Path):
        bl_path = tmp_path / "bl.json"
        bl_path.write_text(json.dumps({"sc": {"m": {"name": "m", "value": 1.0}}}))
        suite = BenchmarkSuite("t", baseline_path=bl_path)
        assert suite._baseline is not None


# ── comparison / regression detection ──────────────────────────────────


class TestComparison:
    def _suite_with_baseline(self, tmp_path: Path, baseline_value: float = 0.9):
        suite = _make_suite()
        _register_dummy(suite, "s", value=baseline_value)
        bl_path = tmp_path / "bl.json"
        suite.save_baseline(suite.run(), bl_path)
        suite.load_baseline(bl_path)
        return suite

    def test_no_regression_within_threshold(self, tmp_path: Path):
        suite = self._suite_with_baseline(tmp_path, 0.9)
        # Current value only slightly lower: 0.9 -> 0.87 = -3.3%, within 5%
        result = BenchmarkResult(
            scenario="s",
            metrics=[MetricValue(name="score", value=0.87)],
            timestamp=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
            duration_ms=1.0,
        )
        comparisons = suite.compare([result])
        assert len(comparisons) == 1
        assert comparisons[0].regression is False

    def test_regression_beyond_threshold(self, tmp_path: Path):
        suite = self._suite_with_baseline(tmp_path, 0.9)
        # 0.9 -> 0.8 = -11%, beyond 5%
        result = BenchmarkResult(
            scenario="s",
            metrics=[MetricValue(name="score", value=0.8)],
            timestamp=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
            duration_ms=1.0,
        )
        comparisons = suite.compare([result])
        assert comparisons[0].regression is True

    def test_improvement_not_flagged(self, tmp_path: Path):
        suite = self._suite_with_baseline(tmp_path, 0.9)
        result = BenchmarkResult(
            scenario="s",
            metrics=[MetricValue(name="score", value=0.99)],
            timestamp=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
            duration_ms=1.0,
        )
        comparisons = suite.compare([result])
        assert comparisons[0].regression is False
        assert comparisons[0].delta > 0

    def test_lower_is_better_regression(self, tmp_path: Path):
        """For lower-is-better metrics, an *increase* beyond threshold is regression."""
        suite = _make_suite()

        @suite.scenario("lat")
        def _fn(*, config: dict | None = None):
            return [MetricValue(name="latency", value=100.0, higher_is_better=False)]

        bl_path = tmp_path / "bl.json"
        suite.save_baseline(suite.run(), bl_path)
        suite.load_baseline(bl_path)

        result = BenchmarkResult(
            scenario="lat",
            metrics=[MetricValue(name="latency", value=120.0, higher_is_better=False)],
            timestamp=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
            duration_ms=1.0,
        )
        comparisons = suite.compare([result])
        assert comparisons[0].regression is True

    def test_custom_threshold(self, tmp_path: Path):
        suite = self._suite_with_baseline(tmp_path, 0.9)
        # -3.3% drop – regression at 1% threshold, not at 5%
        result = BenchmarkResult(
            scenario="s",
            metrics=[MetricValue(name="score", value=0.87)],
            timestamp=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
            duration_ms=1.0,
        )
        assert suite.compare([result], threshold=0.01)[0].regression is True
        assert suite.compare([result], threshold=0.05)[0].regression is False

    def test_compare_without_baseline_raises(self):
        suite = _make_suite()
        with pytest.raises(RuntimeError, match="No baseline"):
            suite.compare([])

    def test_delta_pct_values(self, tmp_path: Path):
        suite = self._suite_with_baseline(tmp_path, 1.0)
        result = BenchmarkResult(
            scenario="s",
            metrics=[MetricValue(name="score", value=0.9)],
            timestamp=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
            duration_ms=1.0,
        )
        [c] = suite.compare([result])
        assert math.isclose(c.delta, -0.1, abs_tol=1e-9)
        assert math.isclose(c.delta_pct, -0.1, abs_tol=1e-9)


# ── CI summary ─────────────────────────────────────────────────────────


class TestCISummary:
    def test_ok_when_no_regressions(self):
        suite = _make_suite()
        comparisons = [
            BaselineComparison(
                scenario="s", metric="m",
                baseline_value=1.0, current_value=0.96,
                delta=-0.04, delta_pct=-0.04,
                regression=False, threshold=0.05,
            ),
        ]
        assert suite.ci_summary(comparisons) == "CI SUMMARY GATES ok=true"

    def test_fail_when_regression(self):
        suite = _make_suite()
        comparisons = [
            BaselineComparison(
                scenario="s", metric="m",
                baseline_value=1.0, current_value=0.8,
                delta=-0.2, delta_pct=-0.2,
                regression=True, threshold=0.05,
            ),
        ]
        assert suite.ci_summary(comparisons) == "CI SUMMARY GATES ok=false"

    def test_empty_comparisons_ok(self):
        suite = _make_suite()
        assert suite.ci_summary([]) == "CI SUMMARY GATES ok=true"


# ── report generation ──────────────────────────────────────────────────


class TestReport:
    def test_report_contains_scenario_names(self):
        suite = _make_suite("my-bench")
        _register_dummy(suite, "alpha", value=0.95)
        results = suite.run()
        report = suite.report(results)
        assert "my-bench" in report
        assert "alpha" in report
        assert "0.9500" in report

    def test_report_with_comparisons(self):
        suite = _make_suite()
        _register_dummy(suite)
        results = suite.run()
        comparisons = [
            BaselineComparison(
                scenario="dummy", metric="score",
                baseline_value=1.0, current_value=0.9,
                delta=-0.1, delta_pct=-0.1,
                regression=True, threshold=0.05,
            ),
        ]
        report = suite.report(results, comparisons)
        assert "REGRESSION" in report
        assert "Baseline" in report


# ── error handling ─────────────────────────────────────────────────────


class TestErrorHandling:
    def test_scenario_exception_propagates(self):
        suite = _make_suite()

        @suite.scenario("boom")
        def _fn(*, config: dict | None = None):
            raise ValueError("intentional")

        with pytest.raises(ValueError, match="intentional"):
            suite.run(["boom"])

    def test_missing_baseline_metric_skipped(self, tmp_path: Path):
        """If a metric in the result isn't in the baseline, skip it."""
        bl_path = tmp_path / "bl.json"
        bl_path.write_text(json.dumps({"s": {"old_metric": {"name": "old_metric", "value": 1.0}}}))
        suite = _make_suite()
        suite.load_baseline(bl_path)

        result = BenchmarkResult(
            scenario="s",
            metrics=[MetricValue(name="new_metric", value=0.5)],
            timestamp=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
            duration_ms=1.0,
        )
        comparisons = suite.compare([result])
        assert comparisons == []

    def test_zero_baseline_lower_is_better_flags_regression(self, tmp_path: Path):
        """A lower-is-better metric going from 0 to >0 must flag regression."""
        bl_path = tmp_path / "bl.json"
        bl_path.write_text(json.dumps({
            "s": {"latency": {"name": "latency", "value": 0.0, "higher_is_better": False}}
        }))
        suite = _make_suite()
        suite.load_baseline(bl_path)

        result = BenchmarkResult(
            scenario="s",
            metrics=[MetricValue(name="latency", value=5.0, higher_is_better=False)],
            timestamp=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
            duration_ms=1.0,
        )
        comparisons = suite.compare([result])
        assert len(comparisons) == 1
        assert comparisons[0].regression is True
        assert math.isinf(comparisons[0].delta_pct)

    def test_zero_baseline_higher_is_better_no_regression_on_increase(self, tmp_path: Path):
        """A higher-is-better metric going from 0 to >0 is not a regression."""
        bl_path = tmp_path / "bl.json"
        bl_path.write_text(json.dumps({
            "s": {"accuracy": {"name": "accuracy", "value": 0.0, "higher_is_better": True}}
        }))
        suite = _make_suite()
        suite.load_baseline(bl_path)

        result = BenchmarkResult(
            scenario="s",
            metrics=[MetricValue(name="accuracy", value=0.8, higher_is_better=True)],
            timestamp=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
            duration_ms=1.0,
        )
        comparisons = suite.compare([result])
        assert len(comparisons) == 1
        assert comparisons[0].regression is False


class TestRegressionGateFailsLoud:
    """#2320: `app.eval.run`'s production call site must fail loud (non-zero
    exit / regression=True) when a sliced golden-set metric drops below its
    configured threshold, exercising the real CLI entrypoint, not just the
    BenchmarkSuite.compare() guard in isolation."""

    def test_regression_gate_fails_loud(self):
        import copy

        from app.eval import run as eval_run

        thresholds = eval_run.load_thresholds()
        # Force every bucket floor above 1.0 - an unreachable regression
        # injection - and confirm the production entrypoint (build_scorecard,
        # the same function app.eval.run.main() calls) reports the failure
        # and would drive a non-zero process exit code.
        impossible = copy.deepcopy(thresholds)
        for bucket in ("aggregate", "per_language", "memory_recall"):
            for metric in impossible.get(bucket, {}):
                impossible[bucket][metric] = 1.5

        scorecard = eval_run.build_scorecard(thresholds=impossible)

        assert scorecard["regression"] is True
        assert scorecard["failures"]
        exit_code = 1 if scorecard["regression"] else 0
        assert exit_code != 0

        # A clean pass on real thresholds must not regress.
        clean_scorecard = eval_run.build_scorecard(thresholds=thresholds)
        assert clean_scorecard["regression"] is False
