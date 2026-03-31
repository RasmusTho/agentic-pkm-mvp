"""Tests for environment-scoped artifact path separation (Issue #266).

Verify that dev and prod environments use distinct paths for:
- Vault surfaces
- Store/index/outbox surfaces
- Watcher state and heartbeat files
- Incident logs and runtime artifacts
"""

import pytest
from pathlib import Path
from app.config.paths import resolve_vault_root, resolve_runtime_artifact_path, resolve_paths
from app.settings.watcher_settings import load_watcher_settings


class TestVaultPathSeparation:
    """Test vault path separation by environment."""

    def test_prod_vault_uses_base_path(self):
        """Production environment uses base vault path."""
        prod_path = resolve_vault_root(environment="prod")
        assert str(prod_path) == "vault"

    def test_dev_vault_uses_dev_suffix(self):
        """Development environment uses -dev suffixed vault path."""
        dev_path = resolve_vault_root(environment="dev")
        assert str(dev_path) == "vault-dev"

    def test_vault_paths_are_distinct(self):
        """Dev and prod vault paths are distinct."""
        prod = resolve_vault_root(environment="prod")
        dev = resolve_vault_root(environment="dev")
        assert prod != dev
        assert prod == Path("vault")
        assert dev == Path("vault-dev")

    def test_explicit_override_bypasses_environment_scoping(self):
        """Explicit vault root override bypasses environment scoping."""
        override = Path("custom/vault")
        prod = resolve_vault_root(cli_override=override, environment="prod")
        dev = resolve_vault_root(cli_override=override, environment="dev")
        assert prod == override
        assert dev == override


class TestRuntimeArtifactPathSeparation:
    """Test runtime artifact path separation by environment."""

    def test_prod_artifact_uses_default_path(self):
        """Production artifacts use default tmp/ paths."""
        artifact = Path("tmp/watcher_state.json")
        resolved = resolve_runtime_artifact_path(artifact, environment="prod")
        assert resolved == artifact

    def test_dev_artifact_uses_dev_directory(self):
        """Development artifacts use tmp-dev/ directory."""
        artifact = Path("tmp/watcher_state.json")
        resolved = resolve_runtime_artifact_path(artifact, environment="dev")
        assert str(resolved) == "tmp-dev/watcher_state.json"

    def test_artifact_paths_are_distinct(self):
        """Dev and prod artifact paths are distinct."""
        artifact = Path("tmp/index-outbox.jsonl")
        prod = resolve_runtime_artifact_path(artifact, environment="prod")
        dev = resolve_runtime_artifact_path(artifact, environment="dev")
        assert prod != dev
        assert prod == artifact
        assert str(dev) == "tmp-dev/index-outbox.jsonl"

    def test_multiple_artifacts_separated_by_environment(self):
        """Multiple artifacts are all properly separated."""
        artifacts = [
            Path("tmp/index-outbox.jsonl"),
            Path("tmp/watcher_state.json"),
            Path("tmp/watcher_heartbeat.json"),
            Path("tmp/worker_heartbeat.json"),
        ]
        prod_paths = [resolve_runtime_artifact_path(a, environment="prod") for a in artifacts]
        dev_paths = [resolve_runtime_artifact_path(a, environment="dev") for a in artifacts]

        # Prod paths match originals
        for prod, orig in zip(prod_paths, artifacts):
            assert prod == orig

        # Dev paths are all distinct from prod and have tmp-dev
        for dev, prod in zip(dev_paths, prod_paths):
            assert dev != prod
            assert "tmp-dev" in str(dev)


class TestResolvedPathsWithEnvironment:
    """Test ResolvedPaths structure includes environment."""

    def test_resolved_paths_includes_environment(self):
        """ResolvedPaths includes environment field."""
        resolved = resolve_paths(environment="dev")
        assert resolved.environment == "dev"

    def test_resolved_paths_prod_vault(self):
        """ResolvedPaths for prod has base vault root."""
        resolved = resolve_paths(environment="prod")
        assert resolved.environment == "prod"
        assert resolved.vault_root == Path("vault")

    def test_resolved_paths_dev_vault(self):
        """ResolvedPaths for dev has -dev suffixed vault root."""
        resolved = resolve_paths(environment="dev")
        assert resolved.environment == "dev"
        assert resolved.vault_root == Path("vault-dev")


class TestWatcherSettingsEnvironmentScoping:
    """Test watcher settings use environment-scoped paths."""

    def test_watcher_settings_prod_paths(self):
        """Watcher settings for prod use tmp/ paths."""
        settings = load_watcher_settings(environment="prod")
        assert str(settings.paths.index_outbox) == "tmp/index-outbox.jsonl"
        assert str(settings.paths.watcher_state) == "tmp/watcher_state.json"
        assert str(settings.paths.watcher_heartbeat) == "tmp/watcher_heartbeat.json"

    def test_watcher_settings_dev_paths(self):
        """Watcher settings for dev use tmp-dev/ paths."""
        settings = load_watcher_settings(environment="dev")
        assert str(settings.paths.index_outbox) == "tmp-dev/index-outbox.jsonl"
        assert str(settings.paths.watcher_state) == "tmp-dev/watcher_state.json"
        assert str(settings.paths.watcher_heartbeat) == "tmp-dev/watcher_heartbeat.json"

    def test_watcher_settings_paths_distinct_by_environment(self):
        """Watcher settings prod and dev paths are distinct."""
        prod_settings = load_watcher_settings(environment="prod")
        dev_settings = load_watcher_settings(environment="dev")

        # All paths should be distinct
        assert prod_settings.paths.index_outbox != dev_settings.paths.index_outbox
        assert prod_settings.paths.watcher_state != dev_settings.paths.watcher_state
        assert prod_settings.paths.watcher_heartbeat != dev_settings.paths.watcher_heartbeat


class TestImplicitEnvironmentResolution:
    """Test that environment resolution works when not explicitly provided."""

    def test_vault_implicit_prod_default(self):
        """Without explicit environment, vault defaults to prod path."""
        # This depends on PKM_ENVIRONMENT and PKM_SETTINGS_PROFILE not being set in test
        path = resolve_vault_root()
        # Should resolve to base path (default prod)
        assert "dev" not in str(path)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
