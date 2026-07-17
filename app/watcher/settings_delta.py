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
    SETTING_DEFINITIONS,
    SettingsService,
    SettingsWriteError,
    SettingsWriteReceipt,
)

SETTINGS_LOCAL_REL = Path("settings/local.md")
SETTINGS_YOUTUBE_REL = Path("settings/youtube.md")

_RUNTIME_GATING_KEYS_BY_FILE: dict[Path, frozenset[str]] = {
    rel_path: frozenset(
        definition.key
        for definition in SETTING_DEFINITIONS
        if definition.key in RUNTIME_GATING_SETTINGS and definition.file == rel_path.name
    )
    for rel_path in (SETTINGS_LOCAL_REL, SETTINGS_YOUTUBE_REL)
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
) -> SettingsDeltaResult:
    """Route watcher-detected runtime-gating file deltas through the governed seam.

    The historical function name is retained for callers, but the seam covers
    both the vault-local runtime controls and the vault-shared YouTube master
    switch. A blocked edit is REVERTED on disk to the last accepted state:
    the gating seam controls the settings source of truth, and any consumer
    that calls ``SettingsService.resolve`` re-reads the owner file directly,
    so a denied value left on disk would become effective through resolution
    and bypass the gate. The denial (and the revert) surface via ``errors``
    with no success receipt; the human re-applies the edit once the guard
    allows writes again.
    """

    gating_keys = _RUNTIME_GATING_KEYS_BY_FILE.get(rel_path)
    if gating_keys is None:
        return SettingsDeltaResult(values=None)

    store = markdown_store or MarkdownSettingsStore()
    path = vault_root / rel_path
    try:
        document = store.read(path)
    except (FileNotFoundError, OSError, MarkdownSettingsError) as exc:
        return SettingsDeltaResult(values=None, errors=(str(exc),))

    current_values = {
        key: document.frontmatter[key]
        for key in sorted(gating_keys)
        if key in document.frontmatter
    }
    service = settings_service or SettingsService(markdown_store=store)
    if previous_values is None:
        # A lost/empty watcher state is not evidence that an on-disk gate was
        # previously accepted. Treat each present value as a transition from
        # its registered safe/default baseline so activation still requires
        # WriteGuard and a durable receipt.
        accepted_previous_values = {
            key: definition.default_value
            for key in current_values
            if (definition := service.registry.get(key)) is not None
        }
    else:
        # State created by older releases may contain cross-file gating keys.
        # Discard those values rather than carrying an invalid authority source
        # forward after the ownership rule is tightened.
        accepted_previous_values = {
            key: value for key, value in previous_values.items() if key in gating_keys
        }

    manager = VaultManager(markdown_store=store)
    context = manager.validate_vault(vault_root)
    if context.status != "selected":
        detail = f": {context.validation_error}" if context.validation_error else ""
        return SettingsDeltaResult(
            values=accepted_previous_values,
            errors=(
                f"{rel_path.as_posix()} delta requires selected vault; "
                f"status={context.status}{detail}",
            ),
        )

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
        return SettingsDeltaResult(values=current_values, errors=tuple(errors))

    receipts: list[SettingsWriteReceipt] = []
    accepted_values = dict(current_values)
    denied_keys: list[str] = []
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
            denied_keys.append(key)
            if key in previous_values:
                accepted_values[key] = previous_values[key]
            else:
                accepted_values.pop(key, None)
            continue
        receipts.append(receipt)

    if denied_keys:
        _revert_denied_gating_keys(
            store=store,
            path=path,
            accepted=accepted_values,
            denied_keys=denied_keys,
            errors=errors,
        )

    return SettingsDeltaResult(
        values=accepted_values,
        receipts=tuple(receipts),
        errors=tuple(errors),
    )


def _revert_denied_gating_keys(
    *,
    store: MarkdownSettingsStore,
    path: Path,
    accepted: Mapping[str, Any],
    denied_keys: list[str],
    errors: list[str],
) -> None:
    """Restore denied runtime-gating keys in their owner file to the accepted state.

    The gating seam controls the settings source of truth: a WriteGuard-denied
    file edit must not stay on disk where ``SettingsService.resolve`` (or any
    other reader of the owner file) would surface the denied value as
    effective. Reverting is the gate's own enforcement of an already-denied
    write — not a new gated settings write — so it also runs while WriteGuard
    blocks writes. A key absent from the accepted state is removed from the
    file; a revert failure is surfaced loudly and the denial errors remain.
    """
    try:
        document = store.read(path)
    except (FileNotFoundError, OSError, MarkdownSettingsError) as exc:
        errors.append(f"failed to revert denied gating edit in {path.name}: {exc}")
        return
    frontmatter = dict(document.frontmatter)
    reverted: list[str] = []
    for key in denied_keys:
        if key in accepted:
            if frontmatter.get(key) != accepted[key]:
                frontmatter[key] = accepted[key]
                reverted.append(key)
        elif key in frontmatter:
            del frontmatter[key]
            reverted.append(key)
    if not reverted:
        return
    try:
        store.write_frontmatter(path, frontmatter, body=document.body)
    except (OSError, MarkdownSettingsError) as exc:
        errors.append(f"failed to revert denied gating edit in {path.name}: {exc}")
        return
    errors.append(
        f"{path.name}: denied runtime-gating edit reverted to last accepted state: "
        + ", ".join(sorted(reverted))
    )


__all__ = [
    "SETTINGS_LOCAL_REL",
    "SETTINGS_YOUTUBE_REL",
    "SETTINGS_SOURCE_DIR_NAME",
    "SettingsDeltaResult",
    "SettingsSourceDeltaResult",
    "handle_settings_local_delta",
    "handle_settings_source_delta",
    "is_settings_source_path",
    "is_settings_control_path",
]
