from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Tuple

import fcntl

import yaml
from pydantic import ValidationError

from app.events.bus import emit
from app.components.settings.models_loader import load_models
from app.receipts.settings_write import SettingsWriteReceipt, emit_settings_write_receipt
from app.settings.panel_actions_settings import PanelActionsSettings, load_panel_actions_settings
from app.settings.locations import canonical_settings_root, resolve_compiled_sources
from app.settings.watcher_settings import WatcherSettings, load_watcher_settings
from .constraints import as_bool, clamp_int, enum_or_default
from .docs import BEGIN, END, inject_reference, render_reference
from .loader import read_text, split_sections
from .models import (
    ClassifierSettings,
    AskSettings,
    GlobalSettings,
    InstanceSettings,
    LLMRoutingSettings,
    PromotionSettings,
    Providers,
    QaSettings,
    ReviewerSettings,
    SettingsBundle,
    TTSSettings,
    YggdrasilPaths,
    EmbeddingProfiles,
)
from .prompts import resolve_ask_system_prompt
from .parsers import parse_section
from .writeback import write_markdown_via_knowledge_port, writeback_settings_block

VAULT = Path("vault/settings")
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


def dump(runtime_dir: Path, relative: str, payload: Dict[str, Any]) -> None:
    target = runtime_dir / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(payload, handle, allow_unicode=True, sort_keys=True)


def _source_fingerprints(source_paths: dict[Path, Path]) -> dict[str, str]:
    """Record the source bytes that produced one published runtime generation."""
    return {
        str(relative): hashlib.sha256(path.read_bytes()).hexdigest()
        for relative, path in sorted(source_paths.items(), key=lambda item: str(item[0]))
    }


def _new_staged_runtime_dir() -> Path:
    """Create a sibling directory so its symlink can be published atomically."""
    RUNTIME.parent.mkdir(parents=True, exist_ok=True)
    return Path(
        tempfile.mkdtemp(prefix=f".{RUNTIME.name}.staged-", dir=RUNTIME.parent)
    )


@contextmanager
def runtime_projection_lock(*, shared: bool):
    """Coordinate projection publishers with runtime snapshot readers.

    API, worker, and watcher share the app bind mount in dev. The lock lives
    beside the symlink so separate processes serialize publication while a
    reader resolves and consumes one complete projection generation.
    """
    RUNTIME.parent.mkdir(parents=True, exist_ok=True)
    lock_path = RUNTIME.parent / f".{RUNTIME.name}.lock"
    with lock_path.open("a+") as handle:
        mode = fcntl.LOCK_SH if shared else fcntl.LOCK_EX
        fcntl.flock(handle.fileno(), mode)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _publish_staged_runtime(staged_dir: Path) -> None:
    """Atomically switch a complete staged projection into place.

    The stable runtime path is a symlink after its first successful publish.  A
    later publish replaces that symlink in one ``os.replace`` call, so readers
    observe either the old complete projection or the new complete projection,
    never a mixture.  A legacy real directory is converted only after all
    compilation and specialised validation succeeded.
    """
    with runtime_projection_lock(shared=False):
        link = RUNTIME.parent / f".{RUNTIME.name}.next"
        link.unlink(missing_ok=True)
        link.symlink_to(staged_dir.name)

        if RUNTIME.is_symlink():
            previous_dir = RUNTIME.resolve()
            os.replace(link, RUNTIME)
            if previous_dir != staged_dir:
                shutil.rmtree(previous_dir, ignore_errors=True)
            return

        # Existing checkouts may still hold a real runtime/settings directory.
        # Do not touch it until a complete replacement has been staged and
        # validated. The first conversion needs two filesystem operations
        # because POSIX cannot atomically replace a non-empty directory with a
        # symlink; all later publications use the atomic path above.
        previous = RUNTIME.parent / f".{RUNTIME.name}.previous"
        previous.unlink(missing_ok=True)
        if RUNTIME.exists():
            os.replace(RUNTIME, previous)
        try:
            os.replace(link, RUNTIME)
        except Exception:
            if previous.exists():
                os.replace(previous, RUNTIME)
            raise
        shutil.rmtree(previous, ignore_errors=True)

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


def _resolve_route_target_model_ids(
    payload: Dict[str, Any],
    *,
    models_by_id: Dict[str, Any],
    expected_kind: str,
) -> Dict[str, Any]:
    resolved = dict(payload)
    model_id = resolved.get("model_id")
    if model_id:
        descriptor = models_by_id.get(str(model_id))
        if descriptor is None:
            raise ValueError(f"Unknown llm_routing model_id: {model_id}")
        if descriptor.kind != expected_kind:
            raise ValueError(
                f"Invalid llm_routing model_id {model_id}: expected kind={expected_kind}, got {descriptor.kind}"
            )
        resolved["provider"] = descriptor.provider
        resolved["model"] = descriptor.model
    return resolved


def _resolve_fallback_model_ids(
    payload: Dict[str, Any],
    *,
    models_by_id: Dict[str, Any],
    expected_kind: str,
) -> Dict[str, Any]:
    resolved = dict(payload)
    model_id = resolved.get("model_id")
    if model_id:
        descriptor = models_by_id.get(str(model_id))
        if descriptor is None:
            raise ValueError(f"Unknown llm_routing fallback model_id: {model_id}")
        if descriptor.kind != expected_kind:
            raise ValueError(
                f"Invalid llm_routing fallback model_id {model_id}: expected kind={expected_kind}, got {descriptor.kind}"
            )
        resolved["provider"] = descriptor.provider
        resolved["model"] = descriptor.model
    return resolved


def _resolve_task_policy_model_ids(
    payload: Dict[str, Any],
    *,
    models_by_id: Dict[str, Any],
    expected_kind: str,
) -> Dict[str, Any]:
    resolved = dict(payload)
    primary = resolved.get("primary")
    if isinstance(primary, dict):
        resolved["primary"] = _resolve_route_target_model_ids(
            primary,
            models_by_id=models_by_id,
            expected_kind=expected_kind,
        )
    fallback = resolved.get("fallback")
    if isinstance(fallback, dict):
        resolved["fallback"] = _resolve_fallback_model_ids(
            fallback,
            models_by_id=models_by_id,
            expected_kind=expected_kind,
        )
    return resolved


def _resolve_llm_routing_model_ids(payload: Dict[str, Any]) -> Dict[str, Any]:
    models_by_id = load_models()
    resolved = dict(payload)

    for key in ("default_chat", "default_reasoning", "default_eval"):
        section = resolved.get(key)
        if isinstance(section, dict):
            resolved[key] = _resolve_task_policy_model_ids(
                section,
                models_by_id=models_by_id,
                expected_kind="chat",
            )

    embedding = resolved.get("default_embedding")
    if isinstance(embedding, dict):
        resolved["default_embedding"] = _resolve_task_policy_model_ids(
            embedding,
            models_by_id=models_by_id,
            expected_kind="embedding",
        )

    tasks = resolved.get("tasks")
    if isinstance(tasks, dict):
        task_resolved: Dict[str, Any] = {}
        for task_kind, task_payload in tasks.items():
            if not isinstance(task_payload, dict):
                task_resolved[task_kind] = task_payload
                continue
            expected_kind = "embedding" if str(task_kind).strip().lower() == "embed" else "chat"
            task_resolved[task_kind] = _resolve_task_policy_model_ids(
                task_payload,
                models_by_id=models_by_id,
                expected_kind=expected_kind,
            )
        resolved["tasks"] = task_resolved

    return resolved


def _update_reference(path: Path, title: str, model: Any, auto_heal: bool, *, vault_root: Path) -> None:
    if not auto_heal or model is None:
        return
    try:
        markdown = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return
    block = render_reference(title, model)
    updated = inject_reference(markdown, block)
    if updated != markdown:
        write_markdown_via_knowledge_port(path, updated, vault_root=vault_root)
        old_reference = None
        if BEGIN in markdown and END in markdown:
            _, tail = markdown.split(BEGIN, 1)
            old_reference, _ = tail.split(END, 1)
            old_reference = old_reference.strip()
        emit_settings_write_receipt(
            SettingsWriteReceipt(
                key=f"{path.stem}.__reference__",
                value=block,
                old_value=old_reference,
                new_value=block,
                file=str(path),
                surface="auto-heal",
                actor="agent",
            )
        )


def compile_all(
    *,
    auto_heal: bool | None = None,
    vault_dir: Path | None = None,
    vault_root: Path | None = None,
) -> SettingsBundle:
    if vault_dir is not None and vault_root is not None:
        raise ValueError("pass vault_dir or vault_root, not both")
    settings_dir = (
        Path(vault_dir)
        if vault_dir is not None
        else canonical_settings_root(vault_root) if vault_root is not None else VAULT
    )
    auto_heal_enabled = _auto_heal_enabled(auto_heal)
    resolved_vault_root = Path(vault_root) if vault_root is not None else settings_dir.parent
    if vault_root is not None:
        source_paths = resolve_compiled_sources(resolved_vault_root)
    else:
        source_paths = {
            path.relative_to(settings_dir): path
            for path in settings_dir.rglob("*.md")
        } if settings_dir.exists() else {}
    file_sections: Dict[str, Dict[str, Any]] = {}
    file_paths: Dict[str, Path] = {}
    for relative, path in sorted(source_paths.items(), key=lambda item: str(item[0])):
        if relative.parent != Path("."):
            continue
        file_sections[path.stem] = compile_file(path)
        file_paths[path.stem] = path

    agent_sections: Dict[str, Dict[str, Any]] = {}
    agent_paths: Dict[str, Path] = {}
    for relative, path in sorted(source_paths.items(), key=lambda item: str(item[0])):
        if relative.parent != Path("agents"):
            continue
        agent_sections[path.stem] = compile_file(path)
        agent_paths[path.stem] = path

    canonical_source_root = canonical_settings_root(resolved_vault_root)

    def writeback_allowed(path: Path) -> bool:
        return auto_heal_enabled and path.resolve().is_relative_to(
            canonical_source_root
        )

    bundle = SettingsBundle()
    global_payload = _merge_sections(file_sections.get("global", {}))
    global_model, global_canonical, global_fixed = _hydrate_model(payload=global_payload, model_cls=GlobalSettings)
    bundle.global_ = global_model
    if global_fixed and "global" in file_paths and writeback_allowed(file_paths["global"]):
        writeback_settings_block(
            file_paths["global"],
            global_canonical,
            previous=global_payload,
            vault_root=resolved_vault_root,
        )
    if "global" in file_paths:
        _update_reference(file_paths["global"], "Global", bundle.global_, writeback_allowed(file_paths["global"]), vault_root=resolved_vault_root)

    provider_payload = _merge_sections(file_sections.get("providers", {}))
    providers_model, providers_canonical, providers_fixed = _hydrate_model(
        payload=provider_payload, model_cls=Providers
    )
    bundle.providers = providers_model
    if providers_fixed and "providers" in file_paths and writeback_allowed(file_paths["providers"]):
        writeback_settings_block(
            file_paths["providers"],
            providers_canonical,
            previous=provider_payload,
            vault_root=resolved_vault_root,
        )
    if "providers" in file_paths:
        _update_reference(file_paths["providers"], "Providers", bundle.providers, writeback_allowed(file_paths["providers"]), vault_root=resolved_vault_root)

    llm_routing_source_payload = _merge_sections(file_sections.get("llm_routing", {}))
    llm_routing_source_model, llm_routing_canonical, llm_routing_fixed = _hydrate_model(
        payload=llm_routing_source_payload, model_cls=LLMRoutingSettings
    )
    resolved_llm_routing_payload = _resolve_llm_routing_model_ids(
        llm_routing_source_model.model_dump(exclude_none=True)
    )
    bundle.llm_routing = LLMRoutingSettings(**resolved_llm_routing_payload)
    if llm_routing_fixed and "llm_routing" in file_paths and writeback_allowed(file_paths["llm_routing"]):
        writeback_settings_block(
            file_paths["llm_routing"],
            llm_routing_canonical,
            previous=llm_routing_source_payload,
            vault_root=resolved_vault_root,
        )
    if "llm_routing" in file_paths:
        _update_reference(file_paths["llm_routing"], "LLM routing", bundle.llm_routing, writeback_allowed(file_paths["llm_routing"]), vault_root=resolved_vault_root)

    embedding_payload = _merge_sections(file_sections.get("embeddings", {}))
    embeddings_model, embeddings_canonical, embeddings_fixed = _hydrate_model(
        payload=embedding_payload, model_cls=EmbeddingProfiles
    )
    bundle.embedding_profiles = embeddings_model
    if embeddings_fixed and "embeddings" in file_paths and writeback_allowed(file_paths["embeddings"]):
        writeback_settings_block(
            file_paths["embeddings"],
            embeddings_canonical,
            previous=embedding_payload,
            vault_root=resolved_vault_root,
        )
    if "embeddings" in file_paths:
        _update_reference(file_paths["embeddings"], "Embeddings", bundle.embedding_profiles, writeback_allowed(file_paths["embeddings"]), vault_root=resolved_vault_root)

    tts_payload = _merge_sections(file_sections.get("tts", {}))
    tts_model, tts_canonical, tts_fixed = _hydrate_model(payload=tts_payload, model_cls=TTSSettings)
    bundle.tts = tts_model
    if tts_fixed and "tts" in file_paths and writeback_allowed(file_paths["tts"]):
        writeback_settings_block(
            file_paths["tts"], tts_canonical, previous=tts_payload, vault_root=resolved_vault_root
        )
    if "tts" in file_paths:
        _update_reference(file_paths["tts"], "TTS", bundle.tts, writeback_allowed(file_paths["tts"]), vault_root=resolved_vault_root)

    yggdrasil_payload = _merge_sections(file_sections.get("yggdrasil", {}))
    if yggdrasil_payload:
        ygg_model, ygg_canonical, ygg_fixed = _hydrate_model(
            payload=yggdrasil_payload,
            model_cls=YggdrasilPaths,
        )
        bundle.yggdrasil_paths = ygg_model
        if ygg_fixed and "yggdrasil" in file_paths and writeback_allowed(file_paths["yggdrasil"]):
            writeback_settings_block(
                file_paths["yggdrasil"],
                ygg_canonical,
                previous=yggdrasil_payload,
                vault_root=resolved_vault_root,
            )
        if "yggdrasil" in file_paths:
            _update_reference(file_paths["yggdrasil"], "Yggdrasil", ygg_model, writeback_allowed(file_paths["yggdrasil"]), vault_root=resolved_vault_root)

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
            if normalized and agent_paths.get(agent_name) and writeback_allowed(agent_paths[agent_name]):
                writeback_settings_block(
                    agent_paths[agent_name],
                    healed_payload,
                    previous=merged,
                    vault_root=resolved_vault_root,
                )
            agents_cfg[agent_name] = instance
            if agent_paths.get(agent_name) and writeback_allowed(agent_paths[agent_name]):
                _update_reference(
                    agent_paths[agent_name],
                    agent_name.title(),
                    instance,
                    writeback_allowed(agent_paths[agent_name]),
                    vault_root=resolved_vault_root,
                )
        else:
            agents_cfg[agent_name] = resolve_secret(merged)

    ask_settings = agents_cfg.get("ask")
    if not isinstance(ask_settings, AskSettings):
        ask_settings = AskSettings()
    ask_prompt, _ = resolve_ask_system_prompt(resolved_vault_root)
    agents_cfg["ask"] = ask_settings.model_copy(update={"system_prompt": ask_prompt})
    bundle.agents = agents_cfg

    # Validate every specialised source before creating or replacing any runtime
    # projection.  A bad watcher/panel source must leave the last valid files
    # readable by a fresh process as well as by the current in-memory process.
    panel_actions_settings = load_panel_actions_settings()
    # Keep the watcher-specific settings loader on the same selected vault as
    # the generic and agent source compilation above.  Otherwise a
    # channel-scoped VAULT_ROOT_DEV/TEST could silently retain its default
    # auto-exec policy while the rest of the bundle came from this vault.
    watcher_settings = load_watcher_settings(vault_root=resolved_vault_root)

    staged_runtime = _new_staged_runtime_dir()
    try:
        dump(staged_runtime, "global.yaml", bundle.global_.model_dump())
        dump(staged_runtime, "providers.yaml", bundle.providers.model_dump())
        dump(staged_runtime, "llm_routing.yaml", bundle.llm_routing.model_dump())
        dump(staged_runtime, "tts.yaml", bundle.tts.model_dump())
        dump(staged_runtime, "instance.yaml", bundle.instance.model_dump())
        if bundle.yggdrasil_paths is not None:
            dump(staged_runtime, "yggdrasil.yaml", bundle.yggdrasil_paths.model_dump())
        for name, settings in bundle.agents.items():
            payload = settings.model_dump() if hasattr(settings, "model_dump") else settings
            dump(staged_runtime, f"agents/{name}.yaml", payload)
        dump(
            staged_runtime,
            "panel_actions.yaml",
            _panel_actions_payload(panel_actions_settings),
        )
        dump(staged_runtime, "watchers.yaml", _watcher_settings_payload(watcher_settings))
        with (staged_runtime / "sources.json").open("w", encoding="utf-8") as handle:
            json.dump(
                {"version": 1, "sources": _source_fingerprints(source_paths)},
                handle,
                sort_keys=True,
            )
        _publish_staged_runtime(staged_runtime)
    except Exception:
        shutil.rmtree(staged_runtime, ignore_errors=True)
        raise

    fingerprint = hashlib.sha256(
        yaml.safe_dump(bundle.model_dump(), sort_keys=True).encode("utf-8")
    ).hexdigest()[:12]
    emit("settings.changed", {"sha": fingerprint, "ts": time.time()})
    return bundle
