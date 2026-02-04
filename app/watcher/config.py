from __future__ import annotations

import os
import logging
from dataclasses import dataclass
from pathlib import Path

from app.index.outbox import DEFAULT_OUTBOX_PATH
from app.watcher.heartbeat import DEFAULT_HEARTBEAT_PATH, resolve_heartbeat_path


_TRUE_VALUES = {"1", "true", "yes", "on"}

DEFAULT_SCOPE_GLOB = "**/*.md"

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
    state_path: Path = Path("tmp/watcher_state.json")
    stop_file: Path = Path("tmp/WATCHER_STOP")
    outbox_path: Path = DEFAULT_OUTBOX_PATH
    heartbeat_path: Path = DEFAULT_HEARTBEAT_PATH
    summary_interval: int = 60
    tick_sleep_seconds: float = 1.0
    tick_log_path: Path = Path("/app/tmp/watcher_tick.jsonl")
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

        scope_env = (os.getenv("WATCHER_SCOPE_GLOB") or "").strip()
        scope_source = "env" if scope_env else "default"
        scope_glob = scope_env if scope_env else _default_scope_glob(vault_path)
        logger.info(
            "watcher scope resolved vault_path=%s scope_glob=%s provenance=%s",
            vault_path,
            scope_glob,
            scope_source,
        )

        debounce_ms = _as_int(os.getenv("WATCHER_DEBOUNCE_MS"), fallback=1500)
        rate_limit_per_min = _as_int(os.getenv("WATCHER_RATE_LIMIT_PER_MIN"), fallback=30)
        backoff_seconds = _as_int(os.getenv("WATCHER_BACKOFF_SECONDS"), fallback=10)
        outbox_env = os.getenv("INDEX_OUTBOX_PATH") or str(DEFAULT_OUTBOX_PATH)
        state_path = Path(os.getenv("WATCHER_STATE_PATH", "tmp/watcher_state.json")).expanduser()
        stop_file = Path(os.getenv("WATCHER_STOP_FILE", "tmp/WATCHER_STOP")).expanduser()
        heartbeat_path = resolve_heartbeat_path()
        tick_sleep_seconds = _as_float(os.getenv("WATCHER_TICK_SLEEP_SECONDS"), fallback=1.0)
        tick_log_env = os.getenv("WATCHER_TICK_LOG_PATH")
        tick_log_path = Path(tick_log_env) if tick_log_env else Path("/app/tmp/watcher_tick.jsonl")
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
