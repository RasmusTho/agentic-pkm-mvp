from __future__ import annotations

import logging
from pathlib import Path

from app.vault.markdown_settings import MarkdownSettingsStore
from app.vault.app_local import AppLocalSettingsStore
from app.vault.manager import VaultManager


def _manager(tmp_path: Path) -> VaultManager:
    return VaultManager(app_local_store=AppLocalSettingsStore(tmp_path / "app-local.md"))


def test_initial_context_is_none_without_config(tmp_path: Path) -> None:
    manager = _manager(tmp_path)

    assert manager.context.status == "none"


def test_select_missing_path_gives_missing(tmp_path: Path) -> None:
    context = _manager(tmp_path).select_vault(tmp_path / "missing")

    assert context.status == "missing"
    assert context.active_vault_path == str(tmp_path / "missing")


def test_select_existing_uninitialized_folder(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()

    context = _manager(tmp_path).select_vault(vault)

    assert context.status == "uninitialized"
    assert context.settings_path == str(vault / "settings")


def test_initialize_vault_creates_expected_settings_files(tmp_path: Path) -> None:
    vault = tmp_path / "vault"

    result = _manager(tmp_path).initialize_vault(vault, vault_name="Test Vault")

    assert result.context.status == "selected"
    assert result.context.active_vault_name == "Test Vault"
    expected = {
        "settings/vault.md",
        "settings/paths.md",
        "settings/workflow.md",
        "settings/design-handoff.md",
        "settings/companion-ui.md",
        "settings/youtube.md",
        "settings/prompts/ask.md",
        "settings/local.md",
        "settings/.gitignore",
    }
    assert set(result.created_files) == expected
    for rel_path in expected:
        assert (vault / rel_path).exists()


def test_initialize_vault_creates_local_settings_gitignore(tmp_path: Path) -> None:
    vault = tmp_path / "vault"

    _manager(tmp_path).initialize_vault(vault)

    text = (vault / "settings" / ".gitignore").read_text(encoding="utf-8")
    assert "local.md" in text
    assert "*.local.md" in text
    assert "runtime/" in text
    assert "cache/" in text
    assert "*" not in {line.strip() for line in text.splitlines()}


def test_select_initialized_vault_reads_ids(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    manager = _manager(tmp_path)
    initialized = manager.initialize_vault(vault)

    context = manager.select_vault(vault)

    assert context.status == "selected"
    assert context.active_vault_id == initialized.context.active_vault_id
    assert context.local_instance_id == initialized.context.local_instance_id


def test_subscriber_failure_is_logged(tmp_path: Path, caplog) -> None:
    vault = tmp_path / "vault"
    manager = _manager(tmp_path)
    manager.initialize_vault(vault)

    def failing_subscriber(event) -> None:
        raise RuntimeError("subscriber boom")

    manager.subscribe(failing_subscriber)
    caplog.set_level(logging.ERROR, logger="app.vault.manager")

    context = manager.select_vault(vault)

    assert context.status == "selected"
    assert any("vault changed subscriber failed" in record.getMessage() for record in caplog.records)
    assert any(record.exc_info for record in caplog.records)


def test_missing_vault_id_is_stable_across_calls(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    manager = _manager(tmp_path)
    manager.initialize_vault(vault)
    store = MarkdownSettingsStore()
    vault_path = vault / "settings" / "vault.md"
    local_path = vault / "settings" / "local.md"
    vault_doc = store.read(vault_path)
    local_doc = store.read(local_path)
    vault_frontmatter = dict(vault_doc.frontmatter)
    local_frontmatter = dict(local_doc.frontmatter)
    vault_frontmatter.pop("vaultId")
    local_frontmatter.pop("localInstanceId")
    store.write_frontmatter(vault_path, vault_frontmatter, body=vault_doc.body)
    store.write_frontmatter(local_path, local_frontmatter, body=local_doc.body)

    first = manager.validate_vault(vault)
    second = manager.validate_vault(vault)
    selected = manager.select_vault(vault)

    assert first.status == "selected"
    assert first.active_vault_id
    assert first.active_vault_id == second.active_vault_id == selected.active_vault_id
    assert first.local_instance_id
    assert first.local_instance_id == second.local_instance_id == selected.local_instance_id
    assert store.read(vault_path).frontmatter["vaultId"] == first.active_vault_id
    assert store.read(local_path).frontmatter["localInstanceId"] == first.local_instance_id


def test_missing_vault_id_heal_blocked_by_denying_guard_marks_vault_invalid(
    tmp_path: Path, monkeypatch
) -> None:
    """Guard-at-seam (#2910): a denying WriteGuard on the identity-heal write
    is a fail-closed transition, not a silent success or a crash out of vault
    selection. ``_ensure_frontmatter_id`` raises ``WritesBlockedError``;
    ``validate_vault``'s except clause converts it into a loud ``invalid``
    VaultContext (the same branch an ``OSError`` persist failure reaches),
    and the on-disk frontmatter is never partially written.
    """
    from app.write_guard import DEFAULT_WRITE_GUARD

    vault = tmp_path / "vault"
    manager = _manager(tmp_path)
    manager.initialize_vault(vault)
    store = MarkdownSettingsStore()
    vault_path = vault / "settings" / "vault.md"
    vault_doc = store.read(vault_path)
    vault_frontmatter = dict(vault_doc.frontmatter)
    vault_frontmatter.pop("vaultId")
    store.write_frontmatter(vault_path, vault_frontmatter, body=vault_doc.body)
    before = vault_path.read_text(encoding="utf-8")

    monkeypatch.setattr(
        DEFAULT_WRITE_GUARD, "snapshot_fn", lambda: {"state": "safe_mode", "reason": "test-blocked"}
    )
    monkeypatch.setattr(DEFAULT_WRITE_GUARD, "bootstrap_actions", frozenset())

    context = manager.validate_vault(vault)

    assert context.status == "invalid"
    assert context.validation_error is not None
    assert "vault identity" in context.validation_error
    assert vault_path.read_text(encoding="utf-8") == before


def test_conflicted_settings_mark_vault_invalid(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    manager = _manager(tmp_path)
    manager.initialize_vault(vault)
    (vault / "settings" / "vault.md").write_text(
        "---\n<<<<<<< HEAD\nschema: design-handoff.vault.v1\n=======\nschema: other\n>>>>>>> branch\n---\n",
        encoding="utf-8",
    )

    context = manager.select_vault(vault)

    assert context.status == "invalid"
    assert "conflict markers" in str(context.validation_error)
