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
from app.vault.paths import get_vault_system_dir_rel
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
                relative = source.relative_to(compiled)
                if relative == Path("system-settings.yaml"):
                    mappings.append((source, Path("system-settings.md"), "yaml_to_markdown"))
                else:
                    mappings.append((source, relative, None))

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

    for legacy_health in _legacy_health_paths(vault_root):
        if legacy_health.is_file():
            mappings.append((legacy_health, Path("health.md"), None))
    return mappings


def _target_text(source: Path, transform: str | None) -> str:
    raw = source.read_text(encoding="utf-8")
    return _markdown_from_yaml(raw) if transform == "yaml_to_markdown" else raw


def _legacy_health_paths(root: Path) -> tuple[Path, ...]:
    resolved_root = root.resolve()
    paths = {resolved_root / LEGACY_HEALTH_SETTINGS}
    try:
        configured_system_dir = Path(get_vault_system_dir_rel(resolved_root))
    except (OSError, ValueError):
        pass
    else:
        configured_health = (resolved_root / configured_system_dir / "Settings" / "health.md").resolve()
        if not configured_health.is_relative_to(resolved_root):
            raise ValueError(
                "configured legacy health settings path escapes vault root: "
                f"{configured_health}"
            )
        paths.add(configured_health)
    return tuple(sorted(paths, key=str))


def _prepared_mappings(
    canonical: Path,
    mappings: list[tuple[Path, Path, str | None]],
) -> list[tuple[Path, Path, str]]:
    """Validate all sources before the guard and collapse identical aliases."""

    prepared: list[tuple[Path, Path, str]] = []
    by_target: dict[Path, tuple[Path, str]] = {}
    for source, relative, transform in mappings:
        text = _target_text(source, transform)
        prior = by_target.get(relative)
        if prior is not None:
            prior_source, prior_text = prior
            if prior_text != text:
                raise FileExistsError(
                    "legacy settings sources conflict at canonical target: "
                    f"{prior_source} and {source} both map to {canonical / relative}"
                )
            continue
        target = canonical / relative
        if target.exists() and target.read_text(encoding="utf-8") != text:
            raise FileExistsError(
                f"canonical settings artifact conflicts with legacy source: {target} shadows {source}"
            )
        by_target[relative] = (source, text)
        prepared.append((source, relative, text))
    return prepared


def _remove_legacy_sources(root: Path) -> None:
    compiled = root / LEGACY_COMPILED_DIR
    if compiled.exists():
        shutil.rmtree(compiled)

    legacy_system_root = (root / LEGACY_SYSTEM_SETTINGS).parent
    if legacy_system_root.exists():
        shutil.rmtree(legacy_system_root)

    for legacy_health in _legacy_health_paths(root):
        if legacy_health.is_file():
            legacy_health.unlink()
        try:
            legacy_health.parent.rmdir()
        except OSError:
            # A compatibility directory may hold unrelated operator files.
            # Only the named health artifact belongs to this migration.
            pass


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
    prepared = _prepared_mappings(canonical, mappings)

    write_guard.assert_writes_allowed(MIGRATION_ACTION)

    canonical.parent.mkdir(parents=True, exist_ok=True)
    staged = Path(tempfile.mkdtemp(prefix=".settings-migrate-", dir=canonical.parent))
    backup = Path(tempfile.mkdtemp(prefix=".settings-before-migration-", dir=canonical.parent))
    backup.rmdir()
    published = False
    try:
        if canonical.exists():
            shutil.copytree(canonical, staged, dirs_exist_ok=True)
        for _source, relative, text in prepared:
            target = staged / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")

        if canonical.exists():
            os.replace(canonical, backup)
        os.replace(staged, canonical)
        published = True

        _remove_legacy_sources(root)
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
        value={"canonical": "settings", "migrated_files": len(prepared)},
        old_value={"canonical": None, "legacy_files": len(prepared)},
        file=str(canonical),
        surface="migration",
        actor="operator",
        is_runtime_gating=False,
    )
    emit_settings_write_receipt(receipt)
    return receipt


__all__ = ["MIGRATION_ACTION", "migrate_settings_location"]
