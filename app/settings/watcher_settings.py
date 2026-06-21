from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping

import yaml

from app.config.environment import active_environment
from app.config.paths import (
    VaultRootMisconfiguredError,
    resolve_optional_vault_root,
    resolve_runtime_artifact_path,
)
from app.settings.source import SettingsSource, build_source

DEFAULT_INDEX_OUTBOX = Path("tmp/index-outbox.jsonl")
DEFAULT_WATCHER_TICK_LOG = Path("tmp/watcher_tick.jsonl")
DEFAULT_WATCHER_RUN_LOG = Path("tmp/watcher_run.jsonl")
# Maximum size (bytes) before the watcher_run_log is rotated. Default 10 MB.
WATCHER_RUN_LOG_MAX_BYTES_DEFAULT = 10 * 1024 * 1024
DEFAULT_ALLOWED_ACTIONS = ("promote.evergreen",)
SUMMARY_MEASUREMENT_ACTION = "ingest.summary.create"
MEASUREMENT_MODE_ENV = "WATCHER_MEASUREMENT_MODE"
DEFAULT_AUTO_EXEC_ENV = "WATCHER_AUTO_EXEC"
DEFAULT_AUTO_EXEC_DEFAULT = True
_TRUE_VALUES = {"1", "true", "yes", "on"}


def _resolve_vault_root(vault_root: Path | None = None) -> Path | None:
    """Resolve the vault root for the *optional* watcher settings file, or ``None``.

    An explicit ``vault_root`` always wins. Otherwise resolution defers to
    :func:`app.config.paths.resolve_optional_vault_root`. The legacy silent
    ``Path("vault")`` CWD fallback is removed (#2384): with no vault selected the
    settings file is not read from a synthesized ``./vault`` and this returns
    ``None`` (defaults are used).

    The watcher settings *file* (``@Settings/watchers.md``) is optional config
    that only tunes the watcher; it is not a note read/write surface. A
    set-but-missing ``VAULT_ROOT`` therefore degrades to no-settings here rather
    than raising at import time — the loud set-but-missing contract is enforced
    by the resolvers that actually read or write vault notes (inbox, vault path
    helpers, health, worker) and by the channel preflight, not by this optional
    config lookup.
    """
    if vault_root is not None:
        return Path(vault_root).expanduser()
    try:
        return resolve_optional_vault_root()
    except VaultRootMisconfiguredError:
        return None


def _settings_file(vault_root: Path | None = None) -> Path | None:
    root = _resolve_vault_root(vault_root)
    if root is None:
        return None
    return root / "@Settings" / "watchers.md"


def _read_frontmatter(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise ValueError("watcher settings frontmatter is malformed")
    block = parts[1]
    try:
        data = yaml.safe_load(block) or {}
    except yaml.YAMLError as exc:  # pragma: no cover - YAML error handling
        raise ValueError(f"invalid watcher settings: {exc}")
    if not isinstance(data, dict):
        raise ValueError("watcher settings frontmatter must be a mapping")
    return data


def _resolve_path_setting(
    candidate: Any, env_key: str, default: Path, *, environment: Literal["dev", "prod", "test"] | None = None
) -> Path:
    """Resolve a path setting with optional environment scoping.

    Args:
        candidate: Explicit path from config
        env_key: Environment variable name
        default: Default path
        environment: Environment for scoping artifact paths

    Returns:
        Resolved path, scoped to environment if applicable
    """
    if isinstance(candidate, str) and candidate.strip():
        resolved = Path(candidate.strip()).expanduser()
    else:
        env_value = os.getenv(env_key, "").strip()
        resolved = Path(env_value).expanduser() if env_value else default

    # Apply environment scoping to tmp-based artifact paths
    if environment and str(resolved).startswith("tmp"):
        resolved = resolve_runtime_artifact_path(resolved, environment=environment)

    return resolved


@dataclass(frozen=True)
class WatcherPaths:
    index_outbox: Path
    watcher_tick_log: Path
    watcher_heartbeat: Path
    worker_heartbeat: Path
    watcher_state: Path
    watcher_stop_file: Path
    panel_event_log: Path
    watcher_run_log: Path


@dataclass(frozen=True)
class WatcherSettings:
    auto_exec_env: str
    auto_exec_default: bool
    allowed_actions: tuple[str, ...]
    paths: WatcherPaths
    source: SettingsSource


@dataclass(frozen=True)
class AutoExecResolution:
    env_key: str
    default_enabled: bool
    enabled: bool
    source: str
    raw_value: str | None


def load_watcher_settings(vault_root: Path | None = None, *, environment: Literal["dev", "prod", "test"] | None = None) -> WatcherSettings:
    """Load watcher settings with optional environment scoping.

    Args:
        vault_root: Override vault root path
        environment: Environment for artifact path scoping

    Returns:
        WatcherSettings with environment-scoped paths if applicable
    """
    path = _settings_file(vault_root)
    data = _read_frontmatter(path)
    auto_run = data.get("auto_run") or {}
    paths_cfg = data.get("paths") or {}

    allowed_actions_raw = auto_run.get("allowed_actions")
    if isinstance(allowed_actions_raw, list):
        allowed_actions = tuple(
            str(value).strip()
            for value in allowed_actions_raw
            if isinstance(value, (str, int)) and str(value).strip()
        )
    else:
        allowed_actions = ()
    if not allowed_actions:
        allowed_actions = DEFAULT_ALLOWED_ACTIONS
    if str(os.getenv(MEASUREMENT_MODE_ENV, "")).strip().lower() in _TRUE_VALUES:
        if SUMMARY_MEASUREMENT_ACTION not in allowed_actions:
            allowed_actions = (*allowed_actions, SUMMARY_MEASUREMENT_ACTION)

    auto_exec_env = str(auto_run.get("auto_exec_env") or DEFAULT_AUTO_EXEC_ENV).strip()
    if not auto_exec_env:
        auto_exec_env = DEFAULT_AUTO_EXEC_ENV
    auto_exec_default = bool(auto_run.get("auto_exec_default", DEFAULT_AUTO_EXEC_DEFAULT))

    # Use provided environment or detect from runtime
    env = environment or active_environment()

    index_outbox = _resolve_path_setting(paths_cfg.get("index_outbox"), "INDEX_OUTBOX_PATH", DEFAULT_INDEX_OUTBOX, environment=env)
    watcher_tick_log = _resolve_path_setting(
        paths_cfg.get("watcher_tick_log"),
        "WATCHER_TICK_LOG_PATH",
        DEFAULT_WATCHER_TICK_LOG,
        environment=env,
    )
    watcher_heartbeat = _resolve_path_setting(
        paths_cfg.get("watcher_heartbeat"),
        "WATCHER_HEARTBEAT_PATH",
        Path("tmp/watcher_heartbeat.json"),
        environment=env,
    )
    worker_heartbeat = _resolve_path_setting(
        paths_cfg.get("worker_heartbeat"),
        "WORKER_HEARTBEAT_PATH",
        Path("tmp/worker_heartbeat.json"),
        environment=env,
    )
    watcher_state = _resolve_path_setting(
        paths_cfg.get("watcher_state"),
        "WATCHER_STATE_PATH",
        Path("tmp/watcher_state.json"),
        environment=env,
    )
    watcher_stop_file = _resolve_path_setting(
        paths_cfg.get("watcher_stop_file"),
        "WATCHER_STOP_FILE",
        Path("tmp/WATCHER_STOP"),
        environment=env,
    )
    panel_event_log = _resolve_path_setting(
        paths_cfg.get("panel_event_log"),
        "INDEX_OUTBOX_PATH",
        index_outbox,
        environment=env,
    )
    watcher_run_log = _resolve_path_setting(
        paths_cfg.get("watcher_run_log"),
        "WATCHER_RUN_LOG_PATH",
        DEFAULT_WATCHER_RUN_LOG,
        environment=env,
    )

    source = (
        SettingsSource(path="", mtime=None, sha256=None)
        if path is None
        else build_source(path)
    )

    return WatcherSettings(
        auto_exec_env=auto_exec_env,
        auto_exec_default=auto_exec_default,
        allowed_actions=allowed_actions,
        paths=WatcherPaths(
            index_outbox=index_outbox,
            watcher_tick_log=watcher_tick_log,
            watcher_heartbeat=watcher_heartbeat,
            worker_heartbeat=worker_heartbeat,
            watcher_state=watcher_state,
            watcher_stop_file=watcher_stop_file,
            panel_event_log=panel_event_log,
            watcher_run_log=watcher_run_log,
        ),
        source=source,
    )


def invalid_allowed_actions(settings: WatcherSettings, valid_actions: Iterable[str]) -> list[str]:
    valid_set = set(valid_actions)
    return [action for action in settings.allowed_actions if action not in valid_set]


def resolve_auto_exec_enabled(
    *,
    vault_root: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> bool:
    return resolve_auto_exec_state(vault_root=vault_root, env=env).enabled


def resolve_auto_exec_state(
    *,
    vault_root: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> AutoExecResolution:
    settings = load_watcher_settings(vault_root)
    env_map = os.environ if env is None else env
    raw = env_map.get(settings.auto_exec_env)
    if raw is None:
        return AutoExecResolution(
            env_key=settings.auto_exec_env,
            default_enabled=settings.auto_exec_default,
            enabled=settings.auto_exec_default,
            source="settings_default",
            raw_value=None,
        )
    return AutoExecResolution(
        env_key=settings.auto_exec_env,
        default_enabled=settings.auto_exec_default,
        enabled=str(raw).strip().lower() in _TRUE_VALUES,
        source="env",
        raw_value=str(raw),
    )
