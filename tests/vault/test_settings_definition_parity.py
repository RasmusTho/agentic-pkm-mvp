"""Registry parity checks for initialized and routed vault settings files."""

from __future__ import annotations

from app.vault.manager import _initial_settings_files
from app.vault.settings_service import (
    SETTING_DEFINITIONS,
    VAULT_LOCAL_SETTING_FILES,
    VAULT_SHARED_SETTING_FILES,
)
from app.watcher.settings_delta import SCOPED_SETTINGS_FILENAMES


def test_youtube_sync_initializer_seeds_match_registered_defaults() -> None:
    """YSS defaults have one registry source and are faithfully scaffolded."""
    initial_files = {
        filename: frontmatter
        for filename, frontmatter, _body in _initial_settings_files(
            vault_id="vault-test",
            vault_name="Test vault",
            local_instance_id="local-test",
            machine_role="primary",
        )
    }

    for definition in SETTING_DEFINITIONS:
        if not definition.key.startswith("youtubeSync."):
            continue

        expected_file = "local.md" if definition.key == "youtubeSync.runnerEnabled" else "youtube.md"
        assert definition.file == expected_file
        assert initial_files[expected_file][definition.key] == definition.default_value


def test_registered_owner_files_are_routable_by_scope() -> None:
    """Each registered vault owner file reaches its scoped service and watcher path."""
    scoped_files_by_scope = {
        "vault-shared": set(VAULT_SHARED_SETTING_FILES),
        "vault-local": set(VAULT_LOCAL_SETTING_FILES),
    }

    registered_owner_files = {
        definition.file
        for definition in SETTING_DEFINITIONS
        if definition.file is not None
    }
    assert registered_owner_files <= set(SCOPED_SETTINGS_FILENAMES)

    for definition in SETTING_DEFINITIONS:
        if definition.file is None:
            continue
        assert definition.file in scoped_files_by_scope[definition.scope]

    # Parameterized control files remain explicit rather than static seeds.
    assert "vault.md" in VAULT_SHARED_SETTING_FILES
    assert "local.md" in VAULT_LOCAL_SETTING_FILES
    assert {"vault.md", "local.md", "youtube.md"} <= set(SCOPED_SETTINGS_FILENAMES)
