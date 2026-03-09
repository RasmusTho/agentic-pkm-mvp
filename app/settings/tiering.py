from __future__ import annotations

import os
from collections.abc import Callable, Mapping
import logging
from typing import TypeVar

PROFILE_ENV = "PKM_SETTINGS_PROFILE"
OPERATOR_PROFILE = "operator"
LAB_PROFILE = "lab"

_WARNED_IGNORED: set[str] = set()
T = TypeVar("T")


def active_settings_profile(env: Mapping[str, str] | None = None) -> str:
    env_map = os.environ if env is None else env
    raw = str(env_map.get(PROFILE_ENV, "") or "").strip().lower()
    if raw == LAB_PROFILE:
        return LAB_PROFILE
    return OPERATOR_PROFILE


def is_lab_profile(env: Mapping[str, str] | None = None) -> bool:
    return active_settings_profile(env) == LAB_PROFILE


def resolve_dev_lab_env_value(
    name: str,
    *,
    default: str,
    env: Mapping[str, str] | None = None,
    logger: logging.Logger | None = None,
) -> str:
    env_map = os.environ if env is None else env
    raw = env_map.get(name)
    if raw is None:
        return default
    if is_lab_profile(env_map):
        return str(raw)
    if logger is not None:
        key = f"{name}:{active_settings_profile(env_map)}"
        if key not in _WARNED_IGNORED:
            _WARNED_IGNORED.add(key)
            logger.warning(
                "ignoring dev/lab setting %s in %s profile; set %s=%s to enable",
                name,
                active_settings_profile(env_map),
                PROFILE_ENV,
                LAB_PROFILE,
            )
    return default


def resolve_dev_lab_env_typed(
    name: str,
    *,
    default: str,
    parser: Callable[[str], T],
    env: Mapping[str, str] | None = None,
    logger: logging.Logger | None = None,
) -> T:
    raw = resolve_dev_lab_env_value(name, default=default, env=env, logger=logger)
    try:
        return parser(raw)
    except Exception:
        return parser(default)


__all__ = [
    "PROFILE_ENV",
    "OPERATOR_PROFILE",
    "LAB_PROFILE",
    "active_settings_profile",
    "is_lab_profile",
    "resolve_dev_lab_env_value",
    "resolve_dev_lab_env_typed",
]
