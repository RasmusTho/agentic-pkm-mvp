from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable, Dict, Any, List

import yaml

from .compiler import RUNTIME
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
)
from .hotreload import init_hot_reload

_LOCK = threading.RLock()
_CURRENT: SettingsBundle | None = None
_SUBSCRIBERS: List[Callable[[SettingsBundle], None]] = []

AGENT_MODEL_MAP: Dict[str, Any] = {
    "classifier": ClassifierSettings,
    "promotion": PromotionSettings,
    "reviewer": ReviewerSettings,
    "qa": QaSettings,
}


def _read_yaml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return {}
    return data


def _build_bundle() -> SettingsBundle:
    global_yaml = _read_yaml(RUNTIME / "global.yaml")
    providers_yaml = _read_yaml(RUNTIME / "providers.yaml")
    instance_yaml = _read_yaml(RUNTIME / "instance.yaml")
    yggdrasil_yaml = _read_yaml(RUNTIME / "yggdrasil.yaml")
    agents_dir = RUNTIME / "agents"
    agents: Dict[str, Any] = {}
    if agents_dir.exists():
        for file in sorted(agents_dir.glob("*.yaml")):
            agent_data = _read_yaml(file)
            model_cls = AGENT_MODEL_MAP.get(file.stem)
            if model_cls:
                agents[file.stem] = model_cls(**agent_data)
            else:
                agents[file.stem] = agent_data
    yggdrasil_paths = None
    if yggdrasil_yaml:
        try:
            yggdrasil_paths = YggdrasilPaths(**yggdrasil_yaml)
        except Exception:
            yggdrasil_paths = None
    instance_settings = InstanceSettings()
    if instance_yaml:
        try:
            instance_settings = InstanceSettings(**instance_yaml)
        except Exception:
            instance_settings = InstanceSettings()
    bundle = SettingsBundle(
        global_=GlobalSettings(**global_yaml),
        providers=Providers(**providers_yaml),
        agents=agents,
        yggdrasil_paths=yggdrasil_paths,
        instance=instance_settings,
    )
    return bundle


def _notify(bundle: SettingsBundle) -> None:
    for callback in list(_SUBSCRIBERS):
        try:
            callback(bundle)
        except Exception:
            continue


def get_settings_bundle() -> SettingsBundle:
    with _LOCK:
        global _CURRENT
        if _CURRENT is None:
            _CURRENT = _build_bundle()
        return _CURRENT


def reload_settings_bundle(*, notify: bool = True) -> SettingsBundle:
    bundle = _build_bundle()
    with _LOCK:
        global _CURRENT
        _CURRENT = bundle
    if notify:
        _notify(bundle)
    return bundle


def subscribe_settings(callback: Callable[[SettingsBundle], None], *, replay: bool = True) -> None:
    _SUBSCRIBERS.append(callback)
    if replay:
        callback(get_settings_bundle())


def _handle_hot_reload(_payload: Dict[str, Any]) -> None:
    reload_settings_bundle()


init_hot_reload(_handle_hot_reload)
