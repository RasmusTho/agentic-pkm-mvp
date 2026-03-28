from __future__ import annotations

import os
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from app.settings.tiering import resolve_dev_lab_env_typed
from app.settings.watcher_settings import load_watcher_settings
from app.watcher.heartbeat import DEFAULT_HEARTBEAT_PATH, resolve_heartbeat_path


_TRUE_VALUES = {"1", "true", "yes", "on"}

DEFAULT_SCOPE_GLOB = "*.md,**/*.md"

logger = logging.getLogger(__name__)


def _as_bool(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in _TRUE_VALUES


def _as_int(value: str | None, *, fallback: int) -> int:
    try:
        return int(value) if value is not None else fallback
    except Exception:
        return fallback


def _as_float(value: str | None, *, fallback: float) -> float:
    try:
        return float(value) if value is not None else fallback
    except Exception:
        return fallback


def _parse_int_factory(*, fallback: int) -> Callable[[str], int]:
    return lambda raw: _as_int(raw, fallback=fallback)


def _parse_float_factory(*, fallback: float) -> Callable[[str], float]:
    return lambda raw: _as_float(raw, fallback=fallback)


def _default_scope_glob(vault_root: Path) -> str:
    del vault_root
    return DEFAULT_SCOPE_GLOB


@dataclass
class WatcherConfig:
    enable: bool
    vault_path: Path
    scope_glob: str
    debounce_ms: int = 1500
    rate_limit_per_min: int = 30
    backoff_seconds: int = 10
    state_path: Path = field(default_factory=lambda: load_watcher_settings().paths.watcher_state)
    stop_file: Path = field(default_factory=lambda: load_watcher_settings().paths.watcher_stop_file)
    outbox_path: Path = field(default_factory=lambda: load_watcher_settings().paths.index_outbox)
    heartbeat_path: Path = DEFAULT_HEARTBEAT_PATH
    summary_interval: int = 60
    tick_sleep_seconds: float = 1.0
    tick_log_path: Path = field(default_factory=lambda: load_watcher_settings().paths.watcher_tick_log)
    max_scanned_files_per_tick: int = 500
    max_bytes_read_per_tick: int = 50_000_000
    max_elapsed_ms_per_tick: int = 2000
    max_bad_ticks: int = 10
    bad_tick_backoff_seconds: float = 2.0

    @classmethod
    def from_env(cls) -> "WatcherConfig":
        enable = _as_bool(os.getenv("WATCHER_ENABLE", "0"))
        vault_raw = (os.getenv("WATCHER_VAULT_PATH") or "").strip()
        if enable and not vault_raw:
            raise ValueError("WATCHER_VAULT_PATH is required when WATCHER_ENABLE=1")
        vault_path = Path(vault_raw or ".").expanduser()
        watcher_settings = load_watcher_settings(vault_path)

        scope_env = (os.getenv("WATCHER_SCOPE_GLOB") or "").strip()
        scope_source = "env:WATCHER_SCOPE_GLOB" if scope_env else "default:vaultwide"
        scope_glob = scope_env if scope_env else _default_scope_glob(vault_path)
        logger.info(
            "watcher scope resolved vault_path=%s scope_glob=%s provenance=%s",
            vault_path,
            scope_glob,
            scope_source,
        )

        debounce_ms = resolve_dev_lab_env_typed(
            "WATCHER_DEBOUNCE_MS",
            default="1500",
            parser=_parse_int_factory(fallback=1500),
            logger=logger,
        )
        rate_limit_per_min = resolve_dev_lab_env_typed(
            "WATCHER_RATE_LIMIT_PER_MIN",
            default="30",
            parser=_parse_int_factory(fallback=30),
            logger=logger,
        )
        backoff_seconds = resolve_dev_lab_env_typed(
            "WATCHER_BACKOFF_SECONDS",
            default="10",
            parser=_parse_int_factory(fallback=10),
            logger=logger,
        )
        outbox_env = os.getenv("INDEX_OUTBOX_PATH") or str(watcher_settings.paths.index_outbox)
        state_path = Path(os.getenv("WATCHER_STATE_PATH") or watcher_settings.paths.watcher_state).expanduser()
        stop_file = Path(os.getenv("WATCHER_STOP_FILE") or watcher_settings.paths.watcher_stop_file).expanduser()
        heartbeat_path = resolve_heartbeat_path()
        tick_sleep_seconds = resolve_dev_lab_env_typed(
            "WATCHER_TICK_SLEEP_SECONDS",
            default="1.0",
            parser=_parse_float_factory(fallback=1.0),
            logger=logger,
        )
        tick_log_env = os.getenv("WATCHER_TICK_LOG_PATH")
        tick_log_path = Path(tick_log_env).expanduser() if tick_log_env else watcher_settings.paths.watcher_tick_log
        max_scanned_files_per_tick = _as_int(os.getenv("WATCHER_MAX_SCANNED_FILES_PER_TICK"), fallback=500)
        max_bytes_read_per_tick = _as_int(os.getenv("WATCHER_MAX_BYTES_READ_PER_TICK"), fallback=50_000_000)
        max_elapsed_ms_per_tick = _as_int(os.getenv("WATCHER_MAX_ELAPSED_MS_PER_TICK"), fallback=2000)
        max_bad_ticks = _as_int(os.getenv("WATCHER_MAX_BAD_TICKS"), fallback=10)
        bad_tick_backoff_seconds = _as_float(os.getenv("WATCHER_BAD_TICK_BACKOFF_SECONDS"), fallback=2.0)

        return cls(
            enable=enable,
            vault_path=vault_path,
            scope_glob=scope_glob,
            debounce_ms=debounce_ms,
            rate_limit_per_min=rate_limit_per_min,
            backoff_seconds=backoff_seconds,
            state_path=state_path,
            stop_file=stop_file,
            outbox_path=Path(outbox_env).expanduser(),
            heartbeat_path=heartbeat_path,
            summary_interval=_as_int(os.getenv("WATCHER_SUMMARY_INTERVAL"), fallback=60),
            tick_sleep_seconds=tick_sleep_seconds,
            tick_log_path=tick_log_path.expanduser(),
            max_scanned_files_per_tick=max_scanned_files_per_tick,
            max_bytes_read_per_tick=max_bytes_read_per_tick,
            max_elapsed_ms_per_tick=max_elapsed_ms_per_tick,
            max_bad_ticks=max_bad_ticks,
            bad_tick_backoff_seconds=bad_tick_backoff_seconds,
        )


__all__ = ["WatcherConfig"]
