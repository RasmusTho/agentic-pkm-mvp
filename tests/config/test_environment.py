"""Tests for runtime environment selection and resolution."""

from __future__ import annotations

import pytest

from app.config.environment import (
    ENV_DEV,
    ENV_PROD,
    ENVIRONMENT_ENV,
    LAB_PROFILE,
    OPERATOR_PROFILE,
    PROFILE_ENV,
    active_environment,
    is_dev_environment,
    is_prod_environment,
)

pytestmark = pytest.mark.not_pg


class TestEnvironmentResolution:
    """Test environment selection and resolution."""

    def test_default_environment_is_prod(self) -> None:
        """Default environment (no env vars set) should be prod."""
        env = {}
        assert active_environment(env) == ENV_PROD
        assert is_prod_environment(env)
        assert not is_dev_environment(env)

    def test_explicit_dev_environment(self) -> None:
        """Explicit PKM_ENVIRONMENT=dev should select dev."""
        env = {ENVIRONMENT_ENV: "dev"}
        assert active_environment(env) == ENV_DEV
        assert is_dev_environment(env)
        assert not is_prod_environment(env)

    def test_explicit_prod_environment(self) -> None:
        """Explicit PKM_ENVIRONMENT=prod should select prod."""
        env = {ENVIRONMENT_ENV: "prod"}
        assert active_environment(env) == ENV_PROD
        assert is_prod_environment(env)
        assert not is_dev_environment(env)

    def test_explicit_environment_case_insensitive(self) -> None:
        """Environment selection should be case-insensitive."""
        assert active_environment({ENVIRONMENT_ENV: "DEV"}) == ENV_DEV
        assert active_environment({ENVIRONMENT_ENV: "Dev"}) == ENV_DEV
        assert active_environment({ENVIRONMENT_ENV: "PROD"}) == ENV_PROD
        assert active_environment({ENVIRONMENT_ENV: "Prod"}) == ENV_PROD

    def test_explicit_environment_strips_whitespace(self) -> None:
        """Environment selection should strip whitespace."""
        assert active_environment({ENVIRONMENT_ENV: "  dev  "}) == ENV_DEV
        assert active_environment({ENVIRONMENT_ENV: "  prod  "}) == ENV_PROD

    def test_invalid_explicit_environment_raises_value_error(self) -> None:
        """Invalid PKM_ENVIRONMENT values should raise so operators fix their input."""
        with pytest.raises(ValueError):
            active_environment({ENVIRONMENT_ENV: "invalid"})
        assert active_environment({ENVIRONMENT_ENV: ""}) == ENV_PROD
        assert active_environment({ENVIRONMENT_ENV: "   "}) == ENV_PROD

    def test_lab_profile_maps_to_dev_environment(self) -> None:
        """PKM_SETTINGS_PROFILE=lab should map to dev environment."""
        env = {PROFILE_ENV: LAB_PROFILE}
        assert active_environment(env) == ENV_DEV
        assert is_dev_environment(env)
        assert not is_prod_environment(env)

    def test_operator_profile_maps_to_prod_environment(self) -> None:
        """PKM_SETTINGS_PROFILE=operator should map to prod environment."""
        env = {PROFILE_ENV: OPERATOR_PROFILE}
        assert active_environment(env) == ENV_PROD
        assert is_prod_environment(env)
        assert not is_dev_environment(env)

    def test_profile_selection_case_insensitive(self) -> None:
        """Settings profile selection should be case-insensitive."""
        assert active_environment({PROFILE_ENV: "LAB"}) == ENV_DEV
        assert active_environment({PROFILE_ENV: "Lab"}) == ENV_DEV
        assert active_environment({PROFILE_ENV: "OPERATOR"}) == ENV_PROD
        assert active_environment({PROFILE_ENV: "Operator"}) == ENV_PROD

    def test_profile_selection_strips_whitespace(self) -> None:
        """Settings profile selection should strip whitespace."""
        assert active_environment({PROFILE_ENV: "  lab  "}) == ENV_DEV
        assert active_environment({PROFILE_ENV: "  operator  "}) == ENV_PROD

    def test_invalid_profile_defaults_to_prod(self) -> None:
        """Invalid PKM_SETTINGS_PROFILE values should default to prod (operator)."""
        assert active_environment({PROFILE_ENV: "invalid"}) == ENV_PROD
        assert active_environment({PROFILE_ENV: ""}) == ENV_PROD
        assert active_environment({PROFILE_ENV: "   "}) == ENV_PROD

    def test_explicit_environment_takes_priority_over_profile(self) -> None:
        """Explicit PKM_ENVIRONMENT should take priority over PKM_SETTINGS_PROFILE."""
        # dev environment + operator profile → dev (explicit wins)
        env = {ENVIRONMENT_ENV: "dev", PROFILE_ENV: OPERATOR_PROFILE}
        assert active_environment(env) == ENV_DEV

        # prod environment + lab profile → prod (explicit wins)
        env = {ENVIRONMENT_ENV: "prod", PROFILE_ENV: LAB_PROFILE}
        assert active_environment(env) == ENV_PROD


class TestEnvironmentWithOSEnviron:
    """Test environment resolution with actual os.environ."""

    def test_active_environment_uses_os_environ_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """active_environment should use os.environ when no env mapping provided."""
        monkeypatch.setenv(ENVIRONMENT_ENV, "dev")
        assert active_environment() == ENV_DEV

        monkeypatch.delenv(ENVIRONMENT_ENV)
        monkeypatch.setenv(PROFILE_ENV, LAB_PROFILE)
        assert active_environment() == ENV_DEV

        monkeypatch.delenv(PROFILE_ENV)
        assert active_environment() == ENV_PROD

    def test_is_dev_uses_os_environ_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """is_dev_environment should use os.environ when no env mapping provided."""
        monkeypatch.setenv(ENVIRONMENT_ENV, "dev")
        assert is_dev_environment() is True

        monkeypatch.delenv(ENVIRONMENT_ENV)
        assert is_dev_environment() is False

    def test_is_prod_uses_os_environ_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """is_prod_environment should use os.environ when no env mapping provided."""
        monkeypatch.setenv(ENVIRONMENT_ENV, "prod")
        assert is_prod_environment() is True

        monkeypatch.delenv(ENVIRONMENT_ENV)
        assert is_prod_environment() is True


class TestBackwardCompatibility:
    """Test backward compatibility with existing settings profile behavior."""

    def test_existing_lab_profile_continues_to_select_dev(self) -> None:
        """Existing lab profile usage should continue to select dev environment."""
        # Old behavior: PKM_SETTINGS_PROFILE=lab enables dev-only features
        # New behavior: this now maps to dev environment
        env = {PROFILE_ENV: LAB_PROFILE}
        assert active_environment(env) == ENV_DEV

    def test_existing_operator_profile_continues_to_select_prod(self) -> None:
        """Existing operator profile usage should continue to select prod environment."""
        # Old behavior: PKM_SETTINGS_PROFILE=operator (or default) for production
        # New behavior: this now maps to prod environment
        env = {PROFILE_ENV: OPERATOR_PROFILE}
        assert active_environment(env) == ENV_PROD

    def test_no_env_vars_defaults_to_prod_like_operator(self) -> None:
        """No environment variables set should behave like operator profile (prod)."""
        env = {}
        assert active_environment(env) == ENV_PROD
        # This matches the old default behavior where operator was the default profile


class TestDocumentedControlSurface:
    """Test the documented control surface for environment selection."""

    def test_environment_env_constant_defined(self) -> None:
        """ENVIRONMENT_ENV constant should be defined and exportable."""
        assert ENVIRONMENT_ENV == "PKM_ENVIRONMENT"

    def test_profile_env_constant_defined(self) -> None:
        """PROFILE_ENV constant should be defined for documentation."""
        assert PROFILE_ENV == "PKM_SETTINGS_PROFILE"

    def test_constants_for_all_environment_values(self) -> None:
        """Constants should be defined for environment values."""
        assert ENV_DEV == "dev"
        assert ENV_PROD == "prod"

    def test_constants_for_all_profile_values(self) -> None:
        """Constants should be defined for profile values."""
        assert OPERATOR_PROFILE == "operator"
        assert LAB_PROFILE == "lab"
