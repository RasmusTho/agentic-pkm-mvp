"""Runtime driver for the Heimdal capture adapter (#3094, follow-up to A6 #3025).

`app.heimdal.capture_adapter.run_watch_cycle` is a scan-once function with no
built-in schedule. These tests cover the loop that drives it:

- ``test_run_forever_calls_run_watch_cycle_each_tick`` -- the loop calls
  ``run_watch_cycle`` against the configured watch dir on every tick, and
  sleeps between ticks (not after the last one).
- ``test_runtime_survives_tick_exception`` -- a tick that raises does not
  stop the next tick from running.

Plus config resolution coverage (``HEIMDAL_CAPTURE_WATCH_DIR`` is required;
``HEIMDAL_CAPTURE_INTERVAL_SECONDS`` is optional with a default).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.heimdal import capture_runtime
from app.heimdal.capture_adapter import WatchCycleResult
from app.heimdal.capture_runtime import (
    DEFAULT_INTERVAL_SECONDS,
    CaptureRuntimeConfig,
    CaptureRuntimeConfigError,
    resolve_config_for_supervised_run,
    run_forever,
)

pytestmark = pytest.mark.not_pg


def test_from_env_requires_watch_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(capture_runtime.WATCH_DIR_ENV, raising=False)
    with pytest.raises(CaptureRuntimeConfigError):
        CaptureRuntimeConfig.from_env()


def test_from_env_reads_watch_dir_and_interval(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(capture_runtime.WATCH_DIR_ENV, str(tmp_path))
    monkeypatch.setenv(capture_runtime.INTERVAL_ENV, "5")
    cfg = CaptureRuntimeConfig.from_env()
    assert cfg.watch_dir == tmp_path
    assert cfg.interval_seconds == 5.0


def test_from_env_defaults_interval(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(capture_runtime.WATCH_DIR_ENV, str(tmp_path))
    monkeypatch.delenv(capture_runtime.INTERVAL_ENV, raising=False)
    cfg = CaptureRuntimeConfig.from_env()
    assert cfg.interval_seconds == DEFAULT_INTERVAL_SECONDS


def test_from_env_rejects_non_numeric_interval(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(capture_runtime.WATCH_DIR_ENV, str(tmp_path))
    monkeypatch.setenv(capture_runtime.INTERVAL_ENV, "not-a-number")
    with pytest.raises(CaptureRuntimeConfigError):
        CaptureRuntimeConfig.from_env()


def test_run_forever_calls_run_watch_cycle_each_tick(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[Path] = []

    def fake_run_watch_cycle(watch_dir, *, sensor=None, scope="", key=None):
        calls.append(watch_dir)
        return WatchCycleResult(admitted=[], refused=[])

    monkeypatch.setattr(capture_runtime, "run_watch_cycle", fake_run_watch_cycle)
    cfg = CaptureRuntimeConfig(watch_dir=tmp_path, interval_seconds=7.0)

    sleeps: list[float] = []
    ticks = run_forever(cfg, max_ticks=3, sleep=sleeps.append)

    assert ticks == 3
    assert calls == [tmp_path, tmp_path, tmp_path]
    # Sleeps between ticks, not after the last one.
    assert sleeps == [7.0, 7.0]


def test_runtime_survives_tick_exception(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    call_count = {"n": 0}

    def flaky_run_watch_cycle(watch_dir, *, sensor=None, scope="", key=None):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise OSError("transient iCloud sync error")
        return WatchCycleResult(admitted=[], refused=[])

    monkeypatch.setattr(capture_runtime, "run_watch_cycle", flaky_run_watch_cycle)
    cfg = CaptureRuntimeConfig(watch_dir=tmp_path, interval_seconds=0.0)

    ticks = run_forever(cfg, max_ticks=2, sleep=lambda _seconds: None)

    assert ticks == 2
    assert call_count["n"] == 2


def test_resolve_config_for_supervised_run_returns_immediately_when_valid(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(capture_runtime.WATCH_DIR_ENV, str(tmp_path))

    sleeps: list[float] = []
    cfg = resolve_config_for_supervised_run(sleep=sleeps.append)

    assert cfg.watch_dir == tmp_path
    assert sleeps == []


def test_resolve_config_for_supervised_run_retries_instead_of_raising(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """#4362: a missing HEIMDAL_CAPTURE_WATCH_DIR at supervised-loop startup
    must not raise (which would exit the process and, under `restart:
    unless-stopped`, crash-loop faster than the container healthcheck's
    interval/retries window can observe it). It must retry in place instead,
    so the process stays resident long enough for the independent compose
    healthcheck to actually run and report unhealthy honestly."""
    monkeypatch.delenv(capture_runtime.WATCH_DIR_ENV, raising=False)

    sleeps: list[float] = []
    attempts = {"n": 0}

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        attempts["n"] += 1
        if attempts["n"] == 2:
            monkeypatch.setenv(capture_runtime.WATCH_DIR_ENV, str(tmp_path))

    cfg = resolve_config_for_supervised_run(
        sleep=fake_sleep, retry_interval_seconds=3.0
    )

    assert cfg.watch_dir == tmp_path
    assert sleeps == [3.0, 3.0]


def test_resolve_config_for_supervised_run_raises_after_max_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bounded-attempts mode (used by tests) still surfaces the error once
    the attempt budget is exhausted, instead of retrying forever."""
    monkeypatch.delenv(capture_runtime.WATCH_DIR_ENV, raising=False)

    with pytest.raises(CaptureRuntimeConfigError):
        resolve_config_for_supervised_run(
            sleep=lambda _seconds: None, max_attempts=2
        )
