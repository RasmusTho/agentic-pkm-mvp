"""
Runtime environment selection and resolution.

This module provides explicit first-class environment selection for `dev` and `prod`,
mapping existing partial controls such as PKM_SETTINGS_PROFILE into the environment model.

Environment selection hierarchy:
1. Explicit PKM_ENVIRONMENT env var (if set)
2. Implicit from PKM_SETTINGS_PROFILE (lab → dev, operator → prod)
3. Default to prod

The environment model is canonical; settings profile (operator/lab) is a narrower control
that lives beneath it for backward compatibility.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Literal

# Environment values
ENV_DEV = "dev"
ENV_PROD = "prod"

# Environment variable for explicit selection
ENVIRONMENT_ENV = "PKM_ENVIRONMENT"

# Legacy settings profile variable (for mapping and compatibility)
PROFILE_ENV = "PKM_SETTINGS_PROFILE"
OPERATOR_PROFILE = "operator"
LAB_PROFILE = "lab"


def active_environment(env: Mapping[str, str] | None = None) -> Literal["dev", "prod"]:
    """
    Resolve the active runtime environment.

    Priority:
    1. Explicit PKM_ENVIRONMENT (if set to 'dev' or 'prod')
    2. Implicit from PKM_SETTINGS_PROFILE ('lab' → dev, 'operator' → prod)
    3. Default to 'prod'

    Args:
        env: Optional environment mapping (defaults to os.environ)

    Returns:
        Either 'dev' or 'prod'
    """
    env_map = os.environ if env is None else env

    # Check explicit environment selection
    explicit = str(env_map.get(ENVIRONMENT_ENV, "") or "").strip().lower()
    if explicit == ENV_DEV:
        return ENV_DEV
    if explicit == ENV_PROD:
        return ENV_PROD

    # Fall back to settings profile-based inference
    profile = str(env_map.get(PROFILE_ENV, "") or "").strip().lower()
    if profile == LAB_PROFILE:
        return ENV_DEV
    return ENV_PROD


def is_dev_environment(env: Mapping[str, str] | None = None) -> bool:
    """Check if the active environment is 'dev'."""
    return active_environment(env) == ENV_DEV


def is_prod_environment(env: Mapping[str, str] | None = None) -> bool:
    """Check if the active environment is 'prod'."""
    return active_environment(env) == ENV_PROD


__all__ = [
    "ENV_DEV",
    "ENV_PROD",
    "ENVIRONMENT_ENV",
    "PROFILE_ENV",
    "OPERATOR_PROFILE",
    "LAB_PROFILE",
    "active_environment",
    "is_dev_environment",
    "is_prod_environment",
]
