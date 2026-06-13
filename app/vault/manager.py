from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal
from uuid import uuid4

from app.vault.app_local import AppLocalSettingsStore, KnownVaultRef
from app.vault.markdown_settings import MarkdownSettingsError, MarkdownSettingsStore


VaultStatus = Literal["none", "selected", "missing", "invalid", "uninitialized"]
MachineRole = Literal["primary", "satellite", "readOnlySatellite", "automationNode", "testNode"]

SETTINGS_DIR_NAME = "settings"
REQUIRED_SETTINGS_FILES = (
    "vault.md",
    "paths.md",
    "workflow.md",
    "design-handoff.md",
    "companion-ui.md",
    "local.md",
)
LOCAL_GITIGNORE = "# Design Handoff local settings\nlocal.md\n*.local.md\nlocal/\nruntime/\ncache/\n"


@dataclass(frozen=True)
class VaultContext:
    status: VaultStatus
    active_vault_id: str | None = None
    active_vault_name: str | None = None
    active_vault_path: str | None = None
    settings_path: str | None = None
    local_instance_id: str | None = None
    machine_role: MachineRole | None = None
    validation_error: str | None = None

    @property
    def is_selected(self) -> bool:
        return self.status == "selected" and bool(self.active_vault_path)


@dataclass(frozen=True)
class VaultPermissions:
    enable_vault_watcher: bool = True
    enable_auto_indexing: bool = True
    allow_writes_to_vault: bool = True
    allow_shared_settings_edits: bool = True
    allow_local_settings_edits: bool = True


@dataclass(frozen=True)
class VaultChangedEvent:
    previous_vault_id: str | None
    previous_vault_path: str | None
    next_vault_id: str | None
    next_vault_path: str | None
    status: VaultStatus


@dataclass(frozen=True)
class VaultInitializationResult:
    context: VaultContext
    created_files: tuple[str, ...] = field(default=())
    skipped_existing_files: tuple[str, ...] = field(default=())


class VaultRequiredError(RuntimeError):
    """Raised when a vault-scoped operation runs without a selected vault."""


def no_vault_context() -> VaultContext:
    return VaultContext(status="none")


class VaultManager:
    def __init__(
        self,
        *,
        app_local_store: AppLocalSettingsStore | None = None,
        markdown_store: MarkdownSettingsStore | None = None,
    ) -> None:
        self.app_local_store = app_local_store or AppLocalSettingsStore()
        self.markdown_store = markdown_store or MarkdownSettingsStore()
        self._context = no_vault_context()
        self._subscribers: list[Callable[[VaultChangedEvent], None]] = []

    @property
    def context(self) -> VaultContext:
        return self._context

    def subscribe(self, callback: Callable[[VaultChangedEvent], None]) -> None:
        self._subscribers.append(callback)

    def load_last_active(self) -> VaultContext:
        settings = self.app_local_store.load()
        ref = settings.last_active_vault_ref
        if not ref:
            self._context = no_vault_context()
            return self._context
        item = settings.known_vaults.get(ref)
        if item is None:
            self._context = no_vault_context()
            return self._context
        return self.select_vault(Path(item.path), remember=False)

    def select_vault(self, vault_path: Path, *, remember: bool = True) -> VaultContext:
        previous = self._context
        context = self.validate_vault(vault_path)
        self._context = context
        if remember and context.status in {"selected", "uninitialized", "invalid", "missing"}:
            self._remember_context(context, vault_path)
        self._emit_changed(previous, context)
        return context

    def validate_vault(self, vault_path: Path) -> VaultContext:
        expanded = vault_path.expanduser()
        if not expanded.exists():
            return VaultContext(status="missing", active_vault_path=str(expanded))
        if not expanded.is_dir():
            return VaultContext(
                status="invalid",
                active_vault_path=str(expanded),
                validation_error="selected vault path is not a directory",
            )

        settings_dir = expanded / SETTINGS_DIR_NAME
        missing = [name for name in REQUIRED_SETTINGS_FILES if not (settings_dir / name).exists()]
        if missing:
            return VaultContext(
                status="uninitialized",
                active_vault_name=expanded.name,
                active_vault_path=str(expanded),
                settings_path=str(settings_dir),
                validation_error=f"missing Design Handoff settings: {', '.join(missing)}",
            )

        try:
            vault_doc = self.markdown_store.read(settings_dir / "vault.md")
            local_doc = self.markdown_store.read(settings_dir / "local.md")
        except MarkdownSettingsError as exc:
            return VaultContext(
                status="invalid",
                active_vault_name=expanded.name,
                active_vault_path=str(expanded),
                settings_path=str(settings_dir),
                validation_error=str(exc),
            )

        if vault_doc.frontmatter.get("schema") != "design-handoff.vault.v1":
            return VaultContext(
                status="invalid",
                active_vault_name=expanded.name,
                active_vault_path=str(expanded),
                settings_path=str(settings_dir),
                validation_error="settings/vault.md has an incompatible schema",
            )
        if local_doc.frontmatter.get("schema") != "design-handoff.local.v1":
            return VaultContext(
                status="invalid",
                active_vault_name=expanded.name,
                active_vault_path=str(expanded),
                settings_path=str(settings_dir),
                validation_error="settings/local.md has an incompatible schema",
            )

        role = _machine_role(local_doc.frontmatter.get("machineRole"))
        return VaultContext(
            status="selected",
            active_vault_id=_required_str(vault_doc.frontmatter.get("vaultId"), fallback=f"vault-{uuid4()}"),
            active_vault_name=_required_str(vault_doc.frontmatter.get("vaultName"), fallback=expanded.name),
            active_vault_path=str(expanded),
            settings_path=str(settings_dir),
            local_instance_id=_required_str(local_doc.frontmatter.get("localInstanceId"), fallback=f"local-{uuid4()}"),
            machine_role=role,
        )

    def initialize_vault(
        self,
        vault_path: Path,
        *,
        vault_name: str | None = None,
        machine_role: MachineRole = "primary",
        remember: bool = True,
    ) -> VaultInitializationResult:
        expanded = vault_path.expanduser()
        expanded.mkdir(parents=True, exist_ok=True)
        settings_dir = expanded / SETTINGS_DIR_NAME
        settings_dir.mkdir(parents=True, exist_ok=True)

        vault_id = f"vault-{uuid4()}"
        local_instance_id = f"local-{uuid4()}"
        name = vault_name or expanded.name
        created: list[str] = []
        skipped: list[str] = []

        for filename, frontmatter, body in _initial_settings_files(
            vault_id=vault_id,
            vault_name=name,
            local_instance_id=local_instance_id,
            machine_role=machine_role,
        ):
            path = settings_dir / filename
            if self.markdown_store.write_missing(path, frontmatter, body):
                created.append(str(path.relative_to(expanded)))
            else:
                skipped.append(str(path.relative_to(expanded)))

        gitignore_path = settings_dir / ".gitignore"
        if gitignore_path.exists():
            skipped.append(str(gitignore_path.relative_to(expanded)))
        else:
            gitignore_path.write_text(LOCAL_GITIGNORE, encoding="utf-8")
            created.append(str(gitignore_path.relative_to(expanded)))

        context = self.select_vault(expanded, remember=remember)
        return VaultInitializationResult(
            context=context,
            created_files=tuple(created),
            skipped_existing_files=tuple(skipped),
        )

    def permissions_for_context(self, context: VaultContext | None = None) -> VaultPermissions:
        ctx = context or self._context
        if ctx.status != "selected" or not ctx.settings_path:
            return VaultPermissions(
                enable_vault_watcher=False,
                enable_auto_indexing=False,
                allow_writes_to_vault=False,
                allow_shared_settings_edits=False,
                allow_local_settings_edits=False,
            )
        try:
            local_doc = self.markdown_store.read(Path(ctx.settings_path) / "local.md")
        except Exception:
            return VaultPermissions(
                enable_vault_watcher=False,
                enable_auto_indexing=False,
                allow_writes_to_vault=False,
                allow_shared_settings_edits=False,
                allow_local_settings_edits=False,
            )
        fm = local_doc.frontmatter
        role = _machine_role(fm.get("machineRole"))
        if role == "readOnlySatellite":
            return VaultPermissions(
                enable_vault_watcher=False,
                enable_auto_indexing=False,
                allow_writes_to_vault=False,
                allow_shared_settings_edits=False,
                allow_local_settings_edits=_bool_setting(fm.get("allowLocalSettingsEdits"), default=True),
            )
        shared_default = role in {"primary", "automationNode", "testNode"}
        return VaultPermissions(
            enable_vault_watcher=_bool_setting(fm.get("enableVaultWatcher"), default=True),
            enable_auto_indexing=_bool_setting(fm.get("enableAutoIndexing"), default=True),
            allow_writes_to_vault=_bool_setting(fm.get("allowWritesToVault"), default=True),
            allow_shared_settings_edits=_bool_setting(fm.get("allowSharedSettingsEdits"), default=shared_default),
            allow_local_settings_edits=_bool_setting(fm.get("allowLocalSettingsEdits"), default=True),
        )

    def require_selected_vault(
        self,
        *,
        operation: str,
        require_writes: bool = False,
        require_watcher: bool = False,
        require_indexing: bool = False,
        require_shared_settings_edits: bool = False,
        require_local_settings_edits: bool = False,
    ) -> VaultContext:
        ctx = self._context
        if ctx.status != "selected" or not ctx.active_vault_path:
            raise VaultRequiredError(f"{operation} requires a selected initialized vault; current status is {ctx.status}")
        permissions = self.permissions_for_context(ctx)
        if require_writes and not permissions.allow_writes_to_vault:
            raise VaultRequiredError(f"{operation} requires vault writes, but this local role disallows them")
        if require_watcher and not permissions.enable_vault_watcher:
            raise VaultRequiredError(f"{operation} requires the vault watcher, but it is disabled for this vault")
        if require_indexing and not permissions.enable_auto_indexing:
            raise VaultRequiredError(f"{operation} requires auto indexing, but it is disabled for this vault")
        if require_shared_settings_edits:
            if not permissions.allow_writes_to_vault:
                raise VaultRequiredError(f"{operation} requires vault writes, but this local role disallows them")
            if not permissions.allow_shared_settings_edits:
                raise VaultRequiredError(f"{operation} requires shared settings edits, but this local role disallows them")
        if require_local_settings_edits and not permissions.allow_local_settings_edits:
            raise VaultRequiredError(f"{operation} requires local settings edits, but this local role disallows them")
        return ctx

    def _remember_context(self, context: VaultContext, vault_path: Path) -> None:
        ref = f"path:{vault_path.expanduser()}"
        self.app_local_store.upsert_known_vault(
            KnownVaultRef(
                ref=ref,
                path=str(vault_path.expanduser()),
                vault_id=context.active_vault_id,
                vault_name=context.active_vault_name,
                local_instance_id=context.local_instance_id,
                last_opened_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            ),
            make_active=True,
        )

    def _emit_changed(self, previous: VaultContext, next_context: VaultContext) -> None:
        event = VaultChangedEvent(
            previous_vault_id=previous.active_vault_id,
            previous_vault_path=previous.active_vault_path,
            next_vault_id=next_context.active_vault_id,
            next_vault_path=next_context.active_vault_path,
            status=next_context.status,
        )
        for callback in list(self._subscribers):
            try:
                callback(event)
            except Exception:
                continue


_GLOBAL_MANAGER: VaultManager | None = None


def get_vault_manager() -> VaultManager:
    global _GLOBAL_MANAGER
    if _GLOBAL_MANAGER is None:
        _GLOBAL_MANAGER = VaultManager()
    return _GLOBAL_MANAGER


def _initial_settings_files(
    *,
    vault_id: str,
    vault_name: str,
    local_instance_id: str,
    machine_role: MachineRole,
) -> tuple[tuple[str, dict[str, Any], str], ...]:
    return (
        (
            "vault.md",
            {
                "schema": "design-handoff.vault.v1",
                "scope": "vault-shared",
                "vaultId": vault_id,
                "vaultName": vault_name,
                "createdBy": "design-handoff",
                "settingsVersion": 1,
            },
            "# Vault Settings\nThis file identifies the logical Design Handoff vault.\nIt may be shared across machines through Git.\n",
        ),
        (
            "paths.md",
            {
                "schema": "design-handoff.paths.v1",
                "scope": "vault-shared",
                "handoffFolder": "Design Handoff",
                "assetsFolder": "Design Handoff/Assets",
                "templatesFolder": "Design Handoff/Templates",
                "archiveFolder": "Design Handoff/Archive",
            },
            "# Path Settings\nThese paths are relative to the vault root unless otherwise stated.\n",
        ),
        (
            "workflow.md",
            {
                "schema": "design-handoff.workflow.v1",
                "scope": "vault-shared",
                "defaultStatus": "draft",
                "statuses": ["draft", "in-review", "approved", "archived"],
            },
            "# Workflow Settings\nThese settings define shared workflow states for this vault.\n",
        ),
        (
            "design-handoff.md",
            {
                "schema": "design-handoff.core.v1",
                "scope": "vault-shared",
                "autoCreateAssetFolders": True,
                "preserveOriginalFileNames": True,
                "generateIndexOnChange": True,
            },
            "# Design Handoff Settings\nCore settings for the handoff workflow.\n",
        ),
        (
            "companion-ui.md",
            {
                "schema": "design-handoff.companion-ui.v1",
                "scope": "vault-shared",
                "defaultView": "handoff",
                "showAdvancedSettings": False,
                "autoRefresh": True,
            },
            "# Companion UI Settings\nShared Companion UI defaults for this vault.\nLocal UI preferences may override these in local settings.\n",
        ),
        (
            "local.md",
            {
                "schema": "design-handoff.local.v1",
                "scope": "vault-local",
                "localInstanceId": local_instance_id,
                "machineRole": machine_role,
                "syncRole": "local",
                "enableVaultWatcher": machine_role != "readOnlySatellite",
                "enableAutoIndexing": machine_role != "readOnlySatellite",
                "allowWritesToVault": machine_role != "readOnlySatellite",
                "allowSharedSettingsEdits": machine_role in {"primary", "automationNode", "testNode"},
                "allowLocalSettingsEdits": True,
                "localExportPath": None,
            },
            "# Local Settings\nSettings for this local clone of the vault.\nThis file should not be committed to Git.\nUse this file for machine-specific paths, satellite behavior, local runtime preferences, and local automation settings.\n",
        ),
    )


def _required_str(value: object, *, fallback: str) -> str:
    text = str(value).strip() if value is not None else ""
    return text or fallback


def _machine_role(value: object) -> MachineRole:
    text = str(value or "primary").strip()
    if text in {"primary", "satellite", "readOnlySatellite", "automationNode", "testNode"}:
        return text  # type: ignore[return-value]
    return "primary"


def _bool_setting(value: object, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


__all__ = [
    "MachineRole",
    "VaultChangedEvent",
    "VaultContext",
    "VaultInitializationResult",
    "VaultManager",
    "VaultPermissions",
    "VaultRequiredError",
    "VaultStatus",
    "get_vault_manager",
    "no_vault_context",
]
