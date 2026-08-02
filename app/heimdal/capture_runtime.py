"""Runtime driver for the Heimdal voice-memo capture adapter (#3094).

`app.heimdal.capture_adapter.run_watch_cycle` is a scan-once function (A6,
#3025): it has no built-in schedule. This module is the loop that drives it
on an interval against a real watched folder, shaped like
`app.watcher.watcher.run_forever` (sleep-loop, tick-level exception
isolation) without inheriting that module's vault-scan machinery -- Heimdal
watches one flat folder of capture files, not a vault tree.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from app.heimdal.capture_adapter import (
    DEFAULT_CAPTURE_SCOPE,
    SensorIdentity,
    WatchCycleResult,
    run_watch_cycle,
)

logger = logging.getLogger(__name__)

DEFAULT_INTERVAL_SECONDS = 30.0

WATCH_DIR_ENV = "HEIMDAL_CAPTURE_WATCH_DIR"
INTERVAL_ENV = "HEIMDAL_CAPTURE_INTERVAL_SECONDS"


class CaptureRuntimeConfigError(ValueError):
    """Raised when the runtime cannot resolve a required config value from the environment."""


@dataclass(frozen=True)
class CaptureRuntimeConfig:
    """Config for one capture-runtime driver instance.

    `watch_dir` is deliberately never defaulted to an operator-specific path
    -- the watched folder differs per device/operator, so it must come from
    `HEIMDAL_CAPTURE_WATCH_DIR` (or be passed explicitly by a caller, e.g. a
    test).
    """

    watch_dir: Path
    interval_seconds: float = DEFAULT_INTERVAL_SECONDS
    sensor: Optional[SensorIdentity] = None
    scope: str = DEFAULT_CAPTURE_SCOPE
    key: Optional[bytes] = None

    @classmethod
    def from_env(cls) -> "CaptureRuntimeConfig":
        raw_dir = (os.environ.get(WATCH_DIR_ENV) or "").strip()
        if not raw_dir:
            raise CaptureRuntimeConfigError(
                f"{WATCH_DIR_ENV} must be set to the capture folder to watch "
                "(the iCloud Shortcut's Save File destination)."
            )
        interval_raw = os.environ.get(INTERVAL_ENV)
        if interval_raw:
            try:
                interval = float(interval_raw)
            except ValueError as exc:
                raise CaptureRuntimeConfigError(
                    f"{INTERVAL_ENV}={interval_raw!r} is not a valid number of seconds."
                ) from exc
        else:
            interval = DEFAULT_INTERVAL_SECONDS
        return cls(watch_dir=Path(raw_dir), interval_seconds=interval)


def run_capture_tick(cfg: CaptureRuntimeConfig) -> Optional[WatchCycleResult]:
    """Run one watch cycle, isolating any exception so the driving loop survives.

    `run_watch_cycle` already isolates per-file failures (a bad file is
    recorded in `WatchCycleResult.refused`, not raised). This isolates the
    tick itself -- e.g. a transient I/O error listing the directory during
    an iCloud sync -- so one bad tick cannot stop the next one from running.
    Returns `None` on a failed tick instead of raising.
    """
    try:
        return run_watch_cycle(cfg.watch_dir, sensor=cfg.sensor, scope=cfg.scope, key=cfg.key)
    except Exception as exc:  # noqa: BLE001 -- deliberately broad: one bad tick must not kill the loop
        logger.error(
            "Heimdal capture runtime: tick failed for watch_dir=%s: %s. Will retry next tick.",
            cfg.watch_dir,
            exc,
        )
        return None


def resolve_config_for_supervised_run(
    *,
    sleep: Optional[Callable[[float], None]] = None,
    retry_interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
    max_attempts: Optional[int] = None,
) -> CaptureRuntimeConfig:
    """Resolve config for the supervised/looping entrypoint, retrying in place on failure.

    The `--once` CLI path fails loud and exits immediately on a config error
    -- correct for a manually-invoked diagnostic command. The supervised path
    (the compose service's default, no `--once`) must not do the same: under
    `restart: unless-stopped`, an immediate exit respawns the process faster
    than the container healthcheck's interval/retries window can observe a
    consistent failure, so `docker ps` keeps reporting the health status from
    the last successful start instead of transitioning to unhealthy -- a
    crash-loop hiding behind a healthy-looking healthcheck (#4362). Staying
    resident and retrying lets the independent compose healthcheck (which
    re-resolves this same config on its own schedule) accumulate real
    failures and report unhealthy honestly.

    `max_attempts=None` (the production default) retries forever. Tests pass
    a small `max_attempts` with an injected `sleep` to run deterministically.

    `sleep` defaults to `None` and resolves to `time.sleep` inside the loop
    (rather than as a bound default parameter value) so a caller that never
    passes `sleep` explicitly -- the CLI's supervised path -- still honors a
    `unittest.mock.patch`/`monkeypatch.setattr` of this module's `time.sleep`
    at test time; a default parameter value would capture the real
    `time.sleep` once at import time and ignore any later patch.
    """
    attempt = 0
    while True:
        try:
            return CaptureRuntimeConfig.from_env()
        except CaptureRuntimeConfigError as exc:
            attempt += 1
            logger.error(
                "heimdal capture-watch: config unresolved (attempt %d), retrying "
                "in %.0fs: %s",
                attempt,
                retry_interval_seconds,
                exc,
            )
            if max_attempts is not None and attempt >= max_attempts:
                raise
            (sleep or time.sleep)(retry_interval_seconds)


def run_forever(
    cfg: CaptureRuntimeConfig,
    *,
    max_ticks: Optional[int] = None,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Call `run_capture_tick` every `cfg.interval_seconds` forever (or `max_ticks` times).

    Returns the number of ticks executed. `max_ticks=None` is the intended
    production shape (runs until the process is stopped); tests pass a
    small `max_ticks` with an injected `sleep` to run deterministically
    without real waiting.
    """
    ticks = 0
    while max_ticks is None or ticks < max_ticks:
        run_capture_tick(cfg)
        ticks += 1
        if max_ticks is not None and ticks >= max_ticks:
            break
        sleep(cfg.interval_seconds)
    return ticks


__all__ = [
    "DEFAULT_INTERVAL_SECONDS",
    "WATCH_DIR_ENV",
    "INTERVAL_ENV",
    "CaptureRuntimeConfig",
    "CaptureRuntimeConfigError",
    "run_capture_tick",
    "resolve_config_for_supervised_run",
    "run_forever",
]
