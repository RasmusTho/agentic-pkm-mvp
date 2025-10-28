from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from jsonschema import validate

SETTINGS_PATH = Path("vault/_system/settings/system-settings.yaml")
SCHEMA_PATH = Path("schemas/system-settings.schema.json")

_cached_path: Path | None = None
_cached: dict[str, Any] | None = None
_mtime: float | None = None


def _load_schema() -> dict[str, Any]:
    if not SCHEMA_PATH.exists():
        return {}
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _load_yaml(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8")
    data = yaml.safe_load(raw) or {}
    if not isinstance(data, dict):
        raise ValueError("system settings YAML must decode into a mapping")
    return data


def load_settings(force: bool = False, path: Path | None = None) -> dict[str, Any] | None:
    global _cached, _mtime, _cached_path
    if path is None:
        path = SETTINGS_PATH
    if not path.exists():
        return _cached if (_cached is not None and _cached_path == path) else None
    stat = path.stat().st_mtime
    if (
        not force
        and _cached is not None
        and _mtime == stat
        and _cached_path == path
    ):
        return _cached
    data = _load_yaml(path)
    schema = _load_schema()
    if schema:
        validate(instance=data, schema=schema)
    _cached = data
    _mtime = stat
    _cached_path = path
    return _cached


def policy(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    if settings is None:
        settings = load_settings() or {}
    sync = settings.get("sync", {})
    agents = settings.get("agents", {})
    return {
        "debounce_ms": int(sync.get("debounce_ms", 1200)),
        "inactive_grace_s": int(sync.get("inactive_grace_s", 5)),
        "reembed_on_body_diff": bool(agents.get("reembed_on_body_diff", True)),
    }
