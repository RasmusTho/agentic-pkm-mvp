"""Tests for runtime environment selection (dev/prod) and settings profile mapping."""

import pytest

from app.config.environment import (
    ENV_DEV,
    ENV_PROD,
    ENVIRONMENT_ENV,
    PROFILE_ENV,
    is_dev_environment,
    is_prod_environment,
    active_environment,
)


class TestEnvironmentResolution:
    """Environment resolution with explicit override and profile fallback."""

    def test_default_prod_when_no_env_set(self) -> None:
        """Default to prod when no environment or profile is set."""
        env: dict[str, str] = {}
        assert active_environment(env) == ENV_PROD
        assert is_prod_environment(env)
        assert not is_dev_environment(env)

    def test_explicit_dev_override(self) -> None:
        """Explicit PKM_ENVIRONMENT=dev takes precedence."""
        env = {ENVIRONMENT_ENV: "dev"}
        assert active_environment(env) == ENV_DEV
        assert is_dev_environment(env)
        assert not is_prod_environment(env)

    def test_explicit_prod_override(self) -> None:
        """Explicit PKM_ENVIRONMENT=prod takes precedence."""
        env = {ENVIRONMENT_ENV: "prod"}
        assert active_environment(env) == ENV_PROD
        assert is_prod_environment(env)
        assert not is_dev_environment(env)

    def test_explicit_override_beats_profile(self) -> None:
        """Explicit PKM_ENVIRONMENT overrides PKM_SETTINGS_PROFILE."""
        env = {ENVIRONMENT_ENV: "prod", PROFILE_ENV: "lab"}
        assert active_environment(env) == ENV_PROD

        env = {ENVIRONMENT_ENV: "dev", PROFILE_ENV: "operator"}
        assert active_environment(env) == ENV_DEV

    def test_profile_lab_maps_to_dev(self) -> None:
        """PKM_SETTINGS_PROFILE=lab maps to dev environment."""
        env = {PROFILE_ENV: "lab"}
        assert active_environment(env) == ENV_DEV
        assert is_dev_environment(env)

    def test_profile_operator_maps_to_prod(self) -> None:
        """PKM_SETTINGS_PROFILE=operator maps to prod environment."""
        env = {PROFILE_ENV: "operator"}
        assert active_environment(env) == ENV_PROD
        assert is_prod_environment(env)

    def test_profile_empty_defaults_to_prod(self) -> None:
        """PKM_SETTINGS_PROFILE empty or unset defaults to prod."""
        env = {PROFILE_ENV: ""}
        assert active_environment(env) == ENV_PROD

        env = {}
        assert active_environment(env) == ENV_PROD

    def test_profile_case_insensitive(self) -> None:
        """Profile matching is case-insensitive."""
        env = {PROFILE_ENV: "LAB"}
        assert active_environment(env) == ENV_DEV

        env = {PROFILE_ENV: "OPERATOR"}
        assert active_environment(env) == ENV_PROD

    def test_env_case_insensitive(self) -> None:
        """Explicit environment matching is case-insensitive."""
        env = {ENVIRONMENT_ENV: "DEV"}
        assert active_environment(env) == ENV_DEV

        env = {ENVIRONMENT_ENV: "PROD"}
        assert active_environment(env) == ENV_PROD

    def test_invalid_explicit_env_raises(self) -> None:
        """Invalid PKM_ENVIRONMENT value raises ValueError."""
        env = {ENVIRONMENT_ENV: "staging"}
        with pytest.raises(ValueError, match="Invalid PKM_ENVIRONMENT"):
            active_environment(env)

        env = {ENVIRONMENT_ENV: "development"}
        with pytest.raises(ValueError, match="Invalid PKM_ENVIRONMENT"):
            active_environment(env)

    def test_whitespace_stripped(self) -> None:
        """Leading/trailing whitespace is stripped."""
        env = {ENVIRONMENT_ENV: "  dev  "}
        assert active_environment(env) == ENV_DEV

        env = {PROFILE_ENV: "  lab  "}
        assert active_environment(env) == ENV_DEV

    def test_resolution_order(self) -> None:
        """Resolution follows: explicit env > profile mapping > default prod."""
        # Step 1: Explicit override
        env = {ENVIRONMENT_ENV: "dev", PROFILE_ENV: "operator"}
        assert active_environment(env) == ENV_DEV

        # Step 2: Profile mapping (when no explicit)
        env = {PROFILE_ENV: "lab"}
        assert active_environment(env) == ENV_DEV

        # Step 3: Default prod (when neither explicit nor profile)
        env = {}
        assert active_environment(env) == ENV_PROD
