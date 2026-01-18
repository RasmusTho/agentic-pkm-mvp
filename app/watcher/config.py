from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from app.index.outbox import DEFAULT_OUTBOX_PATH
from app.vault.paths import ensure_vault_path_env_defaults, get_vault_inbox_dir_rel
from app.watcher.heartbeat import DEFAULT_HEARTBEAT_PATH, resolve_heartbeat_path

_TRUE_VALUES = {"1", "true", "yes", "on"}

ensure_vault_path_env_defaults()


def _default_scope_glob() -> str:
    inbox = os.getenv("VAULT_INBOX_DIR_REL") or get_vault_inbox_dir_rel()
    return f"{inbox}/**"


@dataclass
class WatcherConfig:
    enable: bool
    vault_path: Path
    scope_glob: str = _default_scope_glob()
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

    @classmethod
    def from_env(cls) -> WatcherConfig:
        enable = _as_bool(os.getenv("WATCHER_ENABLE", "0"))
        vault_raw = os.getenv("WATCHER_VAULT_PATH") or ""
        if enable and not vault_raw.strip():
            raise ValueError("WATCHER_VAULT_PATH is required when WATCHER_ENABLE=1")
        vault_path = Path(vault_raw or ".")

        scope_glob = os.getenv("WATCHER_SCOPE_GLOB", _default_scope_glob())
        debounce_ms = _as_int(os.getenv("WATCHER_DEBOUNCE_MS"), fallback=1500)
        rate_limit_per_min = _as_int(os.getenv("WATCHER_RATE_LIMIT_PER_MIN"), fallback=30)
        backoff_seconds = _as_int(os.getenv("WATCHER_BACKOFF_SECONDS"), fallback=10)
        outbox_env = os.getenv("INDEX_OUTBOX_PATH") or str(DEFAULT_OUTBOX_PATH)
        state_path = Path(os.getenv("WATCHER_STATE_PATH", "tmp/watcher_state.json"))
        stop_file = Path(os.getenv("WATCHER_STOP_FILE", "tmp/WATCHER_STOP"))
        heartbeat_path = resolve_heartbeat_path()
        tick_log_env = os.getenv("WATCHER_TICK_LOG_PATH")
        tick_log_path = Path(tick_log_env) if tick_log_env else Path("/app/tmp/watcher_tick.jsonl")

        return cls(
            enable=enable,
            vault_path=vault_path.expanduser(),
            scope_glob=scope_glob,
            debounce_ms=debounce_ms,
            rate_limit_per_min=rate_limit_per_min,
            backoff_seconds=backoff_seconds,
            state_path=state_path.expanduser(),
            stop_file=stop_file.expanduser(),
            outbox_path=Path(outbox_env).expanduser(),
            heartbeat_path=heartbeat_path,
            tick_log_path=tick_log_path.expanduser(),
        )


def _as_bool(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in _TRUE_VALUES


def _as_int(value: str | None, *, fallback: int) -> int:
    try:
        return int(value) if value is not None else fallback
    except Exception:
        return fallback


__all__ = ["WatcherConfig"]
