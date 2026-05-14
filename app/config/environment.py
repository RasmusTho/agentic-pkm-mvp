"""Runtime environment selection and resolution.

This module provides explicit first-class environment selection for `dev`, `prod`, and `test`,
mapping existing partial controls such as PKM_SETTINGS_PROFILE into the environment model.

Environment selection hierarchy:
1. Explicit PKM_ENVIRONMENT env var (if set to 'dev', 'prod', or 'test')
2. Implicit from PKM_SETTINGS_PROFILE (lab → dev, operator → prod)
3. Default to prod

The environment model is canonical; settings profile (operator/lab) is a narrower control
that lives beneath it for backward compatibility.

Authority: SoT v5.5 Baseline Definition + forward-line environment modeling (Issue #263)
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Literal

# Environment values
ENV_DEV = "dev"
ENV_PROD = "prod"
ENV_TEST = "test"

# Environment variable for explicit selection
ENVIRONMENT_ENV = "PKM_ENVIRONMENT"

# Legacy settings profile variable (for mapping and compatibility)
PROFILE_ENV = "PKM_SETTINGS_PROFILE"
OPERATOR_PROFILE = "operator"
LAB_PROFILE = "lab"


def active_environment(env: Mapping[str, str] | None = None) -> Literal["dev", "prod", "test"]:
    """Resolve the active runtime environment.

    Priority:
    1. Explicit PKM_ENVIRONMENT (if set to 'dev', 'prod', or 'test')
    2. Implicit from PKM_SETTINGS_PROFILE ('lab' → dev, 'operator' → prod)
    3. Default to 'prod'

    Args:
        env: Optional environment mapping (defaults to os.environ)

    Returns:
        'dev', 'prod', or 'test'

    Raises:
        ValueError: If PKM_ENVIRONMENT has an invalid value
    """
    env_map = os.environ if env is None else env

    # Check explicit environment selection
    explicit = str(env_map.get(ENVIRONMENT_ENV, "") or "").strip().lower()
    if explicit:
        if explicit == ENV_DEV:
            return ENV_DEV
        if explicit == ENV_PROD:
            return ENV_PROD
        if explicit == ENV_TEST:
            return ENV_TEST
        raise ValueError(
            f"Invalid {ENVIRONMENT_ENV}={explicit}; must be 'dev', 'prod', or 'test'"
        )

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


def is_test_environment(env: Mapping[str, str] | None = None) -> bool:
    """Check if the active environment is 'test'."""
    return active_environment(env) == ENV_TEST


__all__ = [
    "ENV_DEV",
    "ENV_PROD",
    "ENV_TEST",
    "ENVIRONMENT_ENV",
    "PROFILE_ENV",
    "OPERATOR_PROFILE",
    "LAB_PROFILE",
    "active_environment",
    "is_dev_environment",
    "is_prod_environment",
    "is_test_environment",
]
