"""Runtime environment selection for dev and prod.

This module provides explicit environment selection semantics that map current
PKM_SETTINGS_PROFILE tiering (operator/lab) into a unified dev/prod model without
breaking existing behavior.

Current mapping:
- PKM_SETTINGS_PROFILE=operator (default) -> environment='prod'
- PKM_SETTINGS_PROFILE=lab -> environment='dev'
- Explicit PKM_ENVIRONMENT overrides both

Authority: SoT v5.5 Baseline Definition + forward-line environment modeling
"""

from __future__ import annotations

import os
from typing import Literal

ENV_VARIABLE = "PKM_ENVIRONMENT"
PROFILE_ENV = "PKM_SETTINGS_PROFILE"

ENV_DEV = "dev"
ENV_PROD = "prod"

Environment = Literal["dev", "prod"]


def resolve_environment(env: dict[str, str] | None = None) -> Environment:
    """Resolve the runtime environment.

    Resolution order:
    1. Explicit PKM_ENVIRONMENT (dev or prod)
    2. PKM_SETTINGS_PROFILE mapping: lab -> dev, operator -> prod
    3. Default: prod (production-safe default)

    Args:
        env: Optional environment dict for testing; defaults to os.environ

    Returns:
        'dev' or 'prod'

    Raises:
        ValueError: If PKM_ENVIRONMENT has an invalid value
    """
    env_map = os.environ if env is None else env

    # Check explicit environment override
    explicit = env_map.get(ENV_VARIABLE, "").strip().lower()
    if explicit:
        if explicit in (ENV_DEV, ENV_PROD):
            return explicit  # type: ignore
        raise ValueError(
            f"Invalid {ENV_VARIABLE}={explicit}; must be 'dev' or 'prod'"
        )

    # Fall back to settings profile mapping
    profile = env_map.get(PROFILE_ENV, "").strip().lower()
    if profile == "lab":
        return ENV_DEV

    # Default to prod (operator profile or no profile set)
    return ENV_PROD


def is_dev_environment(env: dict[str, str] | None = None) -> bool:
    """Check if running in dev environment."""
    return resolve_environment(env) == ENV_DEV


def is_prod_environment(env: dict[str, str] | None = None) -> bool:
    """Check if running in prod environment."""
    return resolve_environment(env) == ENV_PROD


__all__ = [
    "ENV_VARIABLE",
    "PROFILE_ENV",
    "ENV_DEV",
    "ENV_PROD",
    "Environment",
    "resolve_environment",
    "is_dev_environment",
    "is_prod_environment",
]
