"""Watcher runtime configuration.

HTTP-vs-background split rationale (#2476)
------------------------------------------
The watcher resolves its vault via ``WATCHER_VAULT_PATH`` (not ``VAULT_ROOT``)
and builds a throwaway ``VaultManager`` to validate the path.  This is an
*intentional* HTTP-vs-background split, not a split-brain bug:

1. The watcher is a background process with an independent lifecycle — it does
   not participate in the HTTP vault-selection state machine managed by
   ``VaultManager`` singleton + ``AppLocalSettingsStore``.
2. ``WATCHER_VAULT_PATH`` lets operators bind the watcher to a vault
   independently of the user-facing ``VAULT_ROOT`` / selection flow (e.g. a
   fixed mount path inside a container).
3. Converging onto ``resolve_active_vault_root`` (the HTTP-path canonical
   resolver) would require the watcher to call back into the FastAPI process or
   share the in-memory singleton — coupling a background daemon to an HTTP
   runtime boundary that it must not own.
4. Converging onto ``resolve_optional_vault_root`` would remove the
   ``WATCHER_VAULT_PATH`` override capability and the VaultManager validation
   step that checks settings-level ``enable_vault_watcher``.

Verdict: document the split, do not converge.  The watcher vault binding is
governed by ``WATCHER_VAULT_PATH``; the HTTP path is governed by
``VAULT_ROOT`` + selection.  Both read from independent source-binding slots.
"""

from __future__ import annotations

import os
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from app.settings.tiering import resolve_dev_lab_env_typed
from app.settings.watcher_settings import load_watcher_settings
from app.vault.manager import VaultManager
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


# Vault statuses that mean "no usable vault yet, but not a misconfiguration":
# the runtime idles until one is opened/initialized instead of fail-exiting
# (#2005 — flips the #1991 hard precondition to idle-until-opened). A
# *set-but-missing* (status="missing") or otherwise *invalid* vault still fails
# loud, mirroring `app/watcher/relevance_tick.py` which skips a not-selected
# vault but never papers over a real misconfig.
_IDLE_VAULT_STATUSES = {"none", "uninitialized"}


def _validate_watcher_vault(vault_path: Path) -> bool:
    """Return True when the watcher should run; False when it should idle.

    Raises only for a *loud* misconfiguration (a set-but-missing or invalid
    vault path, or a vault whose settings disable the watcher). An absent or
    uninitialized vault returns False so the caller builds an idle runtime.
    """

    manager = VaultManager()
    context = manager.validate_vault(vault_path)
    if context.status in _IDLE_VAULT_STATUSES:
        logger.info(
            "vault watcher idling: no usable vault bound (status=%s path=%s)",
            context.status,
            vault_path,
        )
        return False
    if context.status != "selected":
        detail = f": {context.validation_error}" if context.validation_error else ""
        remedy = (
            f" — run `python -m app.cli vault init --path {vault_path}` to scaffold settings"
            if context.status == "uninitialized"
            else ""
        )
        raise ValueError(
            f"vault watcher requires an initialized selected vault; status={context.status}{detail}{remedy}"
        )
    permissions = manager.permissions_for_context(context)
    if not permissions.enable_vault_watcher:
        raise ValueError("vault watcher is disabled by settings/local.md")
    return True


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
            # No vault bound — idle until one is opened instead of raising
            # (#2005). The watcher comes up disabled; the run loop short-circuits
            # on `enable=False`, so no scan/index happens.
            logger.info("vault watcher idling: WATCHER_ENABLE=1 but no vault bound")
            enable = False
        vault_path = Path(vault_raw or ".").expanduser()
        if enable and not _validate_watcher_vault(vault_path):
            enable = False
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
