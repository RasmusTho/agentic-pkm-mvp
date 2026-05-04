"""Tests for environment-aware entrypoint classification and guards.

This test module verifies that CLI entrypoints are explicitly classified as prod,
dev, or lab-only per the environment model defined in ENVIRONMENTS.md.

Focus areas:
- Registry watcher (prod/dev) vs legacy watchers (dev-only)
- Runtime loop (dev-only)
- Startup/reset commands
- Help text clarity for environment classification
"""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from app.cli import cli
from app.config.environment import (
    ENV_DEV,
    ENV_PROD,
    ENVIRONMENT_ENV,
    LAB_PROFILE,
    OPERATOR_PROFILE,
    PROFILE_ENV,
)
from app.settings.tiering import require_lab_profile

pytestmark = pytest.mark.not_pg


class TestWatcherEntrypointClassification:
    """Test that watcher entrypoints are correctly classified by environment."""

    def test_registry_watcher_run_help_documents_prod_facing(self) -> None:
        """Registry watcher run command help should document it as production-facing."""
        runner = CliRunner()
        result = runner.invoke(cli, ["watcher", "run", "--help"])
        assert result.exit_code == 0
        assert "production-facing" in result.output.lower()
        assert "registry watcher" in result.output.lower()

    def test_legacy_vault_watcher_run_help_documents_dev_only(self) -> None:
        """Legacy vault-watcher-run help should clearly mark it as dev-only."""
        runner = CliRunner()
        result = runner.invoke(cli, ["vault-watcher-run", "--help"])
        assert result.exit_code == 0
        assert "dev-only" in result.output.lower()
        assert "legacy" not in result.output.lower()  # "dev-only" is the modern term
        assert "watcher run" in result.output.lower()

    def test_legacy_vault_watcher_daemon_help_documents_dev_only(self) -> None:
        """Legacy vault-watcher-daemon help should clearly mark it as dev-only."""
        runner = CliRunner()
        result = runner.invoke(cli, ["vault-watcher-daemon", "--help"])
        assert result.exit_code == 0
        assert "dev-only" in result.output.lower()
        assert "legacy" not in result.output.lower()  # "dev-only" is the modern term
        assert "watcher run" in result.output.lower()

    def test_vault_watcher_run_requires_lab_profile(self) -> None:
        """vault-watcher-run should enforce lab profile requirement."""
        # When called without PKM_SETTINGS_PROFILE=lab, it should fail
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["vault-watcher-run", "--vault-root", "/tmp/vault"],
            env={},
        )
        assert result.exit_code != 0
        assert "dev-only" in result.output.lower() or "legacy" in result.output.lower()

    def test_vault_watcher_daemon_requires_lab_profile(self) -> None:
        """vault-watcher-daemon should enforce lab profile requirement."""
        # When called without PKM_SETTINGS_PROFILE=lab, it should fail
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["vault-watcher-daemon", "--vault-root", "/tmp/vault"],
            env={},
        )
        assert result.exit_code != 0
        assert "dev-only" in result.output.lower() or "legacy" in result.output.lower()


class TestRuntimeLoopEntrypointClassification:
    """Test that runtime-loop is correctly classified as dev-only."""

    def test_runtime_loop_help_documents_dev_only(self) -> None:
        """runtime-loop help should clearly mark it as dev-only."""
        runner = CliRunner()
        result = runner.invoke(cli, ["runtime-loop", "--help"])
        assert result.exit_code == 0
        assert "dev-only" in result.output.lower()
        assert "watcher run" in result.output.lower()

    def test_runtime_loop_requires_lab_profile(self) -> None:
        """runtime-loop should enforce lab profile requirement."""
        # When called without PKM_SETTINGS_PROFILE=lab, it should fail
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["runtime-loop", "--vault-root", "/tmp/vault"],
            env={},
        )
        assert result.exit_code != 0
        assert "dev-only" in result.output.lower() or "legacy" in result.output.lower()


class TestDevOnlyCommandsClassification:
    """Test that other dev-only commands are classified appropriately."""

    def test_alpha_human_flows_help_documents_dev_only(self) -> None:
        """alpha-human-flows help should clearly mark it as dev-only."""
        runner = CliRunner()
        result = runner.invoke(cli, ["alpha-human-flows", "--help"])
        assert result.exit_code == 0
        assert "dev-only" in result.output.lower() or "testing" in result.output.lower()


class TestRequireLabProfileFunction:
    """Test the require_lab_profile enforcement function."""

    def test_require_lab_profile_passes_in_lab(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """require_lab_profile should pass when PKM_SETTINGS_PROFILE=lab."""
        monkeypatch.setenv(PROFILE_ENV, LAB_PROFILE)
        try:
            require_lab_profile(command_name="test")
        except RuntimeError:
            pytest.fail("require_lab_profile raised when lab profile was set")

    def test_require_lab_profile_fails_in_operator(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """require_lab_profile should fail when PKM_SETTINGS_PROFILE=operator."""
        monkeypatch.setenv(PROFILE_ENV, OPERATOR_PROFILE)
        with pytest.raises(RuntimeError, match="dev-only|legacy"):
            require_lab_profile(command_name="test")

    def test_require_lab_profile_fails_in_prod_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """require_lab_profile should fail when PKM_ENVIRONMENT=prod."""
        monkeypatch.delenv(PROFILE_ENV, raising=False)
        monkeypatch.setenv(ENVIRONMENT_ENV, ENV_PROD)
        with pytest.raises(RuntimeError, match="dev-only|legacy"):
            require_lab_profile(command_name="test")

    def test_require_lab_profile_passes_in_dev_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """require_lab_profile should pass when PKM_ENVIRONMENT=dev."""
        monkeypatch.delenv(PROFILE_ENV, raising=False)
        monkeypatch.setenv(ENVIRONMENT_ENV, ENV_DEV)
        try:
            require_lab_profile(command_name="test")
        except RuntimeError:
            pytest.fail("require_lab_profile raised when dev environment was set")


class TestEnvironmentConsistency:
    """Test that environment classification is consistent across the CLI."""

    def test_prod_facing_commands_are_documented(self) -> None:
        """Production-facing commands should have clear documentation."""
        runner = CliRunner()
        # Registry watcher is production-facing
        result = runner.invoke(cli, ["watcher", "run", "--help"])
        assert result.exit_code == 0
        assert "production" in result.output.lower() or "operator" in result.output.lower()

    def test_dev_only_commands_are_marked(self) -> None:
        """Dev-only commands should explicitly say 'dev-only'."""
        dev_only_commands = [
            ["vault-watcher-run", "--help"],
            ["vault-watcher-daemon", "--help"],
            ["runtime-loop", "--help"],
            ["alpha-human-flows", "--help"],
        ]
        runner = CliRunner()
        for cmd_args in dev_only_commands:
            result = runner.invoke(cli, cmd_args)
            assert result.exit_code == 0
            assert (
                "dev-only" in result.output.lower()
                or "legacy" in result.output.lower()
            ), f"Command {cmd_args[0]} should be marked as dev-only in help"
