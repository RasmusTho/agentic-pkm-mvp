from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Mapping, NamedTuple, TypeAlias, cast

from app.instance.vault_registry import AppLocalSettingsStore
from app.receipts.settings_write import (
    SettingsWriteReceipt,
    emit_settings_write_receipt,
    resolve_settings_receipt_old_value,
)
from app.vault.manager import VaultContext
from app.vault.markdown_settings import MarkdownSettingsDocument, MarkdownSettingsError, MarkdownSettingsStore


logger = logging.getLogger(__name__)


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
    "youtube.md",
)
VAULT_LOCAL_SETTING_FILES = ("local.md",)
VALID_SOURCE_SCOPES = {"app-local", "vault-shared", "vault-local"}

# Runtime-gating settings: authority-bearing writes that reconfigure whether
# the watcher/indexing runtime runs (registry.py:734, config.py:92) or whether
# the YouTube source-sync runner may run at all
# (docs/YOUTUBE_SOURCE_SYNC/SOURCE_SYNC_CONTRACT.md :: Settings model).
# These must route through the governed write seam (WriteGuard + actor receipt).
# See docs/COMPANION_UI_PRODUCT_SPEC.md :: Runtime control actions and
# companion-ui/docs/UI_RUNTIME_BOUNDARIES.md :: Control-action register.
RUNTIME_GATING_SETTINGS: frozenset[str] = frozenset(
    {
        "enableVaultWatcher",
        "enableAutoIndexing",
        "youtubeSync.enabled",
        "youtubeSync.runnerEnabled",
    }
)

_SETTINGS_WRITE_ACTION = "settings.runtime_gating.write"


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
    min_value: float | None = None
    max_value: float | None = None


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


class SettingsWriteError(ValueError):
    """Raised when a scoped settings write cannot be applied safely."""


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
    SettingDefinition(
        "journalingEveningNudgeEnabled",
        "boolean",
        False,
        "Offer an evening reflection in Companion UI; never starts it automatically.",
        "vault-shared",
        "commit",
        True,
        True,
        True,
        "workflow.md",
    ),
    SettingDefinition(
        "journalingEveningNudgeStartHour",
        "number",
        20,
        "Local hour when the optional evening reflection offer begins.",
        "vault-shared",
        "commit",
        True,
        False,
        True,
        "workflow.md",
    ),
    SettingDefinition(
        "journalingEveningNudgeEndHour",
        "number",
        22,
        "Local hour when the optional evening reflection offer ends.",
        "vault-shared",
        "commit",
        True,
        False,
        True,
        "workflow.md",
    ),
    SettingDefinition(
        "journalingReflectionIdleTimeoutSeconds",
        "number",
        900,
        "Idle time before an open reflection conversation closes with its transcript intact.",
        "vault-shared",
        "commit",
        True,
        False,
        True,
        "workflow.md",
    ),
    SettingDefinition(
        "journalingReflectionMaxOwnerTurns",
        "number",
        5,
        "Safety cap on owner turns in one reflection conversation.",
        "vault-shared",
        "commit",
        True,
        False,
        True,
        "workflow.md",
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
    # YouTube source sync (YSS-01): keys, scopes, defaults, and bounds are
    # normative in docs/YOUTUBE_SOURCE_SYNC/SOURCE_SYNC_CONTRACT.md :: Settings model.
    SettingDefinition(
        "youtubeSync.enabled",
        "boolean",
        False,
        "Master switch for YouTube source sync; flipped by completing setup.",
        "vault-shared",
        "commit",
        True,
        True,
        True,
        "youtube.md",
    ),
    SettingDefinition(
        "youtubeSync.inboxPollSeconds",
        "number",
        180,
        "Poll interval in seconds for the inbox playlist.",
        "vault-shared",
        "commit",
        True,
        True,
        True,
        "youtube.md",
        min_value=60,
        max_value=3600,
    ),
    SettingDefinition(
        "youtubeSync.playlistPollSeconds",
        "number",
        3600,
        "Non-inbox playlist poll interval in seconds.",
        "vault-shared",
        "commit",
        True,
        True,
        True,
        "youtube.md",
        min_value=300,
        max_value=86400,
    ),
    SettingDefinition(
        "youtubeSync.subscriptionsPollSeconds",
        "number",
        21600,
        "Subscription feed poll interval in seconds.",
        "vault-shared",
        "commit",
        True,
        True,
        True,
        "youtube.md",
        min_value=3600,
        max_value=86400,
    ),
    SettingDefinition(
        "youtubeSync.reconcileIntervalDays",
        "number",
        7,
        "Days between reconcile/gap-repair sweeps.",
        "vault-shared",
        "commit",
        True,
        True,
        True,
        "youtube.md",
        min_value=1,
        max_value=90,
    ),
    SettingDefinition(
        "youtubeSync.maxConcurrentAcquisitions",
        "number",
        2,
        "Maximum concurrent acquisition requests drained at once.",
        "vault-shared",
        "commit",
        True,
        True,
        True,
        "youtube.md",
        min_value=1,
        max_value=8,
    ),
    SettingDefinition(
        "youtubeSync.subscriptionDefaultPolicy",
        "enum",
        "discover_only",
        "Default acquisition policy mode for subscription-feed sources.",
        "vault-shared",
        "commit",
        True,
        True,
        True,
        "youtube.md",
        allowed_values=(
            "discover_only",
            "candidate_metadata_only",
            "acquire_transcript",
            "acquire_if_filter_matches",
        ),
    ),
    SettingDefinition(
        "youtubeSync.captionsEnabled",
        "boolean",
        True,
        "Acquire captions/transcripts for discovered videos.",
        "vault-shared",
        "commit",
        True,
        True,
        True,
        "youtube.md",
    ),
    SettingDefinition(
        "youtubeSync.mediaDownloadEnabled",
        "boolean",
        False,
        "Full media archival master switch; engine deferred, refused while undelivered.",
        "vault-shared",
        "commit",
        True,
        True,
        True,
        "youtube.md",
    ),
    SettingDefinition(
        "youtubeSync.runnerEnabled",
        "boolean",
        False,
        "Whether this machine runs the YouTube sync loop; the DB lease remains the hard guard.",
        "vault-local",
        "gitignore",
        True,
        True,
        True,
        "local.md",
    ),
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

    def reload(self, context: VaultContext) -> SettingsResolution:
        return self.resolve(context)

    def update_setting(
        self,
        context: VaultContext,
        key: str,
        value: Any,
        *,
        surface: str = "api",
        actor: str = "human",
        persist: bool = True,
    ) -> tuple[EffectiveSetting, SettingsWriteReceipt]:
        """Write a single setting and return (effective_setting, receipt).

        Runtime-gating settings (``enableVaultWatcher``, ``enableAutoIndexing``)
        are authority-bearing and route through the governed write seam:
        WriteGuard health-gate is asserted first, then an actor-tagged receipt
        is emitted.  Non-runtime-gating settings follow the same path but are
        not write-guarded.

        ``persist=False`` keeps the governed receipt path but skips writing the
        file back. The watcher uses that mode when a runtime-gating key is
        removed from frontmatter and the receipt should still be emitted.

        ``surface`` names the interaction origin (``'api'``, ``'cli'``,
        ``'file'``, ``'mcp'``); ``actor`` is the stable actor identity
        (``'human'`` for all UI/API/CLI/file origins).
        """
        definition = self.registry.get(key)
        if definition is None:
            raise SettingsWriteError(f"unknown setting: {key}")
        if not definition.editable_in_companion:
            raise SettingsWriteError(f"{key} is not editable in Companion UI")
        if definition.scope not in {"vault-shared", "vault-local"}:
            raise SettingsWriteError(f"{key} is not a vault-scoped setting")
        if context.status != "selected" or not context.settings_path:
            raise SettingsWriteError("settings writes require a selected initialized vault")
        if not definition.file:
            raise SettingsWriteError(f"{key} has no Markdown settings file")
        valid, message = _validate_value(definition, value)
        if not valid:
            raise SettingsWriteError(message or f"invalid value for {key}")

        is_runtime_gating = key in RUNTIME_GATING_SETTINGS

        # Governed write seam: apply WriteGuard for runtime-gating settings.
        # Import is deferred to avoid a circular dependency between vault and
        # write_guard at module load time.
        if is_runtime_gating:
            from app.write_guard import DEFAULT_WRITE_GUARD, WritesBlockedError  # noqa: PLC0415

            try:
                DEFAULT_WRITE_GUARD.assert_writes_allowed(_SETTINGS_WRITE_ACTION)
            except WritesBlockedError as exc:
                raise SettingsWriteError(
                    f"runtime-gating setting write blocked by health gate: {exc}"
                ) from exc

        path = Path(context.settings_path) / definition.file
        try:
            document = self.markdown_store.read(path)
        except FileNotFoundError as exc:
            raise SettingsWriteError(f"settings file does not exist: {path}") from exc
        except (OSError, MarkdownSettingsError) as exc:
            raise SettingsWriteError(str(exc)) from exc

        raw_scope = str(document.frontmatter.get("scope") or definition.scope).strip()
        if raw_scope not in VALID_SOURCE_SCOPES:
            raise SettingsWriteError(f"settings file declares unsupported scope: {raw_scope}")
        source_scope = cast(SettingScope, raw_scope)
        if not _source_can_set_definition(source_scope, definition):
            raise SettingsWriteError(f"{path.name} cannot set {key}")

        frontmatter = dict(document.frontmatter)
        old_value = resolve_settings_receipt_old_value(frontmatter.get(key))
        frontmatter[key] = value
        if persist:
            self.markdown_store.write_frontmatter(path, frontmatter, body=document.body)

        effective = EffectiveSetting(
            key=key,
            value=value,
            scope=source_scope,
            source=str(path),
            source_file=str(path),
        )

        # Emit actor-tagged receipt for all governed writes.
        receipt_value = value if persist else None
        receipt = SettingsWriteReceipt(
            key=key,
            value=receipt_value,
            surface=surface,
            actor=actor,
            is_runtime_gating=is_runtime_gating,
            file=str(path),
            old_value=old_value,
            new_value=receipt_value,
        )
        logger.info(
            "settings.write surface=%s actor=%s key=%s runtime_gating=%s ts=%s",
            receipt.surface,
            receipt.actor,
            receipt.key,
            receipt.is_runtime_gating,
            receipt.timestamp,
        )
        # Durability is additive: the in-memory receipt above remains the return-value
        # contract; this also persists the same receipt as a durable outbox event so it
        # survives process restart (#2787).
        emit_settings_write_receipt(receipt)

        return effective, receipt

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
            self._apply_source(
                values,
                errors,
                source.document.frontmatter,
                source.scope,
                str(source.path),
                source_filename=source.path.name,
            )

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
        # Trust the source class (where the file was read from), not the file's
        # self-declared scope. A forged ``scope: vault-shared`` in an app-local
        # source must not let app-local content set project-scope keys. The
        # declared scope may only confirm the known class, never widen it.
        if raw_scope != fallback_scope:
            errors.append(
                SettingsValidationError(
                    message=(
                        f"settings file declares scope '{raw_scope}' but is a "
                        f"{fallback_scope} source; declared scope is ignored"
                    ),
                    source_file=str(path),
                    scope=fallback_scope,
                )
            )
        return _SourceDocument(path=path, scope=fallback_scope, document=document)

    def _apply_source(
        self,
        values: dict[str, EffectiveSetting],
        errors: list[SettingsValidationError],
        source_values: Mapping[str, Any],
        source_scope: SettingScope,
        source_file: str,
        *,
        source_filename: str | None = None,
    ) -> None:
        for definition in self.registry.definitions:
            if not _source_can_set_definition(source_scope, definition):
                continue
            # Bind each vault file-backed definition to its declared
            # ``definition.file`` only within its own scope class: a vault-shared
            # file must not override a vault-shared key owned by another shared
            # file (e.g. companion-ui.md setting handoffFolder, owned by
            # paths.md). This must NOT block the documented cross-scope override
            # where a vault-local file (local.md) overrides a vault-shared key —
            # that legitimate precedence path keeps working.
            if (
                source_filename is not None
                and definition.file is not None
                and source_scope == definition.scope
                and definition.file != source_filename
            ):
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
        if not isinstance(value, int | float) or isinstance(value, bool):
            return False, f"{definition.key} must be a number"
        if definition.min_value is not None and value < definition.min_value:
            return False, f"{definition.key} must be >= {definition.min_value}"
        if definition.max_value is not None and value > definition.max_value:
            return False, f"{definition.key} must be <= {definition.max_value}"
        return True, None
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
    "RUNTIME_GATING_SETTINGS",
    "SETTING_DEFINITIONS",
    "SettingDefinition",
    "SettingsRegistry",
    "SettingsResolution",
    "SettingsService",
    "SettingsValidationError",
    "SettingsWriteError",
    "SettingsWriteReceipt",
]
