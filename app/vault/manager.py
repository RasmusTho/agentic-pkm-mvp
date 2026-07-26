from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
import os
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING, Any, Callable, Iterator, Literal
from uuid import uuid4

from app.instance.vault_registry import AppLocalSettingsStore, KnownVaultRef
from app.knowledge.multiwriter import is_conflict_artifact
from app.vault.markdown_settings import MarkdownSettingsError, MarkdownSettingsStore

if TYPE_CHECKING:
    from app.write_guard import WriteGuard


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


ConflictArtifactState = tuple[int, int, int, int, int] | None


class _ConflictQuarantineReceiptPolicy:
    """Bound conflict-quarantine receipts without weakening quarantine.

    State keys are retained without eviction until the fixed tracking limit is
    reached. Detail receipts have a smaller fixed budget; its first overflow
    emits one aggregate suppression receipt and all later observations remain
    silent. The lock owns every transition, so concurrent first observations
    cannot claim duplicate receipts.

    This is deliberately process-local operational state. A process restart
    resets both budgets and can therefore emit a fresh bounded set of receipts.
    Quarantine itself does not depend on this state: every classified artifact
    remains excluded even after tracking or receipt capacity is exhausted.
    """

    def __init__(
        self,
        *,
        max_tracked_states: int = 4096,
        max_detail_receipts: int = 32,
    ) -> None:
        if max_detail_receipts < 1:
            raise ValueError("max_detail_receipts must be positive")
        if max_tracked_states < max_detail_receipts:
            raise ValueError(
                "max_tracked_states must be at least max_detail_receipts"
            )
        self._max_tracked_states = max_tracked_states
        self._max_detail_receipts = max_detail_receipts
        self._seen_states: set[tuple[str, ConflictArtifactState]] = set()
        self._detail_receipts = 0
        self._suppression_receipt_emitted = False
        self._lock = Lock()

    def observe(
        self,
        artifact_path: str,
        state_signature: ConflictArtifactState,
    ) -> None:
        """Observe one quarantined state and emit at most one bounded receipt."""

        state_key = (artifact_path, state_signature)
        receipt_kind: Literal["detail", "suppression_summary"] | None = None
        suppressed_observations = 0
        with self._lock:
            if state_key in self._seen_states:
                return
            if len(self._seen_states) < self._max_tracked_states:
                self._seen_states.add(state_key)

            if self._detail_receipts < self._max_detail_receipts:
                self._detail_receipts += 1
                receipt_kind = "detail"
            elif not self._suppression_receipt_emitted:
                self._suppression_receipt_emitted = True
                suppressed_observations = 1
                receipt_kind = "suppression_summary"

        if receipt_kind == "detail":
            logger.warning(
                "Vault Markdown conflict artifact quarantined before ordinary iteration: %s",
                artifact_path,
                extra={
                    "event": "vault.markdown.quarantined",
                    "receipt_kind": receipt_kind,
                    "classification": "multiwriter_conflict_artifact",
                    "artifact_path": artifact_path,
                    "artifact_state": state_signature,
                    "action": "excluded_from_iteration_preserved_on_disk",
                },
            )
        elif receipt_kind == "suppression_summary":
            logger.warning(
                "Further Vault Markdown conflict-quarantine detail receipts suppressed "
                "for this process",
                extra={
                    "event": "vault.markdown.quarantine_receipts_suppressed",
                    "receipt_kind": receipt_kind,
                    "classification": "multiwriter_conflict_artifact",
                    "artifact_path": artifact_path,
                    "artifact_state": state_signature,
                    "action": "excluded_from_iteration_preserved_on_disk",
                    "suppressed_observations": suppressed_observations,
                    "max_detail_receipts": self._max_detail_receipts,
                    "max_tracked_states": self._max_tracked_states,
                    "suppression_scope": "all_later_observations_this_process",
                    "reset_policy": "process_restart",
                },
            )


_conflict_quarantine_receipts = _ConflictQuarantineReceiptPolicy()


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
    vault_root: Path,
    *,
    subtree_root: Path | None = None,
    include_settings: bool = False,
) -> Iterator[Path]:
    """Yield markdown files owned by ``vault_root`` only (#2522).

    Nested-vault boundary: traversal of a parent vault STOPS at any deeper
    initialized child vault root (``settings/vault.md``). This keeps ingest,
    indexing, watcher scans, and recall-style enumeration from treating a child
    vault's notes as parent-owned content.

    ``subtree_root`` narrows traversal to an explicit folder under the selected
    vault. If that folder itself belongs to a deeper child vault, nothing is
    yielded under the parent identity. Traversal prunes nested child vault
    roots in-place, so the boundary stays cheap on large trees. Yielded paths
    stay in the caller's namespace (for example a symlinked selected vault
    root) while resolved paths are used only for containment/ownership checks.

    Multiwriter conflict artifacts are classified and quarantined here, before
    any watcher, ingest, index, or recall caller can parse them as ordinary
    notes. Quarantine is non-mutating: the artifact remains at its filesystem
    path and a structured warning makes the classification observable for
    later human resolution. Receipt warnings use locked, fixed-memory
    process-local observation state and a hard detail-emission budget, followed
    by one aggregate suppression receipt. A process restart resets that bounded
    operational state; quarantine itself never depends on receipt capacity.
    """
    selected_root = vault_root.expanduser()
    walk_root = (subtree_root or vault_root).expanduser()
    try:
        selected_root_real = selected_root.resolve()
        walk_root_real = walk_root.resolve()
        walk_root_real.relative_to(selected_root_real)
    except ValueError:
        return
    except OSError:
        return
    if not walk_root.is_dir():
        return
    control_roots = {
        Path(SETTINGS_DIR_NAME),
        Path("@Settings"),
        Path("_system") / "settings",
        Path("_system") / "Settings",
    }
    try:
        from app.vault.paths import get_vault_system_dir_rel

        configured_system_root = Path(get_vault_system_dir_rel(selected_root_real))
        control_roots.update(
            {
                configured_system_root / "settings",
                configured_system_root / "Settings",
            }
        )
    except (OSError, ValueError):
        pass

    def _is_control_path(relative: Path) -> bool:
        return any(relative == prefix or relative.is_relative_to(prefix) for prefix in control_roots)

    if not include_settings:
        try:
            walk_relative = walk_root_real.relative_to(selected_root_real)
        except ValueError:
            return
        if _is_control_path(walk_relative):
            return
    if walk_root_real != selected_root_real:
        if nearest_enclosing_vault_root(walk_root_real, search_root=selected_root_real) != selected_root_real:
            return

    for dirpath, dirnames, filenames in os.walk(str(walk_root)):
        kept: list[str] = []
        for name in dirnames:
            child = Path(dirpath) / name
            try:
                child_rel = child.resolve().relative_to(selected_root_real)
            except (OSError, ValueError):
                continue
            if not include_settings and _is_control_path(child_rel):
                continue
            if include_settings and _is_control_path(child_rel):
                kept.append(name)
                continue
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
            if is_conflict_artifact(candidate.name):
                try:
                    stat = candidate.stat(follow_symlinks=False)
                    state_signature: ConflictArtifactState = (
                        stat.st_dev,
                        stat.st_ino,
                        stat.st_size,
                        stat.st_mtime_ns,
                        stat.st_ctime_ns,
                    )
                except OSError:
                    state_signature = None
                _conflict_quarantine_receipts.observe(
                    str(candidate.absolute()),
                    state_signature,
                )
                continue
            if candidate.is_symlink():
                try:
                    real = candidate.resolve()
                except OSError:
                    continue
                try:
                    real_relative = real.relative_to(selected_root_real)
                except ValueError:
                    continue
                if not include_settings and _is_control_path(real_relative):
                    continue
                if nearest_enclosing_vault_root(real, search_root=selected_root_real) != selected_root_real:
                    continue
            yield candidate


class VaultManager:
    def __init__(
        self,
        *,
        app_local_store: AppLocalSettingsStore | None = None,
        markdown_store: MarkdownSettingsStore | None = None,
        write_guard: "WriteGuard | None" = None,
    ) -> None:
        self.app_local_store = app_local_store or AppLocalSettingsStore()
        self.markdown_store = markdown_store or MarkdownSettingsStore()
        # Imported lazily (not at module level): app.write_guard ->
        # health_contract -> settings.health_settings -> app.vault.paths ->
        # app.vault.manager closes a circular import back to this module
        # (the same pattern #2909/#2910 documented for other WG call sites
        # that sit deep in the settings/health import graph).
        if write_guard is None:
            from app.write_guard import DEFAULT_WRITE_GUARD

            write_guard = DEFAULT_WRITE_GUARD
        self._write_guard = write_guard
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
        # Lazy import: see the constructor's comment on the write_guard cycle.
        from app.write_guard import WritesBlockedError

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
        except (OSError, WritesBlockedError) as exc:
            # Guard-at-seam (#2910, formal-model.md gap 4 / P-4): a denying or
            # raising WriteGuard on the identity-heal write is a fail-closed
            # transition, not a silent success -- it reaches the same loud
            # "invalid" VaultContext branch as an OSError persist failure,
            # never a swallowed exception and never a crash out of vault
            # selection (this method sits on read/select call paths: watcher
            # registry/config, load_last_active, orientation routes).
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

        # Ensure the vault is capture-ready immediately (#3120): a vault
        # initialized purely through the Companion UI's "Initialize a vault
        # here" action previously left ``vault.layout.md`` unwritten, so the
        # first quick-capture failed with "vault inbox note convention could
        # not be resolved" until an operator ran
        # ``python -m app.cli vault-layout-ensure`` by hand -- a dead end for a
        # browser-only new user.
        #
        # Deliberately ``load_or_create_layout`` (note-only), NOT the CLI
        # command's ``ensure_vault_layout_report`` (note + eager folder mkdir
        # + system note): the capture path only needs ``vault.layout.md`` to
        # exist so ``load_layout`` resolves ``inbox_folder`` -- the actual
        # inbox write creates its own parent directory on demand. Eagerly
        # mkdir-ing every layout folder here reintroduced the #2183/#2210
        # regression this NOTE used to warn about (this time caught by
        # tests/watcher/test_scope_zero_match_signal.py::test_missing_scope_prefix_warns,
        # which depends on a fresh init-only vault NOT pre-creating its scope
        # prefix directory). ``load_or_create_layout`` is idempotent (a no-op
        # if a layout note already exists) and derives folder names from this
        # vault's own ``system-settings.yaml`` (none yet at fresh init, so it
        # falls back to the packaged default layout) -- the exact same
        # default the CRE read-side fallback
        # (``resolve_vault_system_dir_rel_or_default``) already treats as
        # authoritative. Best-effort -- a layout-note failure must never fail
        # vault init itself, matching the bootstrap-escape contract in
        # app/vault/layout.py (LAYOUT_ENSURE_ACTION).
        try:
            from app.vault.layout import load_or_create_layout

            load_or_create_layout(expanded)
        except Exception:
            logger.warning(
                "vault-layout-ensure best-effort provisioning failed during initialize_vault; "
                "capture may require a manual `python -m app.cli vault-layout-ensure` run",
                exc_info=True,
            )

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
        """Heal a missing vault/local identity id, WG-gated at the write (#2910).

        This is an explicit heal transition (formal-model.md §3 Q4 / P-3): a
        missing ``vaultId``/``localInstanceId`` is healed by writing it back to
        the settings file, registered here (not undocumented) and gated by the
        same WriteGuard every other vault-write seam consults. A denying or
        raising guard raises ``WritesBlockedError`` to the caller (currently
        ``validate_vault``, which converts it into a loud ``invalid``
        VaultContext rather than swallowing it or persisting a partial write).
        """
        existing = str(frontmatter.get(key)).strip() if frontmatter.get(key) is not None else ""
        if existing:
            return existing
        generated = f"{prefix}-{uuid4()}"
        if not persist:
            # Read-only ceiling: provide a runtime id without mutating the vault.
            return generated
        self._write_guard.assert_writes_allowed("vault.identity_heal")
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


def _static_shared_settings_seeds() -> tuple[tuple[str, dict[str, Any], str], ...]:
    """Seeds for shared settings files that need no vault-specific values.

    New-vault initialization and existing-vault scaffold-on-write use this
    one source. Parameterized ``vault.md`` and ``local.md`` intentionally do
    not appear here and remain fail-loud when missing.
    """
    return (
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
            "youtube.md",
            {
                "schema": "design-handoff.youtube-sync.v1",
                "scope": "vault-shared",
                "youtubeSync.enabled": False,
                "youtubeSync.inboxPollSeconds": 180,
                "youtubeSync.playlistPollSeconds": 3600,
                "youtubeSync.subscriptionsPollSeconds": 21600,
                "youtubeSync.reconcileIntervalDays": 7,
                "youtubeSync.maxConcurrentAcquisitions": 2,
                "youtubeSync.subscriptionDefaultPolicy": "discover_only",
                "youtubeSync.captionsEnabled": True,
                "youtubeSync.mediaDownloadEnabled": False,
            },
            "# YouTube Sync Settings\nSettings for the YouTube source-sync capability (YSS).\n"
            "See docs/YOUTUBE_SOURCE_SYNC/SOURCE_SYNC_CONTRACT.md for the full settings model.\n",
        ),
    )


def shared_settings_file_seed(filename: str) -> tuple[dict[str, Any], str] | None:
    """Return a static vault-shared initializer seed, if one is safe to seed."""
    for name, frontmatter, body in _static_shared_settings_seeds():
        if name == filename:
            return frontmatter, body
    return None


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
        *_static_shared_settings_seeds(),
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
                "youtubeSync.runnerEnabled": False,
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
