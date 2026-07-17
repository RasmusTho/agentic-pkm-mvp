from __future__ import annotations

import logging
import json
import os
from pathlib import Path

import pytest

from app.ingest.config import resolve_ingest_config
from app.services import settings as system_settings
from app.settings import compiler
import app.settings.migration as migration_module
from app.settings.health_settings import load_health_settings
from app.settings.locations import (
    contained_settings_path,
    resolve_compiled_sources,
    resolve_settings_file,
)
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


def test_ingest_override_reads_canonical_root(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    vault = tmp_path / "vault"
    legacy = vault / "⚙️ System" / "settings" / "ingest.override.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(
        "---\ninclude_folders: [Legacy]\nignore_glob: [Legacy/**]\n---\n",
        encoding="utf-8",
    )

    with caplog.at_level(logging.WARNING, logger="app.settings.locations"):
        legacy_config = resolve_ingest_config(vault)
    assert legacy_config.include_folders == ["Legacy"]
    assert "deprecated settings location" in caplog.text

    caplog.clear()
    canonical = vault / "settings" / "ingest.override.md"
    canonical.parent.mkdir(parents=True)
    canonical.write_text(
        "---\ninclude_folders: [Canonical]\nignore_glob: [Canonical/**]\n---\n",
        encoding="utf-8",
    )

    with caplog.at_level(logging.WARNING, logger="app.settings.locations"):
        canonical_config = resolve_ingest_config(vault)
    assert canonical_config.include_folders == ["Canonical"]
    assert "Canonical/**" in canonical_config.ignore_glob
    assert "Legacy/**" not in canonical_config.ignore_glob
    assert "shadowed legacy settings" in caplog.text


@pytest.mark.parametrize("source_root", ["settings", "@Settings"])
def test_settings_source_symlink_must_remain_inside_vault(
    tmp_path: Path, source_root: str
) -> None:
    vault = tmp_path / "vault"
    outside = tmp_path / "outside"
    vault.mkdir()
    outside.mkdir()
    (outside / "global.md").write_text("# outside\n", encoding="utf-8")
    (vault / source_root).symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="escapes vault root|symlink"):
        resolve_settings_file(
            vault,
            "global.md",
            legacy_paths=(Path("@Settings") / "global.md",),
        )
    with pytest.raises(ValueError, match="escapes vault root|symlink"):
        resolve_compiled_sources(vault)

    guard_calls: list[str] = []

    class Guard:
        def assert_writes_allowed(self, action: str) -> None:
            guard_calls.append(action)

    with pytest.raises(ValueError, match="escapes vault root|symlink"):
        migrate_settings_location(vault, write_guard=Guard())  # type: ignore[arg-type]
    assert guard_calls == []
    assert (outside / "global.md").read_text(encoding="utf-8") == "# outside\n"


def test_in_vault_symlinked_settings_root_is_rejected(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    control = vault / ".control"
    control.mkdir(parents=True)
    (control / "providers.md").write_text("# hidden control\n", encoding="utf-8")
    (vault / "settings").symlink_to(control, target_is_directory=True)

    with pytest.raises(ValueError, match="symlink"):
        resolve_settings_file(vault, "providers.md")
    with pytest.raises(ValueError, match="symlink"):
        resolve_compiled_sources(vault)


@pytest.mark.parametrize("candidate_kind", ["absolute", "parent"])
def test_contained_settings_path_rejects_lexical_escape_without_hanging(
    tmp_path: Path, candidate_kind: str
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    candidate = (
        tmp_path / "outside.md"
        if candidate_kind == "absolute"
        else vault / ".." / "outside.md"
    )

    with pytest.raises(ValueError, match="escapes vault root"):
        contained_settings_path(vault, candidate)


def test_resolve_settings_file_rejects_absolute_path_inside_vault(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    rogue = vault / "rogue" / "global.md"
    rogue.parent.mkdir(parents=True)
    rogue.write_text("# rogue\n", encoding="utf-8")

    with pytest.raises(ValueError, match="canonical-relative"):
        resolve_settings_file(vault, rogue)


@pytest.mark.parametrize(
    "legacy_path",
    [Path("../outside/global.md"), Path("/absolute/global.md")],
)
def test_resolve_settings_file_rejects_non_relative_legacy_path(
    tmp_path: Path, legacy_path: Path
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()

    with pytest.raises(ValueError, match="legacy settings path must be vault-relative"):
        resolve_settings_file(vault, "global.md", legacy_paths=(legacy_path,))


def test_migration_rejects_legacy_alias_to_canonical_before_guard(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    canonical = vault / "settings"
    canonical.mkdir(parents=True)
    (canonical / "global.md").write_text("# canonical\n", encoding="utf-8")
    (vault / "@Settings").symlink_to(canonical, target_is_directory=True)
    guard_calls: list[str] = []

    class Guard:
        def assert_writes_allowed(self, action: str) -> None:
            guard_calls.append(action)

    with pytest.raises(ValueError, match="must not be a symlink|symlink"):
        migrate_settings_location(vault, write_guard=Guard())  # type: ignore[arg-type]

    assert guard_calls == []
    assert (canonical / "global.md").read_text(encoding="utf-8") == "# canonical\n"


def test_migration_rejects_legacy_file_symlink_before_guard(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    outside = tmp_path / "outside.md"
    outside.write_text("TOP SECRET\n", encoding="utf-8")
    legacy = vault / "@Settings"
    legacy.mkdir(parents=True)
    (legacy / "global.md").symlink_to(outside)
    guard_calls: list[str] = []

    class Guard:
        def assert_writes_allowed(self, action: str) -> None:
            guard_calls.append(action)

    with pytest.raises(ValueError, match="must not be a symlink|escapes vault root|symlink"):
        migrate_settings_location(vault, write_guard=Guard())  # type: ignore[arg-type]

    assert guard_calls == []
    assert outside.read_text(encoding="utf-8") == "TOP SECRET\n"
    assert not (vault / "settings").exists()


def test_migration_rejects_nested_legacy_directory_symlink_before_guard(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "agent.md").write_text("TOP SECRET\n", encoding="utf-8")
    legacy = vault / "@Settings"
    legacy.mkdir(parents=True)
    (legacy / "agents").symlink_to(outside, target_is_directory=True)
    guard_calls: list[str] = []

    class Guard:
        def assert_writes_allowed(self, action: str) -> None:
            guard_calls.append(action)

    with pytest.raises(ValueError, match="must not be a symlink|escapes vault root|symlink"):
        migrate_settings_location(vault, write_guard=Guard())  # type: ignore[arg-type]

    assert guard_calls == []
    assert (outside / "agent.md").read_text(encoding="utf-8") == "TOP SECRET\n"


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


def test_migration_preserves_unowned_fixed_backup_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault"
    legacy = vault / "@Settings" / "global.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("# legacy\n", encoding="utf-8")
    canonical = vault / "settings" / "watchers.md"
    canonical.parent.mkdir(parents=True)
    canonical.write_text("# canonical\n", encoding="utf-8")
    unowned_backup = vault / ".settings-before-migration"
    unowned_backup.mkdir(parents=True)
    sentinel = unowned_backup / "recovery-copy.md"
    sentinel.write_text("preserve me\n", encoding="utf-8")

    class AllowGuard:
        def assert_writes_allowed(self, action: str) -> None:
            assert action == "settings.location.migrate"

    emitted: list[object] = []
    monkeypatch.setattr(
        "app.settings.migration.emit_settings_write_receipt",
        lambda receipt, **_kwargs: emitted.append(receipt),
    )
    receipt = migrate_settings_location(vault, write_guard=AllowGuard())  # type: ignore[arg-type]

    assert sentinel.read_text(encoding="utf-8") == "preserve me\n"
    assert (vault / "settings" / "global.md").read_text(encoding="utf-8") == "# legacy\n"
    assert canonical.read_text(encoding="utf-8") == "# canonical\n"
    assert emitted == [receipt]
    assert receipt.old_value["canonical"] == "settings"
    assert not list(vault.glob(".settings-before-migration-*"))

    second = migrate_settings_location(vault, write_guard=AllowGuard())  # type: ignore[arg-type]
    assert second.value["migrated_files"] == 0
    assert len(list(vault.glob(".settings-migration-*"))) == 1


def test_migration_cleanup_failure_is_committed_and_receipted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    vault = tmp_path / "vault"
    legacy = vault / "@Settings" / "global.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("# legacy\n", encoding="utf-8")
    emitted: list[object] = []

    class AllowGuard:
        def assert_writes_allowed(self, action: str) -> None:
            assert action == "settings.location.migrate"

    monkeypatch.setattr(
        "app.settings.migration.emit_settings_write_receipt",
        lambda receipt, **_kwargs: emitted.append(receipt),
    )
    monkeypatch.setattr(
        "app.settings.migration._quarantine_legacy_sources",
        lambda _root, _transaction: (_ for _ in ()).throw(OSError("cleanup blocked")),
    )

    with caplog.at_level(logging.WARNING, logger="app.settings.migration"):
        receipt = migrate_settings_location(vault, write_guard=AllowGuard())  # type: ignore[arg-type]

    assert emitted == [receipt]
    assert (vault / "settings" / "global.md").read_text(encoding="utf-8") == "# legacy\n"
    assert legacy.exists()
    assert "legacy cleanup was incomplete" in caplog.text
    assert not list(vault.glob(".settings-before-migration-*"))


def test_migration_receipt_failure_restores_previous_canonical_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault"
    canonical = vault / "settings" / "watchers.md"
    canonical.parent.mkdir(parents=True)
    canonical.write_text("# existing canonical\n", encoding="utf-8")
    legacy = vault / "@Settings" / "global.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("# legacy\n", encoding="utf-8")

    class AllowGuard:
        def assert_writes_allowed(self, action: str) -> None:
            assert action == "settings.location.migrate"

    def _fail_receipt(_receipt: object, **_kwargs: object) -> None:
        raise OSError("receipt unavailable")

    fsync_directories: list[Path] = []
    real_fsync_directory = migration_module._fsync_directory

    def _record_fsync(path: Path) -> None:
        fsync_directories.append(path)
        real_fsync_directory(path)

    monkeypatch.setattr("app.settings.migration.emit_settings_write_receipt", _fail_receipt)
    monkeypatch.setattr("app.settings.migration._fsync_directory", _record_fsync)

    with pytest.raises(OSError, match="receipt unavailable"):
        migrate_settings_location(vault, write_guard=AllowGuard())  # type: ignore[arg-type]

    assert canonical.read_text(encoding="utf-8") == "# existing canonical\n"
    assert not (vault / "settings" / "global.md").exists()
    assert legacy.exists()
    assert not list(vault.glob(".settings-before-migration-*"))
    assert vault in fsync_directories


def test_migration_closes_directory_descriptor_when_lock_acquisition_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault"
    legacy = vault / "@Settings" / "global.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("# legacy\n", encoding="utf-8")
    opened: list[int] = []
    closed: list[int] = []
    real_open = os.open
    real_close = os.close

    class AllowGuard:
        def assert_writes_allowed(self, action: str) -> None:
            assert action == "settings.location.migrate"

    def _record_open(path: Path | str, flags: int) -> int:
        descriptor = real_open(path, flags)
        opened.append(descriptor)
        return descriptor

    def _record_close(descriptor: int) -> None:
        closed.append(descriptor)
        real_close(descriptor)

    monkeypatch.setattr("app.settings.migration.os.open", _record_open)
    monkeypatch.setattr("app.settings.migration.os.close", _record_close)
    monkeypatch.setattr(
        "app.settings.migration.fcntl.flock",
        lambda _descriptor, _operation: (_ for _ in ()).throw(OSError("lock failed")),
    )

    with pytest.raises(OSError, match="lock failed"):
        migrate_settings_location(vault, write_guard=AllowGuard())  # type: ignore[arg-type]

    assert opened
    assert opened[-1] in closed


def test_migration_rechecks_interrupted_transactions_after_lock_wait(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault"
    legacy = vault / "@Settings" / "global.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("# legacy\n", encoding="utf-8")
    interrupted = vault / ".settings-migration-interrupted"
    interrupted.mkdir()
    interrupted_receipt = migration_module.SettingsWriteReceipt(
        key="settings.location",
        value={"canonical": "settings", "migrated_files": 1},
        surface="migration",
        actor="operator",
    )
    migration_module._write_transaction_state(
        interrupted,
        "prepared",
        had_canonical=False,
        receipt=interrupted_receipt,
    )
    discovery_calls = 0
    real_discovery = migration_module._owned_transactions

    class AllowGuard:
        def assert_writes_allowed(self, action: str) -> None:
            assert action == "settings.location.migrate"

    def _appear_after_initial_check(root: Path) -> list[Path]:
        nonlocal discovery_calls
        discovery_calls += 1
        if discovery_calls == 1:
            return []
        return real_discovery(root)

    monkeypatch.setattr(
        "app.settings.migration._owned_transactions", _appear_after_initial_check
    )
    monkeypatch.setattr(
        "app.settings.migration.emit_settings_write_receipt",
        lambda _receipt, **_kwargs: None,
    )

    receipt = migrate_settings_location(vault, write_guard=AllowGuard())  # type: ignore[arg-type]

    interrupted_marker = json.loads(
        (interrupted / "transaction.json").read_text(encoding="utf-8")
    )
    assert interrupted_marker["state"] == "rolled_back"
    assert (vault / "settings" / "global.md").exists()
    assert (vault / receipt.value["recovery"] / "transaction.json").exists()


def test_migration_receipt_failure_preserves_post_publish_canonical_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault"
    canonical = vault / "settings" / "watchers.md"
    canonical.parent.mkdir(parents=True)
    canonical.write_text("# existing canonical\n", encoding="utf-8")
    legacy = vault / "@Settings" / "global.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("# legacy\n", encoding="utf-8")

    class AllowGuard:
        def assert_writes_allowed(self, action: str) -> None:
            assert action == "settings.location.migrate"

    def _write_then_fail(_receipt: object, **_kwargs: object) -> None:
        (vault / "settings" / "late.md").write_text("late\n", encoding="utf-8")
        raise OSError("receipt unavailable")

    monkeypatch.setattr(
        "app.settings.migration.emit_settings_write_receipt", _write_then_fail
    )

    with pytest.raises(OSError, match="receipt unavailable"):
        migrate_settings_location(vault, write_guard=AllowGuard())  # type: ignore[arg-type]

    transaction = next(vault.glob(".settings-migration-*"))
    assert (vault / "settings" / "watchers.md").read_text(
        encoding="utf-8"
    ) == "# existing canonical\n"
    assert (transaction / "published-rollback" / "late.md").read_text(
        encoding="utf-8"
    ) == "late\n"
    assert legacy.exists()


def test_migration_atomic_rollback_preserves_write_after_manifest_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault"
    canonical = vault / "settings" / "watchers.md"
    canonical.parent.mkdir(parents=True)
    canonical.write_text("# existing canonical\n", encoding="utf-8")
    legacy = vault / "@Settings" / "global.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("# legacy\n", encoding="utf-8")
    real_manifest = migration_module._canonical_manifest
    injected = False

    class AllowGuard:
        def assert_writes_allowed(self, action: str) -> None:
            assert action == "settings.location.migrate"

    def _manifest_then_write(
        root: Path, candidate: Path
    ) -> dict[Path, tuple[int, int, int, str]]:
        nonlocal injected
        manifest = real_manifest(root, candidate)
        if candidate.name == "published-rollback" and not injected:
            injected = True
            (candidate / "late.md").write_text("late\n", encoding="utf-8")
        return manifest

    def _fail_receipt(_receipt: object, **_kwargs: object) -> None:
        raise OSError("receipt unavailable")

    monkeypatch.setattr(
        "app.settings.migration.emit_settings_write_receipt", _fail_receipt
    )
    monkeypatch.setattr(
        "app.settings.migration._canonical_manifest", _manifest_then_write
    )

    with pytest.raises(OSError, match="receipt unavailable"):
        migrate_settings_location(vault, write_guard=AllowGuard())  # type: ignore[arg-type]

    transaction = next(vault.glob(".settings-migration-*"))
    assert canonical.read_text(encoding="utf-8") == "# existing canonical\n"
    assert (transaction / "published-rollback" / "late.md").read_text(
        encoding="utf-8"
    ) == "late\n"


def test_migration_concurrent_legacy_change_is_preserved_after_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    vault = tmp_path / "vault"
    legacy = vault / "@Settings" / "global.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("A\n", encoding="utf-8")

    class AllowGuard:
        def assert_writes_allowed(self, action: str) -> None:
            assert action == "settings.location.migrate"

    def _emit_and_change(_receipt: object, **_kwargs: object) -> None:
        legacy.write_text("B\n", encoding="utf-8")
        (legacy.parent / "late.md").write_text("late\n", encoding="utf-8")

    monkeypatch.setattr("app.settings.migration.emit_settings_write_receipt", _emit_and_change)

    with caplog.at_level(logging.WARNING, logger="app.settings.migration"):
        receipt = migrate_settings_location(vault, write_guard=AllowGuard())  # type: ignore[arg-type]

    assert (vault / "settings" / "global.md").read_text(encoding="utf-8") == "A\n"
    recovery = vault / receipt.value["recovery"] / "legacy-recovery" / "compiled"
    assert (recovery / "global.md").read_text(encoding="utf-8") == "B\n"
    assert (recovery / "late.md").read_text(encoding="utf-8") == "late\n"
    assert not legacy.exists()
    assert "all current legacy data will be quarantined" in caplog.text


def test_migration_rejects_new_canonical_file_created_during_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault"
    canonical = vault / "settings" / "watchers.md"
    canonical.parent.mkdir(parents=True)
    canonical.write_text("# existing canonical\n", encoding="utf-8")
    legacy = vault / "@Settings" / "global.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("# legacy\n", encoding="utf-8")
    real_manifest_check = migration_module._legacy_manifest_matches
    injected = False

    class AllowGuard:
        def assert_writes_allowed(self, action: str) -> None:
            assert action == "settings.location.migrate"

    def _inject_canonical_file(root: Path, expected: object) -> bool:
        nonlocal injected
        result = real_manifest_check(root, expected)  # type: ignore[arg-type]
        if not injected:
            injected = True
            (vault / "settings" / "late.md").write_text("late\n", encoding="utf-8")
        return result

    monkeypatch.setattr(
        "app.settings.migration._legacy_manifest_matches", _inject_canonical_file
    )
    monkeypatch.setattr(
        "app.settings.migration.emit_settings_write_receipt",
        lambda _receipt, **_kwargs: None,
    )

    with pytest.raises(RuntimeError, match="changed during migration preparation"):
        migrate_settings_location(vault, write_guard=AllowGuard())  # type: ignore[arg-type]

    assert canonical.read_text(encoding="utf-8") == "# existing canonical\n"
    assert (vault / "settings" / "late.md").read_text(encoding="utf-8") == "late\n"
    assert legacy.exists()


def test_migration_preserves_canonical_write_that_races_after_backup_rename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault"
    canonical_file = vault / "settings" / "watchers.md"
    canonical_file.parent.mkdir(parents=True)
    canonical_file.write_text("# existing canonical\n", encoding="utf-8")
    legacy = vault / "@Settings" / "global.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("# legacy\n", encoding="utf-8")
    real_manifest = migration_module._canonical_manifest
    injected = False

    class AllowGuard:
        def assert_writes_allowed(self, action: str) -> None:
            assert action == "settings.location.migrate"

    def _inject_after_backup(root: Path, candidate: Path):
        nonlocal injected
        result = real_manifest(root, candidate)
        if candidate.name == "canonical-before" and not injected:
            injected = True
            (vault / "settings").mkdir()
            (vault / "settings" / "late.md").write_text("late\n", encoding="utf-8")
        return result

    monkeypatch.setattr("app.settings.migration._canonical_manifest", _inject_after_backup)
    monkeypatch.setattr(
        "app.settings.migration.emit_settings_write_receipt",
        lambda _receipt, **_kwargs: None,
    )

    with pytest.raises(RuntimeError, match="reappeared"):
        migrate_settings_location(vault, write_guard=AllowGuard())  # type: ignore[arg-type]

    assert (vault / "settings" / "late.md").read_text(encoding="utf-8") == "late\n"
    transaction = next(vault.glob(".settings-migration-*"))
    assert (transaction / "canonical-before" / "watchers.md").read_text(
        encoding="utf-8"
    ) == "# existing canonical\n"
    assert legacy.exists()


def test_migration_quarantine_preserves_legacy_write_after_atomic_rename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault"
    legacy_root = vault / "@Settings"
    legacy_root.mkdir(parents=True)
    (legacy_root / "global.md").write_text("A\n", encoding="utf-8")
    real_replace = os.replace
    injected = False

    class AllowGuard:
        def assert_writes_allowed(self, action: str) -> None:
            assert action == "settings.location.migrate"

    def _write_after_quarantine(source: Path | str, target: Path | str) -> None:
        nonlocal injected
        source_path = Path(source)
        target_path = Path(target)
        real_replace(source, target)
        if source_path == legacy_root and target_path.name == "compiled" and not injected:
            injected = True
            legacy_root.mkdir()
            (legacy_root / "late.md").write_text("late\n", encoding="utf-8")

    monkeypatch.setattr("app.settings.migration.os.replace", _write_after_quarantine)
    monkeypatch.setattr(
        "app.settings.migration.emit_settings_write_receipt",
        lambda _receipt, **_kwargs: None,
    )

    receipt = migrate_settings_location(vault, write_guard=AllowGuard())  # type: ignore[arg-type]

    recovery = vault / receipt.value["recovery"] / "legacy-recovery" / "compiled"
    assert (recovery / "global.md").read_text(encoding="utf-8") == "A\n"
    assert (legacy_root / "late.md").read_text(encoding="utf-8") == "late\n"


def test_migration_real_receipt_failure_rolls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault"
    canonical = vault / "settings" / "watchers.md"
    canonical.parent.mkdir(parents=True)
    canonical.write_text("# existing canonical\n", encoding="utf-8")
    legacy = vault / "@Settings" / "global.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("# legacy\n", encoding="utf-8")
    invalid_outbox = tmp_path / "outbox-directory"
    invalid_outbox.mkdir()
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(invalid_outbox))

    class AllowGuard:
        def assert_writes_allowed(self, action: str) -> None:
            assert action == "settings.location.migrate"

    with pytest.raises(RuntimeError, match="durable settings receipt append failed"):
        migrate_settings_location(vault, write_guard=AllowGuard())  # type: ignore[arg-type]

    assert canonical.read_text(encoding="utf-8") == "# existing canonical\n"
    assert not (vault / "settings" / "global.md").exists()
    assert legacy.exists()


def test_migration_parent_fsync_uncertainty_keeps_published_transaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault"
    legacy = vault / "@Settings" / "global.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("# legacy\n", encoding="utf-8")
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(tmp_path / "receipts.jsonl"))
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setattr(
        "app.receipts.settings_write._fsync_parent",
        lambda _path: (_ for _ in ()).throw(OSError("parent fsync failed")),
    )

    class AllowGuard:
        def assert_writes_allowed(self, action: str) -> None:
            assert action == "settings.location.migrate"

    receipt = migrate_settings_location(vault, write_guard=AllowGuard())  # type: ignore[arg-type]

    assert (vault / "settings" / "global.md").exists()
    assert legacy.exists()
    transaction = vault / receipt.value["recovery"]
    marker = json.loads((transaction / "transaction.json").read_text(encoding="utf-8"))
    assert marker["state"] == "published"
    assert len((tmp_path / "receipts.jsonl").read_text(encoding="utf-8").splitlines()) == 1


def test_committed_marker_failure_preserves_owned_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault"
    legacy = vault / "@Settings" / "global.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("# legacy\n", encoding="utf-8")
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(tmp_path / "receipts.jsonl"))
    monkeypatch.setenv("STORE_BACKEND", "memory")
    real_write_state = migration_module._write_transaction_state

    class AllowGuard:
        def assert_writes_allowed(self, action: str) -> None:
            assert action == "settings.location.migrate"

    def _fail_committed(
        transaction: Path,
        state: str,
        **kwargs: object,
    ) -> None:
        if state == "committed":
            raise OSError("marker failed")
        real_write_state(transaction, state, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        "app.settings.migration._write_transaction_state", _fail_committed
    )

    receipt = migrate_settings_location(vault, write_guard=AllowGuard())  # type: ignore[arg-type]

    transaction = vault / receipt.value["recovery"]
    marker = json.loads((transaction / "transaction.json").read_text(encoding="utf-8"))
    assert marker["state"] == "published"
    assert (transaction / "legacy-recovery" / "compiled" / "global.md").exists()


def test_migration_recovers_crash_between_canonical_renames(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault"
    canonical = vault / "settings" / "watchers.md"
    canonical.parent.mkdir(parents=True)
    canonical.write_text("# existing canonical\n", encoding="utf-8")
    legacy = vault / "@Settings" / "global.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("# legacy\n", encoding="utf-8")

    class AllowGuard:
        def assert_writes_allowed(self, action: str) -> None:
            assert action == "settings.location.migrate"

    monkeypatch.setattr(
        "app.settings.migration.emit_settings_write_receipt",
        lambda _receipt, **_kwargs: None,
    )
    real_replace = os.replace
    crashed = False

    def _crash_before_publish(source: Path | str, target: Path | str) -> None:
        nonlocal crashed
        source_path = Path(source)
        target_path = Path(target)
        if (
            not crashed
            and source_path.name.startswith(".settings-migrate-")
            and target_path == vault / "settings"
        ):
            crashed = True
            raise SystemExit("simulated process crash")
        real_replace(source, target)

    monkeypatch.setattr("app.settings.migration.os.replace", _crash_before_publish)
    with pytest.raises(SystemExit, match="simulated process crash"):
        migrate_settings_location(vault, write_guard=AllowGuard())  # type: ignore[arg-type]

    assert not (vault / "settings").exists()
    assert len(list(vault.glob(".settings-migration-*"))) == 1

    monkeypatch.setattr("app.settings.migration.os.replace", real_replace)
    migrate_settings_location(vault, write_guard=AllowGuard())  # type: ignore[arg-type]

    assert canonical.read_text(encoding="utf-8") == "# existing canonical\n"
    assert (vault / "settings" / "global.md").read_text(encoding="utf-8") == "# legacy\n"
    recovery_transactions = list(vault.glob(".settings-migration-*"))
    assert len(recovery_transactions) == 2
    states = {
        json.loads((transaction / "transaction.json").read_text(encoding="utf-8"))[
            "state"
        ]
        for transaction in recovery_transactions
    }
    assert states == {"rolled_back", "committed"}


def test_migration_recovers_published_tree_without_durable_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault"
    canonical = vault / "settings" / "watchers.md"
    canonical.parent.mkdir(parents=True)
    canonical.write_text("# existing canonical\n", encoding="utf-8")
    legacy = vault / "@Settings" / "global.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("# legacy\n", encoding="utf-8")

    class AllowGuard:
        def assert_writes_allowed(self, action: str) -> None:
            assert action == "settings.location.migrate"

    def _crash_before_receipt(_receipt: object, **_kwargs: object) -> None:
        raise SystemExit("simulated crash before durable receipt")

    monkeypatch.setattr(
        "app.settings.migration.emit_settings_write_receipt", _crash_before_receipt
    )
    with pytest.raises(SystemExit, match="before durable receipt"):
        migrate_settings_location(vault, write_guard=AllowGuard())  # type: ignore[arg-type]

    assert (vault / "settings" / "global.md").exists()
    assert len(list(vault.glob(".settings-migration-*"))) == 1

    migration_module._recover_interrupted_transaction(vault, vault / "settings")

    assert canonical.read_text(encoding="utf-8") == "# existing canonical\n"
    assert not (vault / "settings" / "global.md").exists()
    assert legacy.exists()
    transaction = next(vault.glob(".settings-migration-*"))
    marker = json.loads((transaction / "transaction.json").read_text(encoding="utf-8"))
    assert marker["state"] == "rolled_back"
    assert (transaction / "published-rollback" / "global.md").exists()


def test_recovery_preserves_concurrent_canonical_write_when_no_prior_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault"
    legacy = vault / "@Settings" / "global.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("# legacy\n", encoding="utf-8")

    class AllowGuard:
        def assert_writes_allowed(self, action: str) -> None:
            assert action == "settings.location.migrate"

    def _write_then_crash(_receipt: object, **_kwargs: object) -> None:
        (vault / "settings" / "late.md").write_text("late\n", encoding="utf-8")
        raise SystemExit("simulated concurrent crash")

    monkeypatch.setattr(
        "app.settings.migration.emit_settings_write_receipt", _write_then_crash
    )
    with pytest.raises(SystemExit, match="concurrent crash"):
        migrate_settings_location(vault, write_guard=AllowGuard())  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="published settings changed"):
        migration_module._recover_interrupted_transaction(vault, vault / "settings")

    transaction = next(vault.glob(".settings-migration-*"))
    assert (transaction / "published-rollback" / "late.md").read_text(
        encoding="utf-8"
    ) == "late\n"
    assert (transaction / "transaction.json").exists()
    assert legacy.exists()


def test_migration_recovery_keeps_published_tree_after_durable_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault"
    canonical = vault / "settings" / "watchers.md"
    canonical.parent.mkdir(parents=True)
    canonical.write_text("# existing canonical\n", encoding="utf-8")
    legacy = vault / "@Settings" / "global.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("# legacy\n", encoding="utf-8")
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(tmp_path / "receipts.jsonl"))
    monkeypatch.setenv("STORE_BACKEND", "memory")

    class AllowGuard:
        def assert_writes_allowed(self, action: str) -> None:
            assert action == "settings.location.migrate"

    real_write_state = migration_module._write_transaction_state

    def _crash_on_committed_state(
        transaction: Path,
        state: str,
        *,
        had_canonical: bool,
        receipt: object,
        published_manifest: object = None,
    ) -> None:
        if state == "committed":
            raise SystemExit("simulated crash after durable receipt")
        real_write_state(
            transaction,
            state,
            had_canonical=had_canonical,
            receipt=receipt,  # type: ignore[arg-type]
            published_manifest=published_manifest,  # type: ignore[arg-type]
        )

    monkeypatch.setattr(
        "app.settings.migration._write_transaction_state", _crash_on_committed_state
    )
    with pytest.raises(SystemExit, match="after durable receipt"):
        migrate_settings_location(vault, write_guard=AllowGuard())  # type: ignore[arg-type]

    assert (vault / "settings" / "global.md").exists()
    assert len(list(vault.glob(".settings-migration-*"))) == 1

    monkeypatch.setattr(
        "app.settings.migration._write_transaction_state", real_write_state
    )
    recovered = migrate_settings_location(vault, write_guard=AllowGuard())  # type: ignore[arg-type]

    assert canonical.read_text(encoding="utf-8") == "# existing canonical\n"
    assert (vault / "settings" / "global.md").read_text(encoding="utf-8") == "# legacy\n"
    assert not legacy.exists()
    transaction = vault / recovered.value["recovery"]
    assert (transaction / "legacy-recovery" / "compiled" / "global.md").exists()
    marker = json.loads((transaction / "transaction.json").read_text(encoding="utf-8"))
    assert marker["state"] == "committed"
    assert len((tmp_path / "receipts.jsonl").read_text(encoding="utf-8").splitlines()) == 1


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


def test_migration_converts_compiled_legacy_system_yaml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault"
    legacy = vault / "@Settings" / "system-settings.yaml"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("sync:\n  debounce_ms: 41\n", encoding="utf-8")

    class AllowGuard:
        def assert_writes_allowed(self, action: str) -> None:
            assert action == "settings.location.migrate"

    monkeypatch.setattr(
        "app.settings.migration.emit_settings_write_receipt",
        lambda _receipt, **_kwargs: None,
    )
    migrate_settings_location(vault, write_guard=AllowGuard())  # type: ignore[arg-type]

    target = vault / "settings" / "system-settings.md"
    assert target.read_text(encoding="utf-8").startswith("---\nsync:\n")
    assert not (vault / "settings" / "system-settings.yaml").exists()


@pytest.mark.parametrize("legacy_kind", ["empty_compiled", "system_gitkeep"])
def test_no_file_migration_quarantines_retired_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, legacy_kind: str
) -> None:
    vault = tmp_path / "vault"
    if legacy_kind == "empty_compiled":
        retired = vault / "@Settings"
        retired.mkdir(parents=True)
        quarantine_relative = Path("legacy-recovery/compiled")
    else:
        retired = vault / "_system" / "settings"
        retired.mkdir(parents=True)
        (retired / ".gitkeep").write_text("", encoding="utf-8")
        quarantine_relative = Path("legacy-recovery/system")

    class AllowGuard:
        def assert_writes_allowed(self, action: str) -> None:
            assert action == "settings.location.migrate"

    monkeypatch.setattr(
        "app.settings.migration.emit_settings_write_receipt",
        lambda _receipt, **_kwargs: None,
    )

    receipt = migrate_settings_location(vault, write_guard=AllowGuard())  # type: ignore[arg-type]

    transaction = vault / receipt.value["recovery"]
    assert receipt.value["migrated_files"] == 0
    assert not retired.exists()
    assert (transaction / quarantine_relative).is_dir()
    marker = json.loads((transaction / "transaction.json").read_text(encoding="utf-8"))
    assert marker["state"] == "committed"


def test_migration_refuses_colliding_legacy_sources_before_guard(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    compiled = vault / "@Settings" / "system-settings.yaml"
    system = vault / "_system" / "settings" / "system-settings.yaml"
    compiled.parent.mkdir(parents=True)
    system.parent.mkdir(parents=True)
    compiled.write_text("sync:\n  debounce_ms: 41\n", encoding="utf-8")
    system.write_text("sync:\n  debounce_ms: 99\n", encoding="utf-8")
    guard_calls: list[str] = []

    class Guard:
        def assert_writes_allowed(self, action: str) -> None:
            guard_calls.append(action)

    with pytest.raises(FileExistsError, match="legacy settings sources conflict"):
        migrate_settings_location(vault, write_guard=Guard())  # type: ignore[arg-type]

    assert guard_calls == []
    assert compiled.exists() and system.exists()
    assert not (vault / "settings").exists()


def test_migration_preserves_unrelated_uppercase_system_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault"
    legacy_health = vault / "_system" / "Settings" / "health.md"
    unrelated = legacy_health.parent / "operator-note.txt"
    legacy_health.parent.mkdir(parents=True)
    legacy_health.write_text("# health\n", encoding="utf-8")
    unrelated.write_text("keep me\n", encoding="utf-8")

    class AllowGuard:
        def assert_writes_allowed(self, action: str) -> None:
            assert action == "settings.location.migrate"

    monkeypatch.setattr(
        "app.settings.migration.emit_settings_write_receipt",
        lambda _receipt, **_kwargs: None,
    )
    migrate_settings_location(vault, write_guard=AllowGuard())  # type: ignore[arg-type]

    assert (vault / "settings" / "health.md").read_text(encoding="utf-8") == "# health\n"
    preserved = unrelated if unrelated.exists() else vault / "settings" / "operator-note.txt"
    assert preserved.read_text(encoding="utf-8") == "keep me\n"
    assert not legacy_health.exists()


def test_migration_moves_health_from_configured_system_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("VAULT_SYSTEM_DIR_REL", raising=False)
    vault = tmp_path / "vault"
    legacy_system = vault / "_system" / "settings" / "system-settings.yaml"
    legacy_system.parent.mkdir(parents=True)
    legacy_system.write_text("paths:\n  system_dir_rel: Meta\n", encoding="utf-8")
    configured_health = vault / "Meta" / "Settings" / "health.md"
    configured_health.parent.mkdir(parents=True)
    configured_health.write_text("# configured health\n", encoding="utf-8")

    class AllowGuard:
        def assert_writes_allowed(self, action: str) -> None:
            assert action == "settings.location.migrate"

    monkeypatch.setattr(
        "app.settings.migration.emit_settings_write_receipt",
        lambda _receipt, **_kwargs: None,
    )
    migrate_settings_location(vault, write_guard=AllowGuard())  # type: ignore[arg-type]

    assert (vault / "settings" / "health.md").read_text(encoding="utf-8") == "# configured health\n"
    assert not configured_health.exists()


def test_migration_preserves_lowercase_legacy_health(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault"
    legacy_health = vault / "_system" / "settings" / "health.md"
    legacy_health.parent.mkdir(parents=True)
    legacy_health.write_text("# lower health\n", encoding="utf-8")

    class AllowGuard:
        def assert_writes_allowed(self, action: str) -> None:
            assert action == "settings.location.migrate"

    monkeypatch.setattr(
        "app.settings.migration.emit_settings_write_receipt",
        lambda _receipt, **_kwargs: None,
    )
    migrate_settings_location(vault, write_guard=AllowGuard())  # type: ignore[arg-type]

    assert (vault / "settings" / "health.md").read_text(encoding="utf-8") == "# lower health\n"
    assert not legacy_health.exists()


def test_migration_rejects_configured_health_path_outside_vault_before_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("VAULT_SYSTEM_DIR_REL", raising=False)
    vault = tmp_path / "vault"
    legacy_system = vault / "_system" / "settings" / "system-settings.yaml"
    legacy_system.parent.mkdir(parents=True)
    legacy_system.write_text("paths:\n  system_dir_rel: ../outside\n", encoding="utf-8")
    outside_health = tmp_path / "outside" / "Settings" / "health.md"
    outside_health.parent.mkdir(parents=True)
    outside_health.write_text("# must remain\n", encoding="utf-8")
    guard_calls: list[str] = []

    class Guard:
        def assert_writes_allowed(self, action: str) -> None:
            guard_calls.append(action)

    with pytest.raises(ValueError, match="escapes vault root"):
        migrate_settings_location(vault, write_guard=Guard())  # type: ignore[arg-type]

    assert guard_calls == []
    assert outside_health.read_text(encoding="utf-8") == "# must remain\n"
    assert not (vault / "settings").exists()
