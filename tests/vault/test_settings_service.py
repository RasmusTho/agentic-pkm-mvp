from __future__ import annotations

from pathlib import Path

import pytest

from app.vault.app_local import AppLocalSettingsStore
from app.vault.manager import VaultContext
from app.vault.settings_service import SettingsService

pytestmark = pytest.mark.not_pg


def _write(path: Path, frontmatter: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(frontmatter, encoding="utf-8")


def _init_shared_vault(vault_root: Path, *, extra: dict[str, str] | None = None) -> Path:
    """Create a minimal selected vault with valid shared/local settings files."""
    settings_dir = vault_root / "settings"
    files = {
        "vault.md": "---\nschema: design-handoff.vault.v1\nscope: vault-shared\nvaultId: vault-test\nvaultName: Test\n---\n",
        "paths.md": (
            "---\nscope: vault-shared\nhandoffFolder: Design Handoff\n"
            "assetsFolder: Design Handoff/Assets\ntemplatesFolder: Design Handoff/Templates\n"
            "archiveFolder: Design Handoff/Archive\n---\n"
        ),
        "workflow.md": "---\nscope: vault-shared\ndefaultStatus: draft\nstatuses: [draft, approved]\n---\n",
        "design-handoff.md": "---\nscope: vault-shared\n---\n",
        "companion-ui.md": "---\nscope: vault-shared\ndefaultView: handoff\n---\n",
        "local.md": "---\nschema: design-handoff.local.v1\nscope: vault-local\nlocalInstanceId: l1\nmachineRole: primary\n---\n",
    }
    if extra:
        files.update(extra)
    for name, content in files.items():
        _write(settings_dir / name, content)
    return settings_dir


def test_app_local_rejects_mismatched_scope(tmp_path: Path) -> None:
    """An app-local source file cannot set a project-scope (vault-shared) key by
    forging ``scope: vault-shared`` in its frontmatter."""
    app_local_path = tmp_path / "app-local.md"
    _write(
        app_local_path,
        "---\nschema: design-handoff.app-local.v1\nscope: vault-shared\nhandoffFolder: HIJACKED\n---\n# app local\n",
    )
    service = SettingsService(app_local_store=AppLocalSettingsStore(path=app_local_path))

    resolution = service.resolve(VaultContext(status="none"))

    handoff = resolution.settings["handoffFolder"]
    # The forged scope must not let an app-local file override a vault-shared key.
    assert handoff.value != "HIJACKED"
    assert handoff.value == "Design Handoff"  # built-in default survives
    assert handoff.scope == "built-in"
    # The mismatch must be surfaced as a validation error, not silently applied.
    assert any(
        err.source_file == str(app_local_path) and "scope" in err.message.lower()
        for err in resolution.validation_errors
    )


def test_vault_shared_definition_file_binding(tmp_path: Path) -> None:
    """A vault-shared key is bound to its declared ``definition.file``; a different
    vault-shared file (read later) cannot override another file's keys."""
    vault_root = tmp_path / "vault"
    # companion-ui.md (read last among shared files) forges handoffFolder, which is
    # owned by paths.md. Without binding it would win by precedence ordering.
    _init_shared_vault(
        vault_root,
        extra={
            "paths.md": (
                "---\nscope: vault-shared\nhandoffFolder: legit_from_paths\n"
                "assetsFolder: Design Handoff/Assets\ntemplatesFolder: Design Handoff/Templates\n"
                "archiveFolder: Design Handoff/Archive\n---\n"
            ),
            "companion-ui.md": "---\nscope: vault-shared\nhandoffFolder: STOLEN_BY_COMPANION\ndefaultView: handoff\n---\n",
        },
    )
    settings_dir = vault_root / "settings"
    context = VaultContext(
        status="selected",
        active_vault_path=str(vault_root),
        settings_path=str(settings_dir),
    )

    resolution = SettingsService().resolve(context)

    handoff = resolution.settings["handoffFolder"]
    assert handoff.value == "legit_from_paths"
    assert handoff.source.endswith("paths.md")
    # The legitimate owner file still sets its own key.
    default_view = resolution.settings["defaultView"]
    assert default_view.value == "handoff"
    assert default_view.source.endswith("companion-ui.md")


def test_vault_local_can_override_shared_key_cross_scope(tmp_path: Path) -> None:
    """The file-binding guard must not block the documented cross-scope override:
    a vault-local file (local.md) overriding a vault-shared key (Codex #2030 P2)."""
    vault_root = tmp_path / "vault"
    _init_shared_vault(
        vault_root,
        extra={
            "local.md": (
                "---\nschema: design-handoff.local.v1\nscope: vault-local\n"
                "localInstanceId: l1\nmachineRole: primary\nhandoffFolder: Local Handoff\n---\n"
            ),
        },
    )
    settings_dir = vault_root / "settings"
    context = VaultContext(
        status="selected",
        active_vault_path=str(vault_root),
        settings_path=str(settings_dir),
    )

    resolution = SettingsService().resolve(context)

    handoff = resolution.settings["handoffFolder"]
    assert handoff.value == "Local Handoff"
    assert handoff.scope == "vault-local"
    assert handoff.source.endswith("local.md")
