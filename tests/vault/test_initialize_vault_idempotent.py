"""initialize_vault scaffolds a bootable vault and is idempotent (no overwrite) — #1991."""

from __future__ import annotations

from pathlib import Path

from app.vault.manager import VaultManager

SHARED_FILES = ("vault.md", "paths.md", "workflow.md", "design-handoff.md", "companion-ui.md")


def test_init_creates_settings_and_selects(tmp_path: Path) -> None:
    result = VaultManager().initialize_vault(
        tmp_path / "Midgård", vault_name="Midgård", machine_role="primary", remember=False
    )
    assert result.context.status == "selected"
    created = set(result.created_files)
    for name in SHARED_FILES:
        assert any(c.endswith(name) for c in created), f"missing {name}"
    # local.md (per-machine) must also be scaffolded so the watcher is enabled.
    assert any(c.endswith("local.md") for c in created)


def test_init_then_reinit_no_overwrite(tmp_path: Path) -> None:
    vault = tmp_path / "Midgård"
    first = VaultManager().initialize_vault(
        vault, vault_name="Midgård", machine_role="primary", remember=False
    )
    vault_md_rel = next(c for c in first.created_files if c.endswith("vault.md"))
    vault_md = vault / vault_md_rel
    tampered = vault_md.read_text(encoding="utf-8") + "\n<!-- operator note -->\n"
    vault_md.write_text(tampered, encoding="utf-8")

    second = VaultManager().initialize_vault(
        vault, vault_name="Different Name", machine_role="primary", remember=False
    )
    # Idempotent: nothing re-created, existing content preserved.
    assert second.created_files == ()
    assert second.context.status == "selected"
    assert "<!-- operator note -->" in vault_md.read_text(encoding="utf-8")
