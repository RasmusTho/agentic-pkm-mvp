"""Explicit governed migration into the canonical vault settings root."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from app.settings.locations import (
    LEGACY_COMPILED_DIR,
    LEGACY_HEALTH_SETTINGS,
    LEGACY_SYSTEM_SETTINGS,
    canonical_settings_root,
)
from app.receipts.settings_write import SettingsWriteReceipt, emit_settings_write_receipt
from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard


MIGRATION_ACTION = "settings.location.migrate"


def _markdown_from_yaml(raw: str) -> str:
    return f"---\n{raw.rstrip()}\n---\n\n# System settings\n"


def _migration_files(vault_root: Path) -> list[tuple[Path, Path, str | None]]:
    mappings: list[tuple[Path, Path, str | None]] = []
    compiled = vault_root / LEGACY_COMPILED_DIR
    if compiled.exists():
        for source in sorted(compiled.rglob("*")):
            if source.is_file():
                mappings.append((source, source.relative_to(compiled), None))

    legacy_system_root = (vault_root / LEGACY_SYSTEM_SETTINGS).parent
    if legacy_system_root.exists():
        for source in sorted(legacy_system_root.rglob("*")):
            if not source.is_file():
                continue
            if source.name == ".gitkeep" or source.name.casefold() == "health.md":
                continue
            relative = source.relative_to(legacy_system_root)
            if source == vault_root / LEGACY_SYSTEM_SETTINGS:
                mappings.append((source, Path("system-settings.md"), "yaml_to_markdown"))
            else:
                mappings.append((source, relative, None))

    legacy_health = vault_root / LEGACY_HEALTH_SETTINGS
    if legacy_health.is_file():
        mappings.append((legacy_health, Path("health.md"), None))
    return mappings


def _target_text(source: Path, transform: str | None) -> str:
    raw = source.read_text(encoding="utf-8")
    return _markdown_from_yaml(raw) if transform == "yaml_to_markdown" else raw


def migrate_settings_location(
    vault_root: Path,
    *,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
) -> SettingsWriteReceipt:
    """Atomically publish a canonical settings tree and remove retired roots.

    Conflicting canonical/legacy artifacts fail before the WriteGuard or any
    mutation. The operator must resolve that conflict explicitly; the migration
    never guesses, overwrites, or merges authority-bearing content.
    """

    root = Path(vault_root).expanduser().resolve()
    canonical = canonical_settings_root(root)
    mappings = _migration_files(root)
    for source, relative, transform in mappings:
        target = canonical / relative
        if target.exists() and target.read_text(encoding="utf-8") != _target_text(source, transform):
            raise FileExistsError(
                f"canonical settings artifact conflicts with legacy source: {target} shadows {source}"
            )

    write_guard.assert_writes_allowed(MIGRATION_ACTION)

    canonical.parent.mkdir(parents=True, exist_ok=True)
    staged = Path(tempfile.mkdtemp(prefix=".settings-migrate-", dir=canonical.parent))
    backup = canonical.parent / ".settings-before-migration"
    published = False
    try:
        if canonical.exists():
            shutil.copytree(canonical, staged, dirs_exist_ok=True)
        for source, relative, transform in mappings:
            target = staged / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(_target_text(source, transform), encoding="utf-8")

        if backup.exists():
            shutil.rmtree(backup)
        if canonical.exists():
            os.replace(canonical, backup)
        os.replace(staged, canonical)
        published = True

        for legacy in (
            root / LEGACY_COMPILED_DIR,
            (root / LEGACY_SYSTEM_SETTINGS).parent,
            (root / LEGACY_HEALTH_SETTINGS).parent,
        ):
            if legacy.exists():
                shutil.rmtree(legacy)
        if backup.exists():
            shutil.rmtree(backup)
    except Exception:
        if not published and backup.exists() and not canonical.exists():
            os.replace(backup, canonical)
        raise
    finally:
        if staged.exists():
            shutil.rmtree(staged, ignore_errors=True)

    receipt = SettingsWriteReceipt(
        key="settings.location",
        value={"canonical": "settings", "migrated_files": len(mappings)},
        old_value={"canonical": None, "legacy_files": len(mappings)},
        file=str(canonical),
        surface="migration",
        actor="operator",
        is_runtime_gating=False,
    )
    emit_settings_write_receipt(receipt)
    return receipt


__all__ = ["MIGRATION_ACTION", "migrate_settings_location"]
