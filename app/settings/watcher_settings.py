from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml

from app.settings.source import SettingsSource, build_source

DEFAULT_INDEX_OUTBOX = Path("tmp/index-outbox.jsonl")
DEFAULT_WATCHER_TICK_LOG = Path("tmp/watcher_tick.jsonl")
DEFAULT_ALLOWED_ACTIONS = ("promote.evergreen",)
DEFAULT_AUTO_EXEC_ENV = "WATCHER_AUTO_EXEC"
DEFAULT_AUTO_EXEC_DEFAULT = False


def _resolve_vault_root(vault_root: Path | None = None) -> Path:
    if vault_root is not None:
        return Path(vault_root).expanduser()
    env_root = os.getenv("VAULT_ROOT", "").strip()
    if env_root:
        return Path(env_root).expanduser()
    return Path("vault").expanduser()


def _settings_file(vault_root: Path | None = None) -> Path:
    return _resolve_vault_root(vault_root) / "@Settings" / "watchers.md"


def _read_frontmatter(path: Path) -> dict[str, Any]:
    if not path.exists():
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


def _resolve_path_setting(candidate: Any, env_key: str, default: Path) -> Path:
    if isinstance(candidate, str) and candidate.strip():
        return Path(candidate.strip()).expanduser()
    env_value = os.getenv(env_key, "").strip()
    if env_value:
        return Path(env_value).expanduser()
    return default


@dataclass(frozen=True)
class WatcherPaths:
    index_outbox: Path
    watcher_tick_log: Path
    panel_event_log: Path


@dataclass(frozen=True)
class WatcherSettings:
    auto_exec_env: str
    auto_exec_default: bool
    allowed_actions: tuple[str, ...]
    paths: WatcherPaths
    source: SettingsSource


def load_watcher_settings(vault_root: Path | None = None) -> WatcherSettings:
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

    auto_exec_env = str(auto_run.get("auto_exec_env") or DEFAULT_AUTO_EXEC_ENV).strip()
    if not auto_exec_env:
        auto_exec_env = DEFAULT_AUTO_EXEC_ENV
    auto_exec_default = bool(auto_run.get("auto_exec_default", DEFAULT_AUTO_EXEC_DEFAULT))

    index_outbox = _resolve_path_setting(paths_cfg.get("index_outbox"), "INDEX_OUTBOX_PATH", DEFAULT_INDEX_OUTBOX)
    watcher_tick_log = _resolve_path_setting(
        paths_cfg.get("watcher_tick_log"),
        "WATCHER_TICK_LOG_PATH",
        DEFAULT_WATCHER_TICK_LOG,
    )
    panel_event_log = _resolve_path_setting(
        paths_cfg.get("panel_event_log"),
        "INDEX_OUTBOX_PATH",
        index_outbox,
    )

    return WatcherSettings(
        auto_exec_env=auto_exec_env,
        auto_exec_default=auto_exec_default,
        allowed_actions=allowed_actions,
        paths=WatcherPaths(
            index_outbox=index_outbox,
            watcher_tick_log=watcher_tick_log,
            panel_event_log=panel_event_log,
        ),
        source=build_source(path),
    )


def invalid_allowed_actions(settings: WatcherSettings, valid_actions: Iterable[str]) -> list[str]:
    valid_set = set(valid_actions)
    return [action for action in settings.allowed_actions if action not in valid_set]
