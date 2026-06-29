from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from app.vault.manager import VaultManager
from app.vault.markdown_settings import MarkdownSettingsError, MarkdownSettingsStore
from app.vault.settings_service import (
    RUNTIME_GATING_SETTINGS,
    SettingsService,
    SettingsWriteError,
    SettingsWriteReceipt,
)

SETTINGS_LOCAL_REL = Path("settings/local.md")


@dataclass(frozen=True)
class SettingsDeltaResult:
    values: dict[str, Any] | None
    receipts: tuple[SettingsWriteReceipt, ...] = ()
    errors: tuple[str, ...] = ()


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

    changed_keys = [
        key
        for key, value in current_values.items()
        if previous_values.get(key) != value
    ]
    if not changed_keys:
        return SettingsDeltaResult(values=current_values)

    manager = VaultManager(markdown_store=store)
    context = manager.validate_vault(vault_root)
    if context.status != "selected":
        detail = f": {context.validation_error}" if context.validation_error else ""
        return SettingsDeltaResult(
            values=current_values,
            errors=(f"settings/local.md delta requires selected vault; status={context.status}{detail}",),
        )

    service = settings_service or SettingsService(markdown_store=store)
    receipts: list[SettingsWriteReceipt] = []
    errors: list[str] = []
    for key in changed_keys:
        try:
            _effective, receipt = service.update_setting(
                context,
                key,
                current_values[key],
                surface="file",
                actor="human",
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
    "SettingsDeltaResult",
    "handle_settings_local_delta",
]
