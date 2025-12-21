from __future__ import annotations

import hashlib
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from app.config.paths import resolve_vault_root

SETTINGS_REL_PATH = Path("@System") / "Settings" / "health.md"


@dataclass(frozen=True)
class SettingsSource:
    path: str
    mtime: str | None
    sha256: str | None

    def to_payload(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "mtime": self.mtime,
            "sha256": self.sha256,
        }


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

    @staticmethod
    def defaults() -> HealthSettingsV1:
        return HealthSettingsV1(
            thresholds=HealthThresholds.defaults(),
            incident_capture=IncidentCaptureSettings(),
            policy=HealthPolicy(),
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
    target = vault_root / SETTINGS_REL_PATH
    source = _build_source(target)
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
            )

    return HealthSettingsLoadResult(
        status=status,
        settings=active_settings,
        source=source,
        errors=errors,
    )


def _build_source(path: Path) -> SettingsSource:
    if path.exists():
        stat = path.stat()
        mtime = datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat()
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
    else:
        mtime = None
        sha = None
    return SettingsSource(path=str(path), mtime=mtime, sha256=sha)


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
        raw = raw_thresholds.get(key)
        if raw is None:
            threshold_errors.append(f"thresholds.{key} is required")
            continue
        try:
            values[key] = caster(raw)
        except (TypeError, ValueError):
            threshold_errors.append(f"thresholds.{key} must be {caster.__name__}")
    if threshold_errors:
        errors.extend(threshold_errors)
        return None
    return HealthThresholds(
        outbox_degrade_oldest_age_s=float(values["outbox_degrade_oldest_age_s"]),
        outbox_recover_oldest_age_s=float(values["outbox_recover_oldest_age_s"]),
        degrade_samples=int(values["degrade_samples"]),
        recover_samples=int(values["recover_samples"]),
    )


def _parse_incident_capture(data: dict[str, Any], errors: list[str]) -> IncidentCaptureSettings:
    block = data.get("incident_capture") or {}
    if block is None:
        block = {}
    if not isinstance(block, dict):
        errors.append("incident_capture must be a mapping")
        return IncidentCaptureSettings()
    enabled, err_enabled = _coerce_bool(block.get("enabled"))
    if err_enabled:
        errors.append("incident_capture.enabled must be boolean")
    history, err_history = _coerce_bool(block.get("transition_history"))
    if err_history:
        errors.append("incident_capture.transition_history must be boolean")
    return IncidentCaptureSettings(enabled=enabled, transition_history=history)


def _parse_policy(data: dict[str, Any], errors: list[str]) -> HealthPolicy:
    block = data.get("policy") or {}
    if block is None:
        block = {}
    if not isinstance(block, dict):
        errors.append("policy must be a mapping")
        return HealthPolicy()
    env_overrides, err = _coerce_bool(block.get("env_overrides"))
    if err:
        errors.append("policy.env_overrides must be boolean")
    return HealthPolicy(env_overrides=env_overrides)


def _coerce_bool(value: Any) -> tuple[bool, bool]:
    if value is None:
        return False, False
    if isinstance(value, bool):
        return value, False
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True, False
        if normalized in {"false", "0", "no", "off"}:
            return False, False
    return False, True


def _apply_env_overrides(
    thresholds: HealthThresholds,
    env_getter: Callable[[str], str | None],
) -> tuple[HealthThresholds, list[str]]:
    errors: list[str] = []
    values = thresholds.to_payload().copy()
    for var, (attr, caster) in _ENV_OVERRIDE_SPEC.items():
        raw = env_getter(var)
        if raw is None:
            continue
        try:
            values[attr] = caster(raw)
        except (TypeError, ValueError):
            errors.append(f"{var} must be {caster.__name__}")
    if errors:
        return thresholds, errors
    return (
        HealthThresholds(
            outbox_degrade_oldest_age_s=float(values["outbox_degrade_oldest_age_s"]),
            outbox_recover_oldest_age_s=float(values["outbox_recover_oldest_age_s"]),
            degrade_samples=int(values["degrade_samples"]),
            recover_samples=int(values["recover_samples"]),
        ),
        [],
    )
