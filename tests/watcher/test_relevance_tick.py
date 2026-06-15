"""Regression tests for vault-local write permission on the relevance tick (#2015).

The default-on relevance tick previously only checked ``context.status ==
"selected"`` before materializing moments. ``materialize_moment``'s
``DEFAULT_WRITE_GUARD`` is the health/maintenance gate, not the vault-local role
gate, so an ``allowWritesToVault: false`` satellite still received autonomous
background writes. The tick must honor
``VaultManager.permissions_for_context(...).allow_writes_to_vault`` and skip with
a receipted/blocked result when vault-local writes are disabled.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from app.vault.app_local import AppLocalSettingsStore
from app.vault.manager import VaultManager
from app.vault.paths import get_vault_system_dir_rel
from app.watcher.relevance_tick import run_relevance_tick

TODAY = date(2026, 6, 13)


def _seed_vault_content(vault: Path) -> None:
    daily = vault / "Daily" / f"{TODAY.isoformat()}.md"
    daily.parent.mkdir(parents=True, exist_ok=True)
    daily.write_text("---\nuuid: daily-uuid\n---\n\n# Today\n", encoding="utf-8")
    note = vault / "Projects" / "CRE.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text(
        "---\nuuid: cre-uuid\n---\n\n# CRE\n\n- [ ] finish the scarcity gate\n",
        encoding="utf-8",
    )


def _disable_vault_writes(vault: Path) -> None:
    local = vault / "settings" / "local.md"
    text = local.read_text(encoding="utf-8")
    assert "allowWritesToVault" not in text or "allowWritesToVault: true" in text
    # Insert/replace the flag inside the frontmatter block.
    if "allowWritesToVault" in text:
        text = text.replace("allowWritesToVault: true", "allowWritesToVault: false")
    else:
        text = text.replace("scope: vault-local", "scope: vault-local\nallowWritesToVault: false", 1)
    local.write_text(text, encoding="utf-8")


def test_tick_honors_vault_local_write_permission(tmp_path: Path) -> None:
    """The tick skips/receipts a blocked result when vault-local writes are disabled."""

    vault = tmp_path / "vault"
    manager = VaultManager(app_local_store=AppLocalSettingsStore(tmp_path / "app-local.md"))
    context = manager.initialize_vault(vault).context
    assert context.status == "selected"
    _seed_vault_content(vault)
    _disable_vault_writes(vault)

    # Sanity: the permission really is off for this context.
    assert manager.permissions_for_context(context).allow_writes_to_vault is False

    receipts = tmp_path / "moment_receipts.jsonl"
    summary = run_relevance_tick(
        vault,
        vault_context=context,
        outbox_path=receipts,
        reachout_outbox_path=tmp_path / "reachout.jsonl",
    )

    # No autonomous background write landed in the vault.
    moments_dir = vault / get_vault_system_dir_rel(vault) / "moments"
    assert not (moments_dir.is_dir() and list(moments_dir.glob("*.md"))), (
        "an allowWritesToVault:false vault must not get autonomous moment writes"
    )
    assert summary["materialized"] == 0
    assert summary.get("skipped") == "vault-local-writes-disabled"


def test_tick_writes_when_vault_local_writes_allowed(tmp_path: Path) -> None:
    """Control: a normal writable vault still materializes moments."""

    vault = tmp_path / "vault"
    manager = VaultManager(app_local_store=AppLocalSettingsStore(tmp_path / "app-local.md"))
    context = manager.initialize_vault(vault).context
    _seed_vault_content(vault)

    assert manager.permissions_for_context(context).allow_writes_to_vault is True

    summary = run_relevance_tick(
        vault,
        vault_context=context,
        outbox_path=tmp_path / "moment_receipts.jsonl",
        reachout_outbox_path=tmp_path / "reachout.jsonl",
    )
    assert summary["materialized"] >= 1
