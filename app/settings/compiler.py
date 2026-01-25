from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path
from typing import Any, Dict, Tuple

import yaml
from pydantic import ValidationError

from app.events.bus import emit
from app.settings.panel_actions_settings import PanelActionsSettings, load_panel_actions_settings
from app.settings.watcher_settings import WatcherSettings, load_watcher_settings
from .constraints import as_bool, clamp_int, enum_or_default
from .docs import inject_reference, render_reference
from .loader import read_text, split_sections
from .models import (
    ClassifierSettings,
    GlobalSettings,
    InstanceSettings,
    PromotionSettings,
    Providers,
    QaSettings,
    ReviewerSettings,
    SettingsBundle,
    YggdrasilPaths,
    EmbeddingProfiles,
)
from .parsers import parse_section
from .writeback import writeback_settings_block

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


AGENT_MODEL_MAP: Dict[str, Any] = {
    "classifier": ClassifierSettings,
    "promotion": PromotionSettings,
    "reviewer": ReviewerSettings,
    "qa": QaSettings,
}


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

def _auto_heal_enabled(auto_heal: bool | None) -> bool:
    if auto_heal is not None:
        return auto_heal
    return os.getenv("SETTINGS_AUTO_HEAL", "").strip().lower() in {"1", "true", "yes", "on"}


def _normalize_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    normalized: Dict[str, Any] = {}
    for key, value in payload.items():
        if isinstance(value, dict):
            normalized[key] = _normalize_payload(value)
        elif isinstance(value, list):
            normalized[key] = list(value)
        else:
            normalized[key] = value
    if "timeout_ms" in normalized:
        normalized["timeout_ms"] = clamp_int(
            normalized["timeout_ms"], lo=100, hi=120000, default=8000
        )
    if "max_retries" in normalized:
        normalized["max_retries"] = clamp_int(
            normalized["max_retries"], lo=0, hi=10, default=3
        )
    if "batch_size" in normalized:
        normalized["batch_size"] = clamp_int(
            normalized["batch_size"], lo=1, hi=1000, default=100
        )
    if "search_k" in normalized:
        normalized["search_k"] = clamp_int(
            normalized["search_k"], lo=1, hi=20, default=8
        )
    if "context_docs" in normalized:
        normalized["context_docs"] = clamp_int(
            normalized["context_docs"], lo=1, hi=10, default=5
        )
    if "cooldown_seconds" in normalized:
        normalized["cooldown_seconds"] = clamp_int(
            normalized["cooldown_seconds"], lo=0, hi=86400, default=90
        )
    if "require_idle_seconds" in normalized:
        normalized["require_idle_seconds"] = clamp_int(
            normalized["require_idle_seconds"], lo=0, hi=3600, default=30
        )
    if "enable" in normalized:
        normalized["enable"] = as_bool(normalized["enable"], default=True)
    if "dry_run" in normalized:
        normalized["dry_run"] = as_bool(normalized["dry_run"], default=False)
    if "log_level" in normalized:
        normalized["log_level"] = enum_or_default(
            normalized["log_level"], {"DEBUG", "INFO", "WARNING", "ERROR"}, "INFO"
        )
    return normalized


def _panel_actions_payload(settings: PanelActionsSettings) -> Dict[str, Any]:
    return {
        "paths": [str(path) for path in settings.paths],
        "sources": [source.to_payload() for source in settings.sources],
        "combined_sha": settings.combined_sha,
        "action_ids": sorted(settings.catalog.ids()),
    }


def _watcher_settings_payload(settings: WatcherSettings) -> Dict[str, Any]:
    return {
        "auto_exec_env": settings.auto_exec_env,
        "auto_exec_default": settings.auto_exec_default,
        "allowed_actions": list(settings.allowed_actions),
        "paths": {
            "index_outbox": str(settings.paths.index_outbox),
            "watcher_tick_log": str(settings.paths.watcher_tick_log),
            "panel_event_log": str(settings.paths.panel_event_log),
        },
        "source": settings.source.to_payload(),
    }





def _hydrate_model(
    *,
    payload: Dict[str, Any],
    model_cls,
) -> Tuple[Any, Dict[str, Any], bool]:
    resolved = resolve_secret(payload)
    try:
        instance = model_cls(**resolved)
        return instance, payload, False
    except ValidationError:
        healed = _normalize_payload(payload)
        resolved_healed = resolve_secret(healed)
        instance = model_cls(**resolved_healed)
        return instance, healed, True


def _update_reference(path: Path, title: str, model: Any, auto_heal: bool) -> None:
    if not auto_heal or model is None:
        return
    try:
        markdown = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return
    block = render_reference(title, model)
    updated = inject_reference(markdown, block)
    if updated != markdown:
        path.write_text(updated, encoding="utf-8")


def compile_all(*, auto_heal: bool | None = None) -> SettingsBundle:
    auto_heal_enabled = _auto_heal_enabled(auto_heal)
    RUNTIME.mkdir(parents=True, exist_ok=True)
    file_sections: Dict[str, Dict[str, Any]] = {}
    file_paths: Dict[str, Path] = {}
    for path in sorted(VAULT.glob("*.md")):
        file_sections[path.stem] = compile_file(path)
        file_paths[path.stem] = path

    agent_sections: Dict[str, Dict[str, Any]] = {}
    agent_paths: Dict[str, Path] = {}
    agents_dir = VAULT / "agents"
    if agents_dir.exists():
        for path in sorted(agents_dir.glob("*.md")):
            agent_sections[path.stem] = compile_file(path)
            agent_paths[path.stem] = path

    bundle = SettingsBundle()
    global_payload = _merge_sections(file_sections.get("global", {}))
    global_model, global_canonical, global_fixed = _hydrate_model(payload=global_payload, model_cls=GlobalSettings)
    bundle.global_ = global_model
    if auto_heal_enabled and global_fixed and "global" in file_paths:
        writeback_settings_block(file_paths["global"], global_canonical)
    if "global" in file_paths:
        _update_reference(file_paths["global"], "Global", bundle.global_, auto_heal_enabled)

    provider_payload = _merge_sections(file_sections.get("providers", {}))
    providers_model, providers_canonical, providers_fixed = _hydrate_model(
        payload=provider_payload, model_cls=Providers
    )
    bundle.providers = providers_model
    if auto_heal_enabled and providers_fixed and "providers" in file_paths:
        writeback_settings_block(file_paths["providers"], providers_canonical)
    if "providers" in file_paths:
        _update_reference(file_paths["providers"], "Providers", bundle.providers, auto_heal_enabled)

    embedding_payload = _merge_sections(file_sections.get("embeddings", {}))
    embeddings_model, embeddings_canonical, embeddings_fixed = _hydrate_model(
        payload=embedding_payload, model_cls=EmbeddingProfiles
    )
    bundle.embedding_profiles = embeddings_model
    if auto_heal_enabled and embeddings_fixed and "embeddings" in file_paths:
        writeback_settings_block(file_paths["embeddings"], embeddings_canonical)
    if "embeddings" in file_paths:
        _update_reference(file_paths["embeddings"], "Embeddings", bundle.embedding_profiles, auto_heal_enabled)

    yggdrasil_payload = _merge_sections(file_sections.get("yggdrasil", {}))
    if yggdrasil_payload:
        ygg_model, ygg_canonical, ygg_fixed = _hydrate_model(
            payload=yggdrasil_payload,
            model_cls=YggdrasilPaths,
        )
        bundle.yggdrasil_paths = ygg_model
        if auto_heal_enabled and ygg_fixed and "yggdrasil" in file_paths:
            writeback_settings_block(file_paths["yggdrasil"], ygg_canonical)
        if "yggdrasil" in file_paths:
            _update_reference(file_paths["yggdrasil"], "Yggdrasil", ygg_model, auto_heal_enabled)

    instance_payload = _merge_sections(file_sections.get("instance", {}))
    bundle.instance = InstanceSettings(**instance_payload) if instance_payload else InstanceSettings()

    agents_cfg: Dict[str, Any] = {}
    for agent_name, sections in agent_sections.items():
        merged = _merge_sections(sections)
        if not merged:
            continue
        model_cls = AGENT_MODEL_MAP.get(agent_name)
        if model_cls:
            instance, healed_payload, normalized = _hydrate_model(
                payload=merged,
                model_cls=model_cls,
            )
            if auto_heal_enabled and normalized and agent_paths.get(agent_name):
                writeback_settings_block(agent_paths[agent_name], healed_payload)
            agents_cfg[agent_name] = instance
            if auto_heal_enabled and agent_paths.get(agent_name):
                _update_reference(agent_paths[agent_name], agent_name.title(), instance, auto_heal_enabled)
        else:
            agents_cfg[agent_name] = resolve_secret(merged)
    bundle.agents = agents_cfg

    dump("global.yaml", bundle.global_.model_dump())
    dump("providers.yaml", bundle.providers.model_dump())
    dump("instance.yaml", bundle.instance.model_dump())
    if bundle.yggdrasil_paths is not None:
        dump("yggdrasil.yaml", bundle.yggdrasil_paths.model_dump())

    agents_output_dir = RUNTIME / "agents"
    existing_agent_files = {
        path.stem: path for path in agents_output_dir.glob("*.yaml")
    } if agents_output_dir.exists() else {}
    stale_files = [
        path for stem, path in existing_agent_files.items() if stem not in bundle.agents
    ]
    for stale in stale_files:
        try:
            stale.unlink()
        except FileNotFoundError:
            pass

    for name, settings in bundle.agents.items():
        payload = settings.model_dump() if hasattr(settings, "model_dump") else settings
        dump(f"agents/{name}.yaml", payload)

    panel_actions_settings = load_panel_actions_settings()
    dump("panel_actions.yaml", _panel_actions_payload(panel_actions_settings))
    watcher_settings = load_watcher_settings()
    dump("watchers.yaml", _watcher_settings_payload(watcher_settings))

    fingerprint = hashlib.sha256(
        yaml.safe_dump(bundle.model_dump(), sort_keys=True).encode("utf-8")
    ).hexdigest()[:12]
    emit("settings.changed", {"sha": fingerprint, "ts": time.time()})
    return bundle

