from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
import os
from pathlib import Path
from typing import Any, Callable, Iterator, Literal
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
# The single committed marker that makes a folder a vault root. Aligned with
# ``validate_vault`` (which requires ``settings/vault.md`` among the Design
# Handoff settings) but used as a *cheap* boundary test: one ``stat`` per
# folder, no schema read, no healing. Boundary detection (#2313) must stay cheap
# on large trees, so callers prune subtrees during traversal rather than
# enumerating everything and validating each candidate.
VAULT_ROOT_MARKER_REL = (SETTINGS_DIR_NAME, "vault.md")
logger = logging.getLogger(__name__)


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


# OS-noise entries that do not indicate a populated personal vault. A folder
# holding only these is treated as empty for the initialize-confirmation gate
# (#2518). ``.DS_Store`` is macOS Finder noise that routinely appears in a folder
# the human believes is empty; warning on it alone would make a fresh-folder init
# feel broken.
INIT_TARGET_IGNORED_ENTRIES = frozenset({".DS_Store"})


def existing_init_target_entries(vault_path: Path) -> tuple[str, ...]:
    """Top-level entry names that mean ``vault_path`` is already populated.

    Returns the sorted names of every entry that is not ignorable OS noise
    (:data:`INIT_TARGET_IGNORED_ENTRIES`). A non-empty result means initializing
    would add the settings scaffold into a folder that already holds content, so
    the picker must obtain an explicit, understood confirmation before the write
    (#2518: "must not write into a human's personal vault without an explicit,
    understood choice").

    Notably a ``settings/`` directory is **counted**, not assumed to be the
    Design Handoff scaffold: a human's own ``settings/`` folder must not be
    silently written into (Codex #2520 P2). A folder holding only a partial DH
    scaffold therefore also requires a one-time confirm to complete via the
    picker — a safe, rare edge — while a fully-initialized vault is ``selected``
    and never reaches this gate.

    A missing path or an empty directory returns ``()`` — those initialize
    friction-free (preserves #2312 AC1). A path that exists but is not a
    directory also returns ``()``; ``initialize_vault`` owns that error surface.
    """
    expanded = vault_path.expanduser()
    if not expanded.is_dir():
        return ()
    # ``vault_path`` is the operator-selected vault location from the loopback-
    # authed picker (#2310 full-host selection), so listing it is by design and
    # is strictly weaker than ``initialize_vault``'s existing mkdir/write at the
    # same path. A CodeQL py/path-injection alert here is accepted on that basis
    # (the picker's whole purpose is choosing an arbitrary local path; there is
    # no containing root to validate against, and only top-level names are read).
    names = [
        child.name
        for child in expanded.iterdir()
        if child.name not in INIT_TARGET_IGNORED_ENTRIES
    ]
    return tuple(sorted(names))


def is_vault_root(path: Path) -> bool:
    """Return True iff ``path`` is an initialized vault root (#2313).

    A folder is a vault root iff it carries the committed vault marker
    ``settings/vault.md`` — the same marker ``validate_vault`` requires. This is
    a deliberately *cheap* check (a single ``stat`` via ``Path.is_file``), not a
    full validation: it does not read the file, check the schema, or heal
    identity. That keeps nested-vault boundary detection inexpensive on large
    trees, where it is called once per directory during a pruned walk.

    The boundary rule: enumeration of a parent vault STOPS at any nested vault
    root strictly below the parent. The parent must act as if a private child
    vault's subtree does not exist, so its contents never surface through the
    parent's read surfaces.
    """
    marker = path.joinpath(*VAULT_ROOT_MARKER_REL)
    return marker.is_file()


def nearest_enclosing_vault_root(
    note_path: Path, *, search_root: Path
) -> Path | None:
    """Return the nearest enclosing vault root for ``note_path`` (#2313).

    A note's owning vault is the NEAREST ENCLOSING vault root — the deepest
    ancestor directory (walking up from the note) that carries the vault marker,
    bounded below by ``search_root``. If a deeper nested vault root encloses the
    note, that nested root owns the note, NOT the selected/search root.

    ``search_root`` is treated as a vault root regardless of marker presence
    (the selected root is the floor of the search) and is returned as the
    fallback owner when no deeper marker exists between it and the note. Returns
    ``None`` when ``note_path`` is not contained within ``search_root``.

    The walk is bounded by the depth of ``note_path`` below ``search_root``;
    callers that need owning-vault identity for many notes should prefer the
    pruned-walk enumeration, which establishes ownership during traversal
    without an O(notes x depth) per-note ancestor rescan.
    """
    try:
        search_root = search_root.resolve()
        candidate = note_path.resolve()
    except OSError:
        return None
    try:
        candidate.relative_to(search_root)
    except ValueError:
        return None
    # Walk up from the note's directory to (and including) the search root,
    # returning the first (deepest) directory that carries the vault marker.
    current = candidate if candidate.is_dir() else candidate.parent
    while True:
        if current == search_root:
            return search_root
        if is_vault_root(current):
            return current
        parent = current.parent
        if parent == current:  # filesystem root guard
            return None
        current = parent


def iter_vault_markdown_files(
    vault_root: Path, *, subtree_root: Path | None = None
) -> Iterator[Path]:
    """Yield markdown files owned by ``vault_root`` only (#2522).

    Nested-vault boundary: traversal of a parent vault STOPS at any deeper
    initialized child vault root (``settings/vault.md``). This keeps ingest,
    indexing, watcher scans, and recall-style enumeration from treating a child
    vault's notes as parent-owned content.

    ``subtree_root`` narrows traversal to an explicit folder under the selected
    vault. If that folder itself belongs to a deeper child vault, nothing is
    yielded under the parent identity. Traversal prunes nested child vault
    roots in-place, so the boundary stays cheap on large trees.
    """
    selected_root = vault_root.expanduser().resolve()
    walk_root = (subtree_root or vault_root).expanduser().resolve()
    try:
        walk_root.relative_to(selected_root)
    except ValueError:
        return
    if not walk_root.is_dir():
        return
    if walk_root != selected_root:
        if nearest_enclosing_vault_root(walk_root, search_root=selected_root) != selected_root:
            return

    for dirpath, dirnames, filenames in os.walk(str(walk_root)):
        kept: list[str] = []
        for name in dirnames:
            child = Path(dirpath) / name
            if is_vault_root(child):
                continue
            kept.append(name)
        dirnames[:] = sorted(kept)

        for filename in sorted(filenames):
            if not filename.endswith(".md"):
                continue
            candidate = Path(dirpath) / filename
            if not candidate.is_file():
                continue
            if candidate.is_symlink():
                try:
                    real = candidate.resolve()
                except OSError:
                    continue
                if nearest_enclosing_vault_root(real, search_root=selected_root) != selected_root:
                    continue
            yield candidate


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
        try:
            settings = self.app_local_store.load()
        except (OSError, MarkdownSettingsError):
            # A corrupt app-local registry (e.g. Git conflict markers) must not
            # 500 vault data/edit routes. Degrade to the no-vault picker state.
            logger.warning("app-local registry unreadable; falling back to no-vault state", exc_info=True)
            self._context = no_vault_context()
            return self._context
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
        if remember and context.status in {"selected", "uninitialized", "invalid", "missing"}:
            self._remember_context(context, vault_path)
        self._context = context
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
        # Honor the read-only ceiling before healing a missing identity. The two
        # ids live in different files with different write authority:
        #   - vaultId is in the shared, committable vault.md -> requires
        #     shared-settings write authority to heal.
        #   - localInstanceId is in the gitignored, machine-local local.md ->
        #     requires only local-settings write authority to heal.
        # A read-only role writes neither; a satellite with shared edits disabled
        # can still persist its own local clone id so recent-vault identity stays
        # stable (Codex #2030 P2).
        allow_shared_heal = self._allow_shared_identity_heal(role, local_doc.frontmatter)
        allow_local_heal = self._allow_local_identity_heal(role, local_doc.frontmatter)
        try:
            vault_id = self._ensure_frontmatter_id(
                settings_dir / "vault.md",
                vault_doc.frontmatter,
                key="vaultId",
                prefix="vault",
                body=vault_doc.body,
                persist=allow_shared_heal,
            )
            local_instance_id = self._ensure_frontmatter_id(
                settings_dir / "local.md",
                local_doc.frontmatter,
                key="localInstanceId",
                prefix="local",
                body=local_doc.body,
                persist=allow_local_heal,
            )
        except OSError as exc:
            return VaultContext(
                status="invalid",
                active_vault_name=expanded.name,
                active_vault_path=str(expanded),
                settings_path=str(settings_dir),
                validation_error=f"unable to persist generated vault identity: {exc}",
            )

        return VaultContext(
            status="selected",
            active_vault_id=vault_id,
            active_vault_name=_required_str(vault_doc.frontmatter.get("vaultName"), fallback=expanded.name),
            active_vault_path=str(expanded),
            settings_path=str(settings_dir),
            local_instance_id=local_instance_id,
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

        # NOTE: initialize_vault deliberately does NOT pre-write a
        # ``vault.layout.md`` here. Bootstrapping a default layout at init time
        # changed the established capture-scoped layout for seed/UAT flows
        # (regressing the watcher scope_glob and the channel-bootstrap settings
        # layout). The CRE path is instead made crash-proof at the read side:
        # ``resolve_vault_system_dir_rel_or_default`` (used by the relevance
        # evaluator and materialization) degrades to the packaged default system
        # folder on an init-only vault, so the default-on tick still materializes
        # without forcing a layout note here.

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
        known = KnownVaultRef(
            ref=ref,
            path=str(vault_path.expanduser()),
            vault_id=context.active_vault_id,
            vault_name=context.active_vault_name,
            local_instance_id=context.local_instance_id,
            last_opened_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        )
        try:
            self.app_local_store.upsert_known_vault(known, make_active=True)
        except MarkdownSettingsError:
            # A corrupt app-local registry (Git conflict markers, malformed
            # frontmatter) must not 500 picker recovery: selecting/initializing a
            # vault with remember=True over a corrupt registry should still
            # succeed. Back up only this proven parse-corruption path; write-side
            # OSError must fail loudly without moving aside a valid registry.
            logger.warning(
                "app-local registry corrupt while remembering vault; backing up and re-seeding",
                exc_info=True,
            )
            self.app_local_store.backup_corrupt_and_reset()
            self.app_local_store.upsert_known_vault(known, make_active=True)

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
                logger.exception("vault changed subscriber failed")

    def _allow_shared_identity_heal(self, role: MachineRole, local_frontmatter: dict[str, Any]) -> bool:
        """Whether a missing ``vaultId`` may be healed by writing the shared vault.md.

        Read-only roles never write the shared vault. A role that otherwise allows
        writes can still opt out via ``allowSharedSettingsEdits: false`` /
        ``allowWritesToVault: false`` in its local clone settings.
        """
        if role == "readOnlySatellite":
            return False
        shared_default = role in {"primary", "automationNode", "testNode"}
        if not _bool_setting(local_frontmatter.get("allowWritesToVault"), default=role != "readOnlySatellite"):
            return False
        if not _bool_setting(local_frontmatter.get("allowSharedSettingsEdits"), default=shared_default):
            return False
        return True

    def _allow_local_identity_heal(self, role: MachineRole, local_frontmatter: dict[str, Any]) -> bool:
        """Whether a missing ``localInstanceId`` may be healed by writing local.md.

        ``local.md`` is the gitignored, machine-local settings file, so this needs
        only local-settings write authority — not shared-write authority. A
        read-only role still writes nothing (read never mutates the vault).
        """
        if role == "readOnlySatellite":
            return False
        return _bool_setting(local_frontmatter.get("allowLocalSettingsEdits"), default=True)

    def _ensure_frontmatter_id(
        self,
        path: Path,
        frontmatter: dict[str, Any],
        *,
        key: str,
        prefix: str,
        body: str,
        persist: bool = True,
    ) -> str:
        existing = str(frontmatter.get(key)).strip() if frontmatter.get(key) is not None else ""
        if existing:
            return existing
        generated = f"{prefix}-{uuid4()}"
        if not persist:
            # Read-only ceiling: provide a runtime id without mutating the vault.
            return generated
        updated = dict(frontmatter)
        updated[key] = generated
        self.markdown_store.write_frontmatter(path, updated, body=body)
        return generated


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
    "INIT_TARGET_IGNORED_ENTRIES",
    "MachineRole",
    "VaultChangedEvent",
    "VaultContext",
    "VaultInitializationResult",
    "VaultManager",
    "VaultPermissions",
    "VaultRequiredError",
    "VaultStatus",
    "VAULT_ROOT_MARKER_REL",
    "existing_init_target_entries",
    "get_vault_manager",
    "is_vault_root",
    "iter_vault_markdown_files",
    "nearest_enclosing_vault_root",
    "no_vault_context",
]
