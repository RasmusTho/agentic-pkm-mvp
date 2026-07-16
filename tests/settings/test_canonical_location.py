from __future__ import annotations

import logging
from pathlib import Path

import pytest

from app.services import settings as system_settings
from app.settings import compiler
from app.settings.health_settings import load_health_settings
from app.settings.migration import migrate_settings_location
from app.settings.watcher_settings import load_watcher_settings
from app.receipts.settings_receipts import query_settings_receipts
from app.vault.manager import VaultManager
from app.write_guard import WritesBlockedError


def _write_settings_markdown(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# Settings\n\n```yaml settings\n{payload}```\n", encoding="utf-8")


def test_all_stacks_read_canonical_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault = tmp_path / "vault"
    result = VaultManager().initialize_vault(vault, remember=False)
    settings = vault / "settings"

    _write_settings_markdown(settings / "global.md", "log_level: DEBUG\n")
    (settings / "watchers.md").write_text(
        "---\nauto_run:\n  allowed_actions: [promote.evergreen, test.action]\n---\n",
        encoding="utf-8",
    )
    (settings / "system-settings.md").write_text(
        Path("vault/settings/system-settings.md").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (settings / "health.md").write_text(
        "---\nthresholds:\n  outbox_degrade_oldest_age_s: 91\n  outbox_recover_oldest_age_s: 5\n  degrade_samples: 3\n  recover_samples: 10\n---\n# Health\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(compiler, "RUNTIME", tmp_path / "runtime" / "settings")
    bundle = compiler.compile_all(vault_root=vault, auto_heal=False)
    assert bundle.global_.log_level == "DEBUG"
    assert "test.action" in load_watcher_settings(vault).allowed_actions
    assert system_settings.load_settings(force=True, path=settings / "system-settings.md")["sync"]["debounce_ms"] == 1200
    assert load_health_settings(vault_root=vault).settings.thresholds.outbox_degrade_oldest_age_s == 91
    assert result.context.settings_path == str(settings)
    assert not (vault / "@Settings").exists()
    assert not (vault / "_system" / "settings").exists()
    assert not (vault / "_system" / "Settings").exists()


def test_legacy_compat_and_shadowing(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    vault = tmp_path / "vault"
    legacy = vault / "@Settings" / "watchers.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(
        "---\nauto_run:\n  allowed_actions: [legacy.action]\n---\n",
        encoding="utf-8",
    )

    with caplog.at_level(logging.WARNING, logger="app.settings.locations"):
        assert "legacy.action" in load_watcher_settings(vault).allowed_actions
    assert "deprecated settings location" in caplog.text
    assert "settings/watchers.md" in caplog.text

    caplog.clear()
    canonical = vault / "settings" / "watchers.md"
    canonical.parent.mkdir(parents=True)
    canonical.write_text(
        "---\nauto_run:\n  allowed_actions: [canonical.action]\n---\n",
        encoding="utf-8",
    )
    with caplog.at_level(logging.WARNING, logger="app.settings.locations"):
        loaded = load_watcher_settings(vault)
    assert "canonical.action" in loaded.allowed_actions
    assert "legacy.action" not in loaded.allowed_actions
    assert "shadowed legacy settings" in caplog.text


def test_migration_is_governed_and_receipted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault = tmp_path / "vault"
    legacy = vault / "@Settings" / "global.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("# legacy\n", encoding="utf-8")
    legacy_system = vault / "_system" / "settings" / "system-settings.yaml"
    legacy_system.parent.mkdir(parents=True)
    legacy_system.write_text("sync:\n  debounce_ms: 99\n", encoding="utf-8")
    legacy_health = vault / "_system" / "Settings" / "health.md"
    legacy_health.parent.mkdir(parents=True, exist_ok=True)
    legacy_health.write_text("# health\n", encoding="utf-8")

    class DenyGuard:
        def assert_writes_allowed(self, action: str) -> None:
            raise WritesBlockedError("blocked", "blocked for test", action)

    with pytest.raises(WritesBlockedError):
        migrate_settings_location(vault, write_guard=DenyGuard())  # type: ignore[arg-type]
    assert legacy.exists()
    assert not (vault / "settings" / "global.md").exists()

    actions: list[str] = []
    outbox_path = tmp_path / "settings-receipts.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("STORE_BACKEND", "memory")

    class AllowGuard:
        def assert_writes_allowed(self, action: str) -> None:
            actions.append(action)

    receipt = migrate_settings_location(vault, write_guard=AllowGuard())  # type: ignore[arg-type]

    assert actions == ["settings.location.migrate"]
    assert (vault / "settings" / "global.md").read_text(encoding="utf-8") == "# legacy\n"
    system_md = (vault / "settings" / "system-settings.md").read_text(encoding="utf-8")
    assert system_md.startswith("---\nsync:\n")
    assert system_md.endswith("# System settings\n")
    assert (vault / "settings" / "health.md").read_text(encoding="utf-8") == "# health\n"
    assert not (vault / "@Settings").exists()
    assert not (vault / "_system" / "settings").exists()
    assert not (vault / "_system" / "Settings").exists()
    assert receipt.surface == "migration"
    assert receipt.actor == "operator"
    assert receipt.file == str(vault / "settings")
    durable = query_settings_receipts(outbox_path=outbox_path)
    assert len(durable.rows) == 1
    assert durable.rows[0].key == "settings.location"
    assert durable.rows[0].actor == "operator"
    assert durable.rows[0].surface == "migration"


def test_migration_refuses_canonical_legacy_conflict_before_guard(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    canonical = vault / "settings" / "global.md"
    legacy = vault / "@Settings" / "global.md"
    canonical.parent.mkdir(parents=True)
    legacy.parent.mkdir(parents=True)
    canonical.write_text("# canonical\n", encoding="utf-8")
    legacy.write_text("# legacy\n", encoding="utf-8")
    guard_calls: list[str] = []

    class Guard:
        def assert_writes_allowed(self, action: str) -> None:
            guard_calls.append(action)

    with pytest.raises(FileExistsError, match="never guesses|conflicts"):
        migrate_settings_location(vault, write_guard=Guard())  # type: ignore[arg-type]

    assert guard_calls == []
    assert canonical.read_text(encoding="utf-8") == "# canonical\n"
    assert legacy.read_text(encoding="utf-8") == "# legacy\n"
