from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, NamedTuple, TypeAlias, Literal

from app.vault.app_local import AppLocalSettingsStore
from app.vault.manager import VaultContext
from app.vault.markdown_settings import MarkdownSettingsDocument, MarkdownSettingsError, MarkdownSettingsStore


SettingScope = Literal["built-in", "app-local", "vault-shared", "vault-local", "runtime"]
SettingType = Literal["string", "boolean", "number", "enum", "path", "array", "object"]
SyncPolicy = Literal["commit", "gitignore", "never-store", "secret-ref-only"]
_ValidationResult: TypeAlias = tuple[bool, str | None]


VAULT_SHARED_SETTING_FILES = (
    "vault.md",
    "paths.md",
    "workflow.md",
    "design-handoff.md",
    "companion-ui.md",
)
VAULT_LOCAL_SETTING_FILES = ("local.md",)
VALID_SOURCE_SCOPES = {"app-local", "vault-shared", "vault-local"}


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
    allowed_values: tuple[Any, ...] = ()
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class EffectiveSetting:
    key: str
    value: Any
    scope: SettingScope
    source: str
    source_file: str | None = None


@dataclass(frozen=True)
class SettingsValidationError:
    message: str
    source_file: str | None = None
    scope: SettingScope | None = None
    key: str | None = None


@dataclass(frozen=True)
class SettingsResolution:
    settings: dict[str, EffectiveSetting]
    validation_errors: tuple[SettingsValidationError, ...] = ()


class _SourceDocument(NamedTuple):
    path: Path
    scope: SettingScope
    document: MarkdownSettingsDocument


class SettingsRegistry:
    def __init__(self, definitions: tuple[SettingDefinition, ...] = ()) -> None:
        self._definitions = definitions or SETTING_DEFINITIONS
        self._by_key = {definition.key: definition for definition in self._definitions}

    @property
    def definitions(self) -> tuple[SettingDefinition, ...]:
        return self._definitions

    def get(self, key: str) -> SettingDefinition | None:
        return self._by_key.get(key)


SETTING_DEFINITIONS: tuple[SettingDefinition, ...] = (
    SettingDefinition("settingsFolder", "path", "settings", "Vault settings folder.", "built-in", "commit", False, False, True),
    SettingDefinition(
        "appInstallId",
        "string",
        None,
        "Local application install identity.",
        "app-local",
        "never-store",
        False,
        False,
        False,
    ),
    SettingDefinition(
        "lastActiveVaultRef",
        "string",
        None,
        "Last active local vault reference.",
        "app-local",
        "never-store",
        False,
        False,
        False,
    ),
    SettingDefinition("handoffFolder", "path", "Design Handoff", "Design Handoff root folder.", "vault-shared", "commit", True, True, True, "paths.md"),
    SettingDefinition("assetsFolder", "path", "Design Handoff/Assets", "Handoff assets folder.", "vault-shared", "commit", True, True, True, "paths.md"),
    SettingDefinition("templatesFolder", "path", "Design Handoff/Templates", "Handoff templates folder.", "vault-shared", "commit", True, True, True, "paths.md"),
    SettingDefinition("archiveFolder", "path", "Design Handoff/Archive", "Handoff archive folder.", "vault-shared", "commit", True, True, True, "paths.md"),
    SettingDefinition(
        "defaultWorkflowStatus",
        "string",
        "draft",
        "Default workflow status.",
        "vault-shared",
        "commit",
        True,
        True,
        True,
        "workflow.md",
        aliases=("defaultStatus",),
    ),
    SettingDefinition(
        "workflowStatuses",
        "array",
        ["draft", "in-review", "approved", "archived"],
        "Workflow statuses.",
        "vault-shared",
        "commit",
        True,
        True,
        True,
        "workflow.md",
        aliases=("statuses",),
    ),
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
    SettingDefinition(
        "machineRole",
        "enum",
        "primary",
        "Local machine role.",
        "vault-local",
        "gitignore",
        True,
        True,
        True,
        "local.md",
        allowed_values=("primary", "satellite", "readOnlySatellite", "automationNode", "testNode"),
    ),
    SettingDefinition("syncRole", "string", "local", "Local sync role.", "vault-local", "gitignore", True, True, True, "local.md"),
)


class SettingsService:
    def __init__(
        self,
        *,
        registry: SettingsRegistry | None = None,
        markdown_store: MarkdownSettingsStore | None = None,
        app_local_store: AppLocalSettingsStore | None = None,
        runtime_overrides: Mapping[str, Any] | None = None,
    ) -> None:
        self.registry = registry or SettingsRegistry()
        self.markdown_store = markdown_store or MarkdownSettingsStore()
        self.app_local_store = app_local_store
        self.runtime_overrides = dict(runtime_overrides or {})

    def effective_settings(self, context: VaultContext) -> dict[str, EffectiveSetting]:
        return self.resolve(context).settings

    def resolve(self, context: VaultContext) -> SettingsResolution:
        values = {
            definition.key: EffectiveSetting(
                key=definition.key,
                value=definition.default_value,
                scope="built-in",
                source="built-in",
            )
            for definition in self.registry.definitions
        }
        errors: list[SettingsValidationError] = []

        for source in self._source_documents(context, errors):
            self._apply_source(values, errors, source.document.frontmatter, source.scope, str(source.path))

        if context.status != "selected" and context.validation_error:
            errors.append(
                SettingsValidationError(
                    message=context.validation_error,
                    source_file=context.settings_path,
                    scope=None,
                )
            )

        self._apply_source(values, errors, self.runtime_overrides, "runtime", "runtime")
        return SettingsResolution(settings=values, validation_errors=tuple(errors))

    def _source_documents(
        self,
        context: VaultContext,
        errors: list[SettingsValidationError],
    ) -> tuple[_SourceDocument, ...]:
        sources: list[_SourceDocument] = []
        if self.app_local_store and self.app_local_store.path.exists():
            app_local = self._read_source(self.app_local_store.path, "app-local", errors)
            if app_local:
                sources.append(app_local)

        if context.status != "selected" or not context.settings_path:
            return tuple(sources)

        settings_dir = Path(context.settings_path)
        for filename in VAULT_SHARED_SETTING_FILES:
            source = self._read_source(settings_dir / filename, "vault-shared", errors)
            if source:
                sources.append(source)
        for filename in VAULT_LOCAL_SETTING_FILES:
            source = self._read_source(settings_dir / filename, "vault-local", errors)
            if source:
                sources.append(source)
        return tuple(sources)

    def _read_source(
        self,
        path: Path,
        fallback_scope: SettingScope,
        errors: list[SettingsValidationError],
    ) -> _SourceDocument | None:
        try:
            document = self.markdown_store.read(path)
        except FileNotFoundError:
            return None
        except (OSError, MarkdownSettingsError) as exc:
            errors.append(SettingsValidationError(message=str(exc), source_file=str(path), scope=fallback_scope))
            return None

        raw_scope = str(document.frontmatter.get("scope") or fallback_scope).strip()
        if raw_scope not in VALID_SOURCE_SCOPES:
            errors.append(
                SettingsValidationError(
                    message=f"settings file declares unsupported scope: {raw_scope}",
                    source_file=str(path),
                    scope=fallback_scope,
                )
            )
            return None
        return _SourceDocument(path=path, scope=raw_scope, document=document)  # type: ignore[arg-type]

    def _apply_source(
        self,
        values: dict[str, EffectiveSetting],
        errors: list[SettingsValidationError],
        source_values: Mapping[str, Any],
        source_scope: SettingScope,
        source_file: str,
    ) -> None:
        for definition in self.registry.definitions:
            if not _source_can_set_definition(source_scope, definition):
                continue
            found = _value_for_definition(source_values, definition)
            if not found[0]:
                continue
            value = found[1]
            valid, message = _validate_value(definition, value)
            if not valid:
                errors.append(
                    SettingsValidationError(
                        message=message or f"invalid value for {definition.key}",
                        source_file=source_file,
                        scope=source_scope,
                        key=definition.key,
                    )
                )
                continue
            values[definition.key] = EffectiveSetting(
                key=definition.key,
                value=value,
                scope=source_scope,
                source=source_file,
                source_file=None if source_file == "runtime" else source_file,
            )


def _source_can_set_definition(source_scope: SettingScope, definition: SettingDefinition) -> bool:
    if source_scope == "runtime":
        return True
    if source_scope == "app-local":
        return definition.scope == "app-local"
    if source_scope == "vault-shared":
        return definition.scope == "vault-shared"
    if source_scope == "vault-local":
        return definition.scope in {"vault-shared", "vault-local"}
    return False


def _value_for_definition(source_values: Mapping[str, Any], definition: SettingDefinition) -> tuple[bool, Any]:
    for key in (definition.key, *definition.aliases):
        if key in source_values:
            return True, source_values[key]
    return False, None


def _validate_value(definition: SettingDefinition, value: Any) -> _ValidationResult:
    if value is None:
        if definition.default_value is None:
            return True, None
        return False, f"{definition.key} must not be null"
    if definition.type in {"string", "path"}:
        if isinstance(value, str):
            return True, None
        return False, f"{definition.key} must be a string"
    if definition.type == "boolean":
        if isinstance(value, bool):
            return True, None
        return False, f"{definition.key} must be a boolean"
    if definition.type == "number":
        if isinstance(value, int | float) and not isinstance(value, bool):
            return True, None
        return False, f"{definition.key} must be a number"
    if definition.type == "array":
        if isinstance(value, list):
            return True, None
        return False, f"{definition.key} must be an array"
    if definition.type == "object":
        if isinstance(value, dict):
            return True, None
        return False, f"{definition.key} must be an object"
    if definition.type == "enum":
        if not isinstance(value, str):
            return False, f"{definition.key} must be a string enum value"
        if definition.allowed_values and value not in definition.allowed_values:
            allowed = ", ".join(str(item) for item in definition.allowed_values)
            return False, f"{definition.key} must be one of: {allowed}"
        return True, None
    return False, f"{definition.key} has unsupported setting type: {definition.type}"


__all__ = [
    "EffectiveSetting",
    "SETTING_DEFINITIONS",
    "SettingDefinition",
    "SettingsRegistry",
    "SettingsResolution",
    "SettingsService",
    "SettingsValidationError",
]
