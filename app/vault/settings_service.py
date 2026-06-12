from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from app.vault.manager import VaultContext
from app.vault.markdown_settings import MarkdownSettingsError, MarkdownSettingsStore


SettingScope = Literal["built-in", "app-local", "vault-shared", "vault-local", "runtime"]
SettingType = Literal["string", "boolean", "number", "enum", "path", "array", "object"]
SyncPolicy = Literal["commit", "gitignore", "never-store", "secret-ref-only"]


@dataclass(frozen=True)
class SettingDefinition:
    key: str
    type: SettingType
    default_value: Any
    description: str
    scope: SettingScope
    sync_policy: SyncPolicy
    requires_vault: bool
    editable_in_companion: bool
    editable_in_obsidian: bool
    file: str | None = None
    allowed_machine_roles: tuple[str, ...] = ()


@dataclass(frozen=True)
class EffectiveSetting:
    key: str
    value: Any
    scope: SettingScope
    source: str


SETTING_DEFINITIONS: tuple[SettingDefinition, ...] = (
    SettingDefinition("settingsFolder", "path", "settings", "Vault settings folder.", "built-in", "commit", False, False, True),
    SettingDefinition("handoffFolder", "path", "Design Handoff", "Design Handoff root folder.", "vault-shared", "commit", True, True, True, "paths.md"),
    SettingDefinition("assetsFolder", "path", "Design Handoff/Assets", "Handoff assets folder.", "vault-shared", "commit", True, True, True, "paths.md"),
    SettingDefinition("templatesFolder", "path", "Design Handoff/Templates", "Handoff templates folder.", "vault-shared", "commit", True, True, True, "paths.md"),
    SettingDefinition("archiveFolder", "path", "Design Handoff/Archive", "Handoff archive folder.", "vault-shared", "commit", True, True, True, "paths.md"),
    SettingDefinition("defaultWorkflowStatus", "string", "draft", "Default workflow status.", "vault-shared", "commit", True, True, True, "workflow.md"),
    SettingDefinition("workflowStatuses", "array", ["draft", "in-review", "approved", "archived"], "Workflow statuses.", "vault-shared", "commit", True, True, True, "workflow.md"),
    SettingDefinition("autoCreateAssetFolders", "boolean", True, "Create asset folders automatically.", "vault-shared", "commit", True, True, True, "design-handoff.md"),
    SettingDefinition("preserveOriginalFileNames", "boolean", True, "Preserve original imported filenames.", "vault-shared", "commit", True, True, True, "design-handoff.md"),
    SettingDefinition("generateIndexOnChange", "boolean", True, "Generate index on change.", "vault-shared", "commit", True, True, True, "design-handoff.md"),
    SettingDefinition("defaultView", "string", "handoff", "Companion UI default view.", "vault-shared", "commit", True, True, True, "companion-ui.md"),
    SettingDefinition("showAdvancedSettings", "boolean", False, "Show advanced settings.", "vault-shared", "commit", True, True, True, "companion-ui.md"),
    SettingDefinition("autoRefresh", "boolean", True, "Refresh UI automatically.", "vault-shared", "commit", True, True, True, "companion-ui.md"),
    SettingDefinition("enableVaultWatcher", "boolean", True, "Enable local vault watcher.", "vault-local", "gitignore", True, True, True, "local.md"),
    SettingDefinition("enableAutoIndexing", "boolean", True, "Enable local auto indexing.", "vault-local", "gitignore", True, True, True, "local.md"),
    SettingDefinition("allowWritesToVault", "boolean", True, "Allow local writes to vault project files.", "vault-local", "gitignore", True, True, True, "local.md"),
    SettingDefinition("allowSharedSettingsEdits", "boolean", True, "Allow editing shared settings from this clone.", "vault-local", "gitignore", True, True, True, "local.md"),
    SettingDefinition("allowLocalSettingsEdits", "boolean", True, "Allow editing local settings from this clone.", "vault-local", "gitignore", True, True, True, "local.md"),
    SettingDefinition("localExportPath", "path", None, "Machine-local export path.", "vault-local", "gitignore", True, True, True, "local.md"),
    SettingDefinition("machineRole", "enum", "primary", "Local machine role.", "vault-local", "gitignore", True, True, True, "local.md"),
    SettingDefinition("syncRole", "string", "local", "Local sync role.", "vault-local", "gitignore", True, True, True, "local.md"),
)


class SettingsService:
    def __init__(self, markdown_store: MarkdownSettingsStore | None = None) -> None:
        self.markdown_store = markdown_store or MarkdownSettingsStore()

    def effective_settings(self, context: VaultContext) -> dict[str, EffectiveSetting]:
        values = {
            definition.key: EffectiveSetting(
                key=definition.key,
                value=definition.default_value,
                scope="built-in",
                source="built-in",
            )
            for definition in SETTING_DEFINITIONS
        }
        if context.status != "selected" or not context.settings_path:
            return values

        settings_dir = Path(context.settings_path)
        for definition in SETTING_DEFINITIONS:
            if definition.file is None:
                continue
            path = settings_dir / definition.file
            try:
                doc = self.markdown_store.read(path)
            except (OSError, MarkdownSettingsError):
                continue
            if definition.key in doc.frontmatter:
                values[definition.key] = EffectiveSetting(
                    key=definition.key,
                    value=doc.frontmatter[definition.key],
                    scope=definition.scope,
                    source=str(path),
                )
            elif definition.key == "defaultWorkflowStatus" and "defaultStatus" in doc.frontmatter:
                values[definition.key] = EffectiveSetting(
                    key=definition.key,
                    value=doc.frontmatter["defaultStatus"],
                    scope=definition.scope,
                    source=str(path),
                )
            elif definition.key == "workflowStatuses" and "statuses" in doc.frontmatter:
                values[definition.key] = EffectiveSetting(
                    key=definition.key,
                    value=doc.frontmatter["statuses"],
                    scope=definition.scope,
                    source=str(path),
                )
        return values


__all__ = [
    "EffectiveSetting",
    "SETTING_DEFINITIONS",
    "SettingDefinition",
    "SettingsService",
]
