from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path
from typing import Any, Dict

import yaml

from app.events.bus import emit
from .loader import read_text, split_sections
from .models import (
    ClassifierSettings,
    GlobalSettings,
    PromotionSettings,
    Providers,
    SettingsBundle,
)
from .parsers import parse_section

VAULT = Path("vault/@Settings")
RUNTIME = Path("runtime/settings")


def merge(dst: Dict[str, Any], src: Dict[str, Any]) -> Dict[str, Any]:
    for key, value in src.items():
        if isinstance(value, dict) and isinstance(dst.get(key), dict):
            merge(dst[key], value)
        else:
            dst[key] = value
    return dst


def resolve_secret(val: Any) -> Any:
    if isinstance(val, str) and val.startswith("${SECRET:") and val.endswith("}"):
        name = val[9:-1]
        return os.environ.get(name, f"missing:{name}")
    if isinstance(val, dict):
        return {k: resolve_secret(v) for k, v in val.items()}
    if isinstance(val, list):
        return [resolve_secret(v) for v in val]
    return val


def compile_file(path: Path) -> Dict[str, Any]:
    md = read_text(path)
    data: Dict[str, Any] = {}
    for name, body in split_sections(md):
        section = parse_section(body)
        if not section:
            continue
        existing = data.get(name, {})
        if isinstance(existing, dict) and isinstance(section, dict):
            data[name] = merge(existing, section)
        else:
            data[name] = section
    return data


def _merge_sections(sections: Dict[str, Any]) -> Dict[str, Any]:
    merged: Dict[str, Any] = {}
    for payload in sections.values():
        if isinstance(payload, dict):
            merge(merged, payload)
    return merged


def dump(relative: str, payload: Dict[str, Any]) -> None:
    target = RUNTIME / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(payload, handle, allow_unicode=True, sort_keys=True)


def compile_all() -> SettingsBundle:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    file_sections: Dict[str, Dict[str, Any]] = {}
    for path in sorted(VAULT.glob("*.md")):
        file_sections[path.stem] = compile_file(path)

    agent_sections: Dict[str, Dict[str, Any]] = {}
    agents_dir = VAULT / "agents"
    if agents_dir.exists():
        for path in sorted(agents_dir.glob("*.md")):
            agent_sections[path.stem] = compile_file(path)

    bundle = SettingsBundle()
    bundle.global_ = GlobalSettings(
        **resolve_secret(_merge_sections(file_sections.get("global", {})))
    )
    bundle.providers = Providers(
        **resolve_secret(_merge_sections(file_sections.get("providers", {})))
    )

    agents_cfg: Dict[str, Any] = {}
    for agent_name, sections in agent_sections.items():
        merged = _merge_sections(sections)
        if not merged:
            continue
        if agent_name == "classifier":
            agents_cfg[agent_name] = ClassifierSettings(**resolve_secret(merged))
        elif agent_name == "promotion":
            agents_cfg[agent_name] = PromotionSettings(**resolve_secret(merged))
        else:
            agents_cfg[agent_name] = resolve_secret(merged)
    bundle.agents = agents_cfg

    dump("global.yaml", bundle.global_.model_dump())
    dump("providers.yaml", bundle.providers.model_dump())
    for name, settings in bundle.agents.items():
        payload = settings.model_dump() if hasattr(settings, "model_dump") else settings
        dump(f"agents/{name}.yaml", payload)

    fingerprint = hashlib.sha256(
        yaml.safe_dump(bundle.model_dump(), sort_keys=True).encode("utf-8")
    ).hexdigest()[:12]
    emit("settings.changed", {"sha": fingerprint, "ts": time.time()})
    return bundle
