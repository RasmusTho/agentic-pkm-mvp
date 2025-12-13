from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict

import yaml

DEFAULT_PANEL_ACTION_WIRING_PATH = Path("docs/settings/panel-action-wiring.yaml")


def _resolve_wiring_path(path: Path | None = None) -> Path | None:
    if path is not None:
        return Path(path)
    env_path = os.getenv("PANEL_ACTION_WIRING_PATH")
    if env_path:
        return Path(env_path)
    if DEFAULT_PANEL_ACTION_WIRING_PATH.exists():
        return DEFAULT_PANEL_ACTION_WIRING_PATH
    return None


def _load_raw(path: Path) -> dict:
    if not path.exists():
        return {}
    if path.suffix.lower() in {".json"}:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def load_action_wiring(path: Path | None = None) -> Dict[str, str]:
    resolved = _resolve_wiring_path(path)
    if resolved is None:
        return {}
    data = _load_raw(resolved)
    actions = data.get("actions") if isinstance(data, dict) else None
    if not isinstance(actions, list):
        return {}
    wiring: Dict[str, str] = {}
    for entry in actions:
        if not isinstance(entry, dict):
            continue
        action_id = str(entry.get("id") or "").strip()
        target = str(entry.get("target_event") or "").strip()
        if action_id and target:
            wiring[action_id] = target
    return wiring


def get_default_action_wiring() -> Dict[str, str]:
    return load_action_wiring()


def reset_action_wiring_cache() -> None:
    pass


__all__ = ["load_action_wiring", "get_default_action_wiring", "reset_action_wiring_cache", "DEFAULT_PANEL_ACTION_WIRING_PATH"]
