from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from app.vault.manager import VaultManager
from app.receipts.settings_write import settings_receipt_old_value
from app.settings.locations import CANONICAL_SETTINGS_DIR_NAME, LEGACY_COMPILED_DIR
from app.vault.markdown_settings import MarkdownSettingsError, MarkdownSettingsStore
from app.vault.settings_service import (
    RUNTIME_GATING_SETTINGS,
    SettingsService,
    SettingsWriteError,
    SettingsWriteReceipt,
)

SETTINGS_LOCAL_REL = Path("settings/local.md")

# Settings source files compile into the effective bundle. A change to one must
# re-ingest so the running services honor
# the edit (SETTINGS-01 / F1) — distinct from the settings/local.md governed-write
# path above.
SETTINGS_SOURCE_DIR_NAME = CANONICAL_SETTINGS_DIR_NAME

# These files belong to the scoped Markdown SettingsService. They share the
# canonical directory with compiler inputs, but remain governed file deltas
# rather than full-bundle compiler sources.
SCOPED_SETTINGS_FILENAMES = frozenset(
    {
        "vault.md",
        "paths.md",
        "workflow.md",
        "design-handoff.md",
        "companion-ui.md",
        "local.md",
    }
)


@dataclass(frozen=True)
class SettingsDeltaResult:
    values: dict[str, Any] | None
    receipts: tuple[SettingsWriteReceipt, ...] = ()
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class SettingsSourceDeltaResult:
    is_source: bool
    reloaded: bool = False
    state: str | None = None
    errors: tuple[str, ...] = ()


def is_settings_source_path(rel_path: Path) -> bool:
    """True for canonical or one-release compatibility source Markdown."""
    if rel_path.suffix != ".md" or not rel_path.parts:
        return False
    if rel_path.parts[0] == LEGACY_COMPILED_DIR.name:
        return True
    return (
        rel_path.parts[0] == SETTINGS_SOURCE_DIR_NAME
        and not (
            len(rel_path.parts) == 2
            and rel_path.name in SCOPED_SETTINGS_FILENAMES
        )
    )


def is_settings_control_path(
    rel_path: Path, *, configured_system_dir: Path | str | None = None
) -> bool:
    """True for canonical and compatibility control-plane Markdown."""

    if rel_path.suffix != ".md" or not rel_path.parts:
        return False
    if rel_path.parts[0] in {SETTINGS_SOURCE_DIR_NAME, LEGACY_COMPILED_DIR.name}:
        return True
    if (
        configured_system_dir is not None
        and rel_path == Path(configured_system_dir) / "Settings" / "health.md"
    ):
        return True
    return rel_path.parts[:2] in {
        ("_system", "settings"),
        ("_system", "Settings"),
    }


def handle_settings_source_delta(
    *, rel_path: Path, vault_settings_dir: Path | None = None, vault_root: Path | None = None
) -> SettingsSourceDeltaResult:
    """Re-ingest effective settings when a settings source file changes.

    Reuses the ingestion entrypoint (compile → ``settings.changed`` bus → reload);
    it adds no second loader. An invalid edit degrades loudly via the ingestion
    state (``degraded_last_valid``) and never crashes the watcher tick.
    """
    if not is_settings_source_path(rel_path):
        return SettingsSourceDeltaResult(is_source=False)

    from app.settings.ingestion import STATE_OK, ingest_settings

    state = ingest_settings(
        reason="watcher_source_delta",
        vault_settings_dir=vault_settings_dir,
        vault_root=vault_root,
        publish_signal=True,
    )
    errors = (state.error,) if state.error else ()
    return SettingsSourceDeltaResult(
        is_source=True,
        reloaded=state.state == STATE_OK,
        state=state.state,
        errors=errors,
    )


def handle_settings_local_delta(
    *,
    vault_root: Path,
    rel_path: Path,
    previous_values: Mapping[str, Any] | None,
    settings_service: SettingsService | None = None,
    markdown_store: MarkdownSettingsStore | None = None,
) -> SettingsDeltaResult:
    """Route watcher-detected runtime-gating settings deltas through the governed seam."""

    if rel_path != SETTINGS_LOCAL_REL:
        return SettingsDeltaResult(values=None)

    store = markdown_store or MarkdownSettingsStore()
    path = vault_root / rel_path
    try:
        document = store.read(path)
    except (FileNotFoundError, OSError, MarkdownSettingsError) as exc:
        return SettingsDeltaResult(values=None, errors=(str(exc),))

    current_values = {
        key: document.frontmatter[key]
        for key in sorted(RUNTIME_GATING_SETTINGS)
        if key in document.frontmatter
    }
    if previous_values is None:
        return SettingsDeltaResult(values=current_values)

    manager = VaultManager(markdown_store=store)
    context = manager.validate_vault(vault_root)
    if context.status != "selected":
        detail = f": {context.validation_error}" if context.validation_error else ""
        return SettingsDeltaResult(
            values=current_values,
            errors=(
                f"settings/local.md delta requires selected vault; status={context.status}{detail}",
            ),
        )

    service = settings_service or SettingsService(markdown_store=store)
    resolution = service.resolve(context)
    previous_keys = set(previous_values)
    current_keys = set(current_values)
    changed_keys = []
    for key in sorted(previous_keys | current_keys):
        current_present = key in current_keys
        previous_present = key in previous_keys
        if current_present != previous_present:
            changed_keys.append(key)
            continue
        if current_present and previous_values.get(key) != current_values[key]:
            changed_keys.append(key)
    if not changed_keys:
        return SettingsDeltaResult(values=current_values)

    receipts: list[SettingsWriteReceipt] = []
    errors: list[str] = []
    for key in changed_keys:
        try:
            persist = key in current_keys
            value = current_values[key] if persist else resolution.settings[key].value
            with settings_receipt_old_value(previous_values.get(key)):
                _effective, receipt = service.update_setting(
                    context,
                    key,
                    value,
                    surface="file",
                    actor="human",
                    persist=persist,
                )
        except SettingsWriteError as exc:
            errors.append(str(exc))
            continue
        receipts.append(receipt)

    return SettingsDeltaResult(
        values=current_values,
        receipts=tuple(receipts),
        errors=tuple(errors),
    )


__all__ = [
    "SETTINGS_LOCAL_REL",
    "SETTINGS_SOURCE_DIR_NAME",
    "SettingsDeltaResult",
    "SettingsSourceDeltaResult",
    "handle_settings_local_delta",
    "handle_settings_source_delta",
    "is_settings_source_path",
    "is_settings_control_path",
]
