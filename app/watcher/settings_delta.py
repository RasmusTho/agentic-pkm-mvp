from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
import subprocess
from typing import Any, Mapping

from app.vault.manager import VaultContext, VaultManager
from app.receipts.settings_write import settings_receipt_old_value
from app.settings.locations import CANONICAL_SETTINGS_DIR_NAME, LEGACY_COMPILED_DIR
from app.vault.markdown_settings import (
    MarkdownSettingsDocument,
    MarkdownSettingsError,
    MarkdownSettingsStore,
    split_markdown_settings,
)
from app.vault.settings_service import (
    RUNTIME_GATING_SETTINGS,
    SETTING_DEFINITIONS,
    SettingsService,
    SettingsWriteError,
    SettingsWriteReceipt,
)

SETTINGS_LOCAL_REL = Path("settings/local.md")
SETTINGS_YOUTUBE_REL = Path("settings/youtube.md")
_STATE_VAULT_ID = "__accepted_runtime_gating_vault_id__"
_STATE_LOCAL_INSTANCE_ID = "__accepted_runtime_gating_local_instance_id__"

# Derived entirely from SETTING_DEFINITIONS so a future runtime-gating key in
# a third owner file cannot silently bypass the governed delta path: every
# gating definition contributes its own file here by construction.
_RUNTIME_GATING_KEYS_BY_FILE: dict[Path, frozenset[str]] = {
    rel_path: frozenset(
        definition.key
        for definition in SETTING_DEFINITIONS
        if definition.key in RUNTIME_GATING_SETTINGS and definition.file == rel_path.name
    )
    for rel_path in {
        Path("settings") / definition.file
        for definition in SETTING_DEFINITIONS
        if definition.key in RUNTIME_GATING_SETTINGS and definition.file
    }
}

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
        "youtube.md",
    }
)


@dataclass(frozen=True)
class SettingsDeltaResult:
    values: dict[str, Any] | None
    receipts: tuple[SettingsWriteReceipt, ...] = ()
    errors: tuple[str, ...] = ()
    # True when the delta could not be routed through the governed seam at all
    # (vault not selected). Callers must NOT record the file as seen: the edit
    # has to re-process on a later tick once the vault validates, or the
    # unrouted on-disk value would silently become effective via resolution.
    deferred: bool = False
    vault_id: str | None = None
    local_instance_id: str | None = None


@dataclass(frozen=True)
class _ObservedSettingsSnapshot:
    exists: bool
    digest: str | None
    payload: bytes | None = field(default=None, compare=False, repr=False)


class _SnapshotBoundMarkdownSettingsStore(MarkdownSettingsStore):
    """Read one owner document from the exact watcher-observed snapshot."""

    def __init__(
        self,
        *,
        delegate: MarkdownSettingsStore,
        path: Path,
        snapshot: _ObservedSettingsSnapshot,
    ) -> None:
        self._delegate = delegate
        self._path = path
        self._document: MarkdownSettingsDocument | None = None
        if snapshot.exists:
            if snapshot.payload is None:
                raise MarkdownSettingsError(
                    f"settings snapshot payload is unavailable: {path}"
                )
            try:
                text = snapshot.payload.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise MarkdownSettingsError(
                    f"settings file is not valid UTF-8: {path}"
                ) from exc
            frontmatter, body = split_markdown_settings(text, path=path)
            self._document = MarkdownSettingsDocument(
                path=path,
                frontmatter=frontmatter,
                body=body,
            )

    def read(self, path: Path) -> MarkdownSettingsDocument:
        if path != self._path:
            return self._delegate.read(path)
        if self._document is None:
            raise FileNotFoundError(path)
        return self._document

    def write_missing(
        self,
        path: Path,
        frontmatter: Mapping[str, Any],
        body: str,
    ) -> bool:
        raise OSError(
            f"snapshot-bound settings processing cannot create settings file: {path}"
        )

    def write_frontmatter(
        self,
        path: Path,
        frontmatter: Mapping[str, Any],
        *,
        body: str | None = None,
    ) -> None:
        if path != self._path:
            raise OSError(
                f"snapshot-bound settings processing cannot write settings file: {path}"
            )
        if self._document is None:
            raise OSError(
                f"snapshot-bound settings processing cannot rewrite deleted owner file: {path}"
            )
        expected_body = self._document.body if body is None else body
        if (
            dict(frontmatter) != self._document.frontmatter
            or expected_body != self._document.body
        ):
            raise OSError(
                f"snapshot-bound settings processing cannot rewrite owner file: {path}"
            )
        # Watcher processing accepts already-authored bytes. Rewriting them is
        # unnecessary and could clobber a local edit that arrived after capture.


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


def is_runtime_gating_owner_path(rel_path: Path) -> bool:
    """Whether a removed path owns one or more runtime-gating settings."""
    return rel_path in _RUNTIME_GATING_KEYS_BY_FILE


def settings_delta_state_values(result: SettingsDeltaResult) -> dict[str, Any] | None:
    """Encode accepted values plus retained acceptance identity for watcher state."""

    if result.values is None:
        return None
    values = dict(result.values)
    if result.vault_id:
        values[_STATE_VAULT_ID] = result.vault_id
    if result.local_instance_id:
        values[_STATE_LOCAL_INSTANCE_ID] = result.local_instance_id
    return values


def _split_retained_settings_state(
    previous_values: Mapping[str, Any] | None,
) -> tuple[dict[str, Any] | None, str | None, str | None]:
    if previous_values is None:
        return None, None, None
    values = dict(previous_values)
    vault_id_raw = values.pop(_STATE_VAULT_ID, None)
    local_instance_id_raw = values.pop(_STATE_LOCAL_INSTANCE_ID, None)
    vault_id = str(vault_id_raw).strip() if vault_id_raw is not None else None
    local_instance_id = (
        str(local_instance_id_raw).strip()
        if local_instance_id_raw is not None
        else None
    )
    return values, vault_id or None, local_instance_id or None


def _retained_context_for_local_owner_deletion(
    *,
    vault_root: Path,
    rel_path: Path,
    document_missing: bool,
    context: VaultContext,
    store: MarkdownSettingsStore,
    retained_vault_id: str | None,
    retained_local_instance_id: str | None,
) -> VaultContext | None:
    """Recover only the identity needed to receipt an observed local.md deletion."""

    if (
        rel_path != SETTINGS_LOCAL_REL
        or not document_missing
        or context.status != "uninitialized"
        or not retained_vault_id
        or not retained_local_instance_id
    ):
        return None
    try:
        vault_document = store.read(vault_root / "settings" / "vault.md")
    except (FileNotFoundError, OSError, MarkdownSettingsError):
        return None
    if (
        vault_document.frontmatter.get("schema") != "design-handoff.vault.v1"
        or vault_document.frontmatter.get("vaultId") != retained_vault_id
    ):
        return None
    return VaultContext(
        status="selected",
        active_vault_id=retained_vault_id,
        active_vault_path=str(vault_root),
        settings_path=str(vault_root / "settings"),
        local_instance_id=retained_local_instance_id,
    )


def is_settings_control_path(
    rel_path: Path, *, configured_system_dir: Path | str | None = None
) -> bool:
    """True for canonical and compatibility control-plane Markdown."""

    if rel_path.suffix != ".md" or not rel_path.parts:
        return False
    if rel_path.parts[0] in {SETTINGS_SOURCE_DIR_NAME, LEGACY_COMPILED_DIR.name}:
        return True
    if configured_system_dir is not None:
        configured_root = Path(configured_system_dir)
        if any(
            rel_path == root or rel_path.is_relative_to(root)
            for root in (
                configured_root / "settings",
                configured_root / "Settings",
            )
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
    surface: str = "file",
    actor: str = "human",
    _verified_snapshot: _ObservedSettingsSnapshot | None = None,
) -> SettingsDeltaResult:
    """Route watcher-detected runtime-gating file deltas through the governed seam.

    The historical function name is retained for callers, but the seam covers
    both the vault-local runtime controls and the vault-shared YouTube master
    switch. A blocked edit remains on disk as human-authored input (the
    vault-shared owner file is git-synced across machines, so this seam never
    rewrites it: a denial on one machine must not clobber a value another
    machine legitimately accepted and receipted); the returned ACCEPTED
    values stay at the last guarded state and the denial surfaces via
    ``errors`` with no success receipt. Because ``SettingsService.resolve``
    re-reads the owner file directly, the future YSS-06/YSS-10 consumers MUST
    consume the accepted accessor for the two YouTube gates, never raw
    resolution. Existing watcher/indexing gates keep their established
    permissions path outside #3964. When the vault is not
    selected the delta cannot be routed at all and the result is marked
    ``deferred``: callers skip recording the file as seen so the edit
    re-processes once the vault validates.
    """

    gating_keys = _RUNTIME_GATING_KEYS_BY_FILE.get(rel_path)
    if gating_keys is None:
        return SettingsDeltaResult(values=None)

    previous_runtime_values, retained_vault_id, retained_local_instance_id = (
        _split_retained_settings_state(previous_values)
    )

    store = markdown_store or MarkdownSettingsStore()
    path = vault_root / rel_path
    if _verified_snapshot is not None:
        try:
            processing_snapshot = _capture_settings_snapshot(path)
        except OSError as exc:
            return SettingsDeltaResult(
                values=dict(previous_runtime_values or {}),
                errors=(str(exc),),
                deferred=True,
                vault_id=retained_vault_id,
                local_instance_id=retained_local_instance_id,
            )
        if processing_snapshot != _verified_snapshot:
            return SettingsDeltaResult(
                values=dict(previous_runtime_values or {}),
                errors=(
                    f"{rel_path.as_posix()} changed before governed processing",
                ),
                deferred=True,
                vault_id=retained_vault_id,
                local_instance_id=retained_local_instance_id,
            )
        try:
            store = _SnapshotBoundMarkdownSettingsStore(
                delegate=store,
                path=path,
                snapshot=processing_snapshot,
            )
        except MarkdownSettingsError as exc:
            return SettingsDeltaResult(values=None, errors=(str(exc),))
    try:
        document = store.read(path)
    except FileNotFoundError:
        # A registered owner-file deletion is an authority-bearing reset, not
        # an absent signal that may silently fall back through raw resolution.
        # Continue below with no current values so every formerly accepted
        # gating key is routed through ``update_setting(..., persist=False)``.
        document = None
    except (OSError, MarkdownSettingsError) as exc:
        return SettingsDeltaResult(values=None, errors=(str(exc),))

    current_values = {
        key: document.frontmatter[key]
        for key in sorted(gating_keys)
        if document is not None and key in document.frontmatter
    }
    service = settings_service or SettingsService(markdown_store=store)
    manager = VaultManager(markdown_store=store)
    if (
        _verified_snapshot is not None
        and not _verified_snapshot.exists
        and rel_path == SETTINGS_LOCAL_REL
    ):
        context = VaultContext(
            status="uninitialized",
            active_vault_name=vault_root.name,
            active_vault_path=str(vault_root),
            settings_path=str(vault_root / "settings"),
            validation_error="missing required settings: local.md",
        )
    else:
        context = manager.validate_vault(vault_root)
    retained_context = _retained_context_for_local_owner_deletion(
        vault_root=vault_root,
        rel_path=rel_path,
        document_missing=document is None,
        context=context,
        store=store,
        retained_vault_id=retained_vault_id,
        retained_local_instance_id=retained_local_instance_id,
    )
    if retained_context is not None:
        context = retained_context
    if context.status != "selected":
        fallback_values = dict(previous_runtime_values or {})
        detail = f": {context.validation_error}" if context.validation_error else ""
        return SettingsDeltaResult(
            values=fallback_values,
            errors=(
                f"{rel_path.as_posix()} delta requires selected vault; "
                f"status={context.status}{detail}",
            ),
            deferred=True,
            vault_id=retained_vault_id,
            local_instance_id=retained_local_instance_id,
        )

    if previous_runtime_values is None:
        # A lost/empty watcher state is not evidence that an on-disk gate was
        # previously accepted. Rebuild the YSS baseline from receipts bound to
        # this vault identity/generation; keys outside #3964 retain their
        # established registered defaults.
        durable_accepted = service.resolve_accepted_runtime_gating(context)
        accepted_previous_values = {
            key: (
                durable_accepted[key].value
                if key in durable_accepted
                else definition.default_value
            )
            for key in gating_keys
            if (definition := service.registry.get(key)) is not None
        }
    else:
        # State created by older releases may contain cross-file gating keys.
        # Discard those values rather than carrying an invalid authority source
        # forward after the ownership rule is tightened.
        accepted_previous_values = {
            key: value
            for key, value in previous_runtime_values.items()
            if key in gating_keys
        }

    resolution = service.resolve(context)
    errors = []
    for error in resolution.validation_errors:
        definition = service.registry.get(error.key) if error.key else None
        if (
            error.source_file == str(path)
            and definition is not None
            and definition.key in RUNTIME_GATING_SETTINGS
            and definition.file != rel_path.name
        ):
            errors.append(error.message)
    previous_values = accepted_previous_values
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
        return SettingsDeltaResult(
            values=current_values,
            errors=tuple(errors),
            vault_id=context.active_vault_id,
            local_instance_id=context.local_instance_id,
        )

    receipts: list[SettingsWriteReceipt] = []
    accepted_values = dict(current_values)
    for key in changed_keys:
        try:
            persist = key in current_keys
            value = current_values[key] if persist else resolution.settings[key].value
            with settings_receipt_old_value(previous_values.get(key)):
                _effective, receipt = service.update_setting(
                    context,
                    key,
                    value,
                    surface=surface,
                    actor=actor,
                    persist=persist,
                )
        except SettingsWriteError as exc:
            errors.append(str(exc))
            if key in previous_values:
                accepted_values[key] = previous_values[key]
            else:
                accepted_values.pop(key, None)
            continue
        receipts.append(receipt)
        if not persist and document is None:
            # The entire registered owner file disappeared. Retain the
            # explicitly accepted default in watcher state so a later
            # reappearance compares against the governed reset rather than
            # treating the old on-disk value as trusted history.
            accepted_values[key] = value

    return SettingsDeltaResult(
        values=accepted_values,
        receipts=tuple(receipts),
        errors=tuple(errors),
        vault_id=context.active_vault_id,
        local_instance_id=context.local_instance_id,
    )


def handle_settings_sync_arrival(
    *,
    vault_root: Path,
    rel_path: Path,
    previous_values: Mapping[str, Any] | None,
    settings_service: SettingsService | None = None,
    markdown_store: MarkdownSettingsStore | None = None,
    _verified_snapshot: _ObservedSettingsSnapshot | None = None,
) -> SettingsDeltaResult:
    """Replay a git-synced settings arrival without misattributing its actor.

    Sync arrival is still locally WriteGuard-gated and receipted, but it is
    evidence of synchronization rather than a local human edit.  This keeps
    the same accepted-state enforcement without inventing another approval or
    persistence path.
    """
    return handle_settings_local_delta(
        vault_root=vault_root,
        rel_path=rel_path,
        previous_values=previous_values,
        settings_service=settings_service,
        markdown_store=markdown_store,
        surface="sync",
        actor="sync",
        _verified_snapshot=_verified_snapshot,
    )


def _capture_settings_snapshot(path: Path) -> _ObservedSettingsSnapshot:
    try:
        payload = path.read_bytes()
    except FileNotFoundError:
        return _ObservedSettingsSnapshot(exists=False, digest=None)
    return _ObservedSettingsSnapshot(
        exists=True,
        digest=hashlib.sha256(payload).hexdigest(),
        payload=payload,
    )


def _git_snapshot_is_sync_arrival(
    *, vault_root: Path, rel_path: Path, snapshot: _ObservedSettingsSnapshot
) -> bool:
    try:
        inside = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=vault_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if inside.returncode != 0 or inside.stdout.strip() != "true":
            return False
        status = subprocess.run(
            [
                "git",
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
                "--",
                rel_path.as_posix(),
            ],
            cwd=vault_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if status.returncode != 0 or status.stdout.strip():
            return False

        tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", rel_path.as_posix()],
            cwd=vault_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if snapshot.exists:
            if tracked.returncode != 0 or snapshot.digest is None:
                return False
            head_blob = subprocess.run(
                ["git", "show", f"HEAD:{rel_path.as_posix()}"],
                cwd=vault_root,
                capture_output=True,
                check=False,
            )
            return (
                head_blob.returncode == 0
                and hashlib.sha256(head_blob.stdout).hexdigest() == snapshot.digest
            )
        if tracked.returncode == 0:
            return False

        head_change = subprocess.run(
            [
                "git",
                "diff-tree",
                "--root",
                "--no-commit-id",
                "--name-status",
                "-r",
                "HEAD",
                "--",
                rel_path.as_posix(),
            ],
            cwd=vault_root,
            capture_output=True,
            text=True,
            check=False,
        )
        return head_change.returncode == 0 and any(
            line.startswith("D\t") for line in head_change.stdout.splitlines()
        )
    except OSError:
        return False


def settings_delta_is_sync_arrival(*, vault_root: Path, rel_path: Path) -> bool:
    """Return true when the observed settings bytes are clean Git state.

    The production watcher is filesystem-polled, so Git cleanliness is the
    available provenance boundary: a tracked clean file (or clean tracked
    deletion) arrived through repository synchronization; a modified or
    untracked working-tree file remains a local file edit. Non-Git vaults and
    Git inspection failures conservatively stay local-human.
    """

    try:
        before = _capture_settings_snapshot(vault_root / rel_path)
    except OSError:
        return False
    is_sync = _git_snapshot_is_sync_arrival(
        vault_root=vault_root,
        rel_path=rel_path,
        snapshot=before,
    )
    try:
        after = _capture_settings_snapshot(vault_root / rel_path)
    except OSError:
        return False
    return is_sync and after == before


def handle_settings_detected_delta(
    *,
    vault_root: Path,
    rel_path: Path,
    previous_values: Mapping[str, Any] | None,
    observed_digest: str | None = None,
    observed_missing: bool | None = None,
) -> SettingsDeltaResult:
    """Dispatch a production watcher delta with its real local/sync provenance."""

    if observed_missing is None:
        try:
            before = _capture_settings_snapshot(vault_root / rel_path)
        except OSError as exc:
            previous_runtime_values, retained_vault_id, retained_local_instance_id = (
                _split_retained_settings_state(previous_values)
            )
            return SettingsDeltaResult(
                values=dict(previous_runtime_values or {}),
                errors=(str(exc),),
                deferred=True,
                vault_id=retained_vault_id,
                local_instance_id=retained_local_instance_id,
            )
    else:
        before = _ObservedSettingsSnapshot(
            exists=not observed_missing,
            digest=None if observed_missing else observed_digest,
        )

    is_sync = _git_snapshot_is_sync_arrival(
        vault_root=vault_root,
        rel_path=rel_path,
        snapshot=before,
    )
    try:
        after = _capture_settings_snapshot(vault_root / rel_path)
    except OSError as exc:
        after = None
        race_error = str(exc)
    else:
        race_error = (
            f"{rel_path.as_posix()} changed during provenance inspection"
        )
    if after != before:
        previous_runtime_values, retained_vault_id, retained_local_instance_id = (
            _split_retained_settings_state(previous_values)
        )
        return SettingsDeltaResult(
            values=dict(previous_runtime_values or {}),
            errors=(race_error,),
            deferred=True,
            vault_id=retained_vault_id,
            local_instance_id=retained_local_instance_id,
        )

    if is_sync:
        return handle_settings_sync_arrival(
            vault_root=vault_root,
            rel_path=rel_path,
            previous_values=previous_values,
            _verified_snapshot=after,
        )
    return handle_settings_local_delta(
        vault_root=vault_root,
        rel_path=rel_path,
        previous_values=previous_values,
        _verified_snapshot=after,
    )


__all__ = [
    "SETTINGS_LOCAL_REL",
    "SETTINGS_YOUTUBE_REL",
    "SETTINGS_SOURCE_DIR_NAME",
    "SettingsDeltaResult",
    "SettingsSourceDeltaResult",
    "handle_settings_local_delta",
    "handle_settings_detected_delta",
    "handle_settings_sync_arrival",
    "handle_settings_source_delta",
    "is_runtime_gating_owner_path",
    "is_settings_source_path",
    "is_settings_control_path",
    "settings_delta_state_values",
    "settings_delta_is_sync_arrival",
]
