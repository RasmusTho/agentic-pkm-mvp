from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.settings.source import SettingsSource, build_source

import yaml

from app.config.paths import resolve_vault_root
from app.vault.paths import get_vault_system_dir_rel


def _settings_rel_path(vault_root: Path) -> Path:
    system_dir_rel = get_vault_system_dir_rel(vault_root)
    return Path(system_dir_rel) / "Settings" / "health.md"



@dataclass(frozen=True)
class HealthThresholds:
    outbox_degrade_oldest_age_s: float
    outbox_recover_oldest_age_s: float
    degrade_samples: int
    recover_samples: int

    @staticmethod
    def defaults() -> HealthThresholds:
        return HealthThresholds(
            outbox_degrade_oldest_age_s=15.0,
            outbox_recover_oldest_age_s=5.0,
            degrade_samples=3,
            recover_samples=10,
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "outbox_degrade_oldest_age_s": self.outbox_degrade_oldest_age_s,
            "outbox_recover_oldest_age_s": self.outbox_recover_oldest_age_s,
            "degrade_samples": self.degrade_samples,
            "recover_samples": self.recover_samples,
        }


@dataclass(frozen=True)
class IncidentCaptureSettings:
    enabled: bool = False
    transition_history: bool = False


@dataclass(frozen=True)
class HealthPolicy:
    env_overrides: bool = False


@dataclass(frozen=True)
class HealthSettingsV1:
    thresholds: HealthThresholds
    incident_capture: IncidentCaptureSettings
    policy: HealthPolicy
    incident_log_path: Path

    @staticmethod
    def defaults() -> HealthSettingsV1:
        return HealthSettingsV1(
            thresholds=HealthThresholds.defaults(),
            incident_capture=IncidentCaptureSettings(),
            policy=HealthPolicy(),
            incident_log_path=_default_incident_log_path(),
        )


@dataclass(frozen=True)
class HealthSettingsLoadResult:
    status: str
    settings: HealthSettingsV1
    source: SettingsSource
    errors: list[str]


_ENV_OVERRIDE_SPEC = {
    "HEALTH_THRESHOLDS_OUTBOX_DEGRADE_OLDEST_AGE_S": (
        "outbox_degrade_oldest_age_s",
        float,
    ),
    "HEALTH_THRESHOLDS_OUTBOX_RECOVER_OLDEST_AGE_S": (
        "outbox_recover_oldest_age_s",
        float,
    ),
    "HEALTH_THRESHOLDS_DEGRADE_SAMPLES": (
        "degrade_samples",
        int,
    ),
    "HEALTH_THRESHOLDS_RECOVER_SAMPLES": (
        "recover_samples",
        int,
    ),
}


def load_health_settings(
    *,
    vault_root: Path | None = None,
    env_getter: Callable[[str], str | None] | None = None,
) -> HealthSettingsLoadResult:
    vault_root = vault_root or resolve_vault_root()
    target = vault_root / _settings_rel_path(vault_root)
    source = build_source(target)
    if not target.exists():
        return HealthSettingsLoadResult(
            status="missing",
            settings=HealthSettingsV1.defaults(),
            source=source,
            errors=[],
        )

    raw, parse_errors = _read_frontmatter(target)
    errors: list[str] = [*parse_errors]
    thresholds_candidate = _parse_thresholds(raw, errors)
    incident_capture = _parse_incident_capture(raw, errors)
    policy = _parse_policy(raw, errors)
    incident_log_path = _parse_incident_log_path(raw, errors)
    env_getter = env_getter or os.getenv

    if thresholds_candidate is None or errors:
        status = "fail"
        active_settings = HealthSettingsV1.defaults()
    else:
        overrides, override_errors = _apply_env_overrides(thresholds_candidate, env_getter)
        if override_errors:
            errors.extend(override_errors)
            status = "fail"
            active_settings = HealthSettingsV1.defaults()
        else:
            status = "ok"
            active_settings = HealthSettingsV1(
                thresholds=overrides,
                incident_capture=incident_capture,
                policy=policy,
                incident_log_path=incident_log_path,
            )

    return HealthSettingsLoadResult(
        status=status,
        settings=active_settings,
        source=source,
        errors=errors,
    )



def _read_frontmatter(path: Path) -> tuple[dict[str, Any], list[str]]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}, []
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, ["malformed frontmatter: missing closing ---"]
    block = parts[1]
    try:
        data = yaml.safe_load(block) or {}
    except yaml.YAMLError as exc:
        return {}, [f"malformed YAML: {exc}"]
    if not isinstance(data, dict):
        return {}, ["frontmatter must be a mapping"]
    return data, []


def _parse_thresholds(data: dict[str, Any], errors: list[str]) -> HealthThresholds | None:
    raw_thresholds = data.get("thresholds")
    if not isinstance(raw_thresholds, dict):
        errors.append("missing thresholds block")
        return None
    values: dict[str, float | int] = {}
    threshold_errors: list[str] = []
    for key, caster in [
        ("outbox_degrade_oldest_age_s", float),
        ("outbox_recover_oldest_age_s", float),
        ("degrade_samples", int),
        ("recover_samples", int),
    ]:
        raw_value = raw_thresholds.get(key)
        if raw_value is None:
            threshold_errors.append(f"missing thresholds.{key}")
            continue
        try:
            values[key] = caster(raw_value)
        except Exception:
            threshold_errors.append(f"invalid thresholds.{key}")
    if threshold_errors:
        errors.extend(threshold_errors)
        return None
    return HealthThresholds(**values)


def _parse_incident_capture(data: dict[str, Any], errors: list[str]) -> IncidentCaptureSettings:
    raw = data.get("incident_capture")
    if not isinstance(raw, dict):
        return IncidentCaptureSettings()
    enabled = raw.get("enabled")
    transition_history = raw.get("transition_history")
    if enabled is None:
        enabled = False
    if transition_history is None:
        transition_history = False
    try:
        return IncidentCaptureSettings(
            enabled=bool(enabled),
            transition_history=bool(transition_history),
        )
    except Exception:
        errors.append("invalid incident_capture")
        return IncidentCaptureSettings()


def _parse_policy(data: dict[str, Any], errors: list[str]) -> HealthPolicy:
    raw = data.get("policy")
    if not isinstance(raw, dict):
        return HealthPolicy()
    env_overrides = raw.get("env_overrides")
    if env_overrides is None:
        env_overrides = False
    try:
        return HealthPolicy(env_overrides=bool(env_overrides))
    except Exception:
        errors.append("invalid policy")
        return HealthPolicy()


def _parse_incident_log_path(data: dict[str, Any], errors: list[str]) -> Path:
    raw = data.get("incident_log_path")
    if raw is None:
        return _default_incident_log_path()
    if not isinstance(raw, str):
        errors.append("incident_log_path must be a string")
        return _default_incident_log_path()
    return Path(raw)


def _default_incident_log_path() -> Path:
    return Path("tmp") / "health_incidents.jsonl"


def _apply_env_overrides(
    thresholds: HealthThresholds,
    env_getter: Callable[[str], str | None],
) -> tuple[HealthThresholds, list[str]]:
    overrides: dict[str, float | int] = {
        "outbox_degrade_oldest_age_s": thresholds.outbox_degrade_oldest_age_s,
        "outbox_recover_oldest_age_s": thresholds.outbox_recover_oldest_age_s,
        "degrade_samples": thresholds.degrade_samples,
        "recover_samples": thresholds.recover_samples,
    }
    errors: list[str] = []
    for env_key, (field, caster) in _ENV_OVERRIDE_SPEC.items():
        raw = env_getter(env_key)
        if raw is None:
            continue
        try:
            overrides[field] = caster(raw)
        except Exception:
            errors.append(f"invalid {env_key}")
    if errors:
        return thresholds, errors
    return HealthThresholds(**overrides), []
