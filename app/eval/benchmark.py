"""Benchmark protocol – structured measurement framework.

Lets you define benchmark scenarios, run them with reproducible config,
compare against baselines, and emit CI-compatible reports.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


# ── Models ──────────────────────────────────────────────────────────────


class MetricValue(BaseModel):
    """Single metric measurement."""

    name: str
    value: float
    unit: str = ""
    higher_is_better: bool = True


class BenchmarkResult(BaseModel):
    """Result of a single benchmark run."""

    scenario: str
    metrics: list[MetricValue]
    timestamp: datetime
    config: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    duration_ms: float


class BaselineComparison(BaseModel):
    """Comparison of a result metric against a baseline value."""

    scenario: str
    metric: str
    baseline_value: float
    current_value: float
    delta: float
    delta_pct: float
    regression: bool
    threshold: float


# ── Suite ───────────────────────────────────────────────────────────────


class BenchmarkSuite:
    """Collection of benchmark scenarios with baseline comparison."""

    def __init__(self, name: str, *, baseline_path: Path | None = None) -> None:
        self.name = name
        self._scenarios: dict[str, _ScenarioEntry] = {}
        self._baseline: dict[str, Any] | None = None
        if baseline_path is not None:
            self.load_baseline(baseline_path)

    # -- registration ----------------------------------------------------

    def scenario(
        self, name: str, *, tags: list[str] | None = None
    ) -> Callable[[Callable[..., list[MetricValue]]], Callable[..., BenchmarkResult]]:
        """Decorator that registers a benchmark scenario function.

        The decorated function must return ``list[MetricValue]``.
        After decoration it returns a ``BenchmarkResult`` (with timing).
        """

        def decorator(
            fn: Callable[..., list[MetricValue]],
        ) -> Callable[..., BenchmarkResult]:
            @wraps(fn)
            def wrapper(*, config: dict[str, Any] | None = None) -> BenchmarkResult:
                cfg = config or {}
                t0 = time.perf_counter()
                metrics = fn(config=cfg)
                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                return BenchmarkResult(
                    scenario=name,
                    metrics=metrics,
                    timestamp=datetime.now(timezone.utc),
                    config=cfg,
                    tags=tags or [],
                    duration_ms=elapsed_ms,
                )

            self._scenarios[name] = _ScenarioEntry(
                name=name, fn=wrapper, tags=tags or []
            )
            return wrapper

        return decorator

    # -- execution -------------------------------------------------------

    def run(
        self,
        scenarios: list[str] | None = None,
        *,
        config: dict[str, Any] | None = None,
    ) -> list[BenchmarkResult]:
        """Run selected (or all) scenarios and return results."""
        names = scenarios if scenarios is not None else list(self._scenarios)
        results: list[BenchmarkResult] = []
        for name in names:
            entry = self._scenarios.get(name)
            if entry is None:
                raise KeyError(f"Unknown scenario: {name!r}")
            result = entry.fn(config=config)
            results.append(result)
        return results

    # -- baseline persistence --------------------------------------------

    def save_baseline(self, results: list[BenchmarkResult], path: Path) -> None:
        """Persist results as a JSON baseline file."""
        data: dict[str, Any] = {}
        for r in results:
            data[r.scenario] = {m.name: m.model_dump() for m in r.metrics}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def load_baseline(self, path: Path) -> None:
        """Load a previously saved baseline."""
        self._baseline = json.loads(path.read_text(encoding="utf-8"))

    # -- comparison ------------------------------------------------------

    def compare(
        self, results: list[BenchmarkResult], *, threshold: float = 0.05
    ) -> list[BaselineComparison]:
        """Compare *results* against the loaded baseline.

        A metric is flagged as a regression when it worsens by more than
        *threshold* (expressed as a fraction, e.g. 0.05 = 5 %).
        """
        if self._baseline is None:
            raise RuntimeError("No baseline loaded – call load_baseline() first")

        comparisons: list[BaselineComparison] = []
        for r in results:
            scenario_bl = self._baseline.get(r.scenario, {})
            for m in r.metrics:
                bl_entry = scenario_bl.get(m.name)
                if bl_entry is None:
                    continue
                bl_value = bl_entry["value"]
                delta = m.value - bl_value
                delta_pct = delta / bl_value if bl_value != 0 else 0.0
                # Regression: metric moved in the *bad* direction beyond threshold.
                if m.higher_is_better:
                    regression = delta_pct < -threshold
                else:
                    regression = delta_pct > threshold
                comparisons.append(
                    BaselineComparison(
                        scenario=r.scenario,
                        metric=m.name,
                        baseline_value=bl_value,
                        current_value=m.value,
                        delta=delta,
                        delta_pct=delta_pct,
                        regression=regression,
                        threshold=threshold,
                    )
                )
        return comparisons

    # -- reporting -------------------------------------------------------

    def report(
        self,
        results: list[BenchmarkResult],
        comparisons: list[BaselineComparison] | None = None,
    ) -> str:
        """Human-readable benchmark report."""
        lines: list[str] = [f"Benchmark Suite: {self.name}", "=" * 60]
        for r in results:
            lines.append(f"\nScenario: {r.scenario}")
            lines.append(f"  Duration: {r.duration_ms:.1f} ms")
            if r.tags:
                lines.append(f"  Tags: {', '.join(r.tags)}")
            for m in r.metrics:
                unit_str = f" {m.unit}" if m.unit else ""
                lines.append(f"  {m.name}: {m.value:.4f}{unit_str}")

        if comparisons:
            lines.append("\n" + "-" * 60)
            lines.append("Baseline Comparisons")
            lines.append("-" * 60)
            for c in comparisons:
                flag = " ** REGRESSION **" if c.regression else ""
                lines.append(
                    f"  {c.scenario}/{c.metric}: "
                    f"{c.baseline_value:.4f} -> {c.current_value:.4f} "
                    f"({c.delta_pct:+.1%}){flag}"
                )

        return "\n".join(lines)

    def ci_summary(self, comparisons: list[BaselineComparison]) -> str:
        """CI-compatible summary line.

        Format: ``CI SUMMARY GATES ok=<bool>``
        """
        ok = not any(c.regression for c in comparisons)
        return f"CI SUMMARY GATES ok={str(ok).lower()}"


# ── internal helpers ────────────────────────────────────────────────────


class _ScenarioEntry:
    __slots__ = ("name", "fn", "tags")

    def __init__(
        self,
        name: str,
        fn: Callable[..., BenchmarkResult],
        tags: list[str],
    ) -> None:
        self.name = name
        self.fn = fn
        self.tags = tags


__all__ = [
    "MetricValue",
    "BenchmarkResult",
    "BaselineComparison",
    "BenchmarkSuite",
]
