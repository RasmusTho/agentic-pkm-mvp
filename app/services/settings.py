from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from jsonschema import validate

SETTINGS_PATH = Path("System/Settings/system.md")
SCHEMA_PATH = Path("docs/schema/system-settings.schema.json")

_cached: dict[str, Any] | None = None
_mtime: float | None = None


def _parse_frontmatter(raw: str) -> dict[str, Any]:
    if not raw.startswith("---"):
        return {}
    parts = raw.split("---", 2)
    if len(parts) < 3:
        return {}
    fm_block = parts[1].strip()
    if not fm_block:
        return {}
    data = yaml.safe_load(fm_block) or {}
    if not isinstance(data, dict):
        raise ValueError("system settings frontmatter must be a mapping")
    return data


def _load_schema() -> dict[str, Any]:
    if not SCHEMA_PATH.exists():
        return {}
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def load_settings(force: bool = False) -> dict[str, Any] | None:
    global _cached, _mtime
    if not SETTINGS_PATH.exists():
        return _cached if _cached is not None else None
    stat = SETTINGS_PATH.stat().st_mtime
    if not force and _cached is not None and _mtime == stat:
        return _cached
    data = _parse_frontmatter(SETTINGS_PATH.read_text(encoding="utf-8"))
    schema = _load_schema()
    if schema:
        validate(data, schema)
    _cached = data
    _mtime = stat
    return _cached


def policy() -> dict[str, Any]:
    settings = load_settings() or {}
    sync = settings.get("sync", {})
    agents = settings.get("agents", {})
    return {
        "debounce_ms": sync.get("debounce_ms", 1200),
        "inactive_grace_s": sync.get("active_edit_grace_s", 5),
        "reembed_on_body_diff": agents.get("reembed_on_body_diff", True),
    }
