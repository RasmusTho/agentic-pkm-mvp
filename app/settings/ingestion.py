"""Startup + reload ingestion of vault-authored settings (SETTINGS-01 / SET-1).

Audit F1: the md→runtime settings pipeline (``compile_all`` →
``runtime/settings/*.yaml`` → ``get_settings_bundle``) was invoked only by the
manual CLI and CI, so every running service silently served pydantic code
defaults. This module is the single place running services call at startup — and
the watcher calls on a settings-source edit — so vault-authored settings actually
take effect, or a degraded state is surfaced loudly on ``/api/health``, never a
silent fallback to code defaults.

Reload reuses the existing hot-reload bus: ``compile_all`` emits ``settings.changed``
(``app/settings/compiler.py``), which ``app/settings/hotreload.py`` subscribes to
and rebuilds the in-memory bundle. This module adds no second loader; it wraps the
existing compile step with the ingestion-state tracking the health contract needs.

Scope boundary: binding settings-source resolution to the *selected* vault path
(rather than the ``compiler.VAULT`` convention) is SETTINGS-05
(``REBIND_ON_VAULT_SELECTION``), explicitly out of scope here.
"""

from __future__ import annotations

import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config.paths import VaultRootMisconfiguredError, resolve_optional_vault_root
from app.settings import compiler
from app.settings.runtime import reload_settings_bundle

# Vault-relative settings-source directory (compiled into the effective bundle).
SETTINGS_SOURCE_DIR_NAME = "@Settings"

# Ingestion states surfaced on the health contract.
STATE_OK = "ok"
STATE_DEGRADED = "degraded_last_valid"
STATE_INVALID = "invalid_sources"
STATE_NO_VAULT = "no_vault"

_VALID_PRIOR_STATES = frozenset({STATE_OK, STATE_DEGRADED})

_STATE_LOCK = threading.RLock()


@dataclass(frozen=True)
class SettingsIngestionState:
    """Effective-settings ingestion status, surfaced on ``/api/health``."""

    state: str
    source: str  # "vault" | "defaults"
    loaded_at: str | None = None
    error: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


# Boot default: nothing ingested yet. Truthful "no_vault" on defaults until the
# first ingest runs; never claims a vault source before an ingest succeeds.
_STATE = SettingsIngestionState(state=STATE_NO_VAULT, source="defaults")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _has_settings_sources(vault_settings_dir: Path) -> bool:
    return vault_settings_dir.exists() and any(vault_settings_dir.glob("*.md"))


def _selected_settings_source_dir() -> Path | None:
    """The ``@Settings`` dir of the *selected* vault, or None when no vault is bound.

    Ingestion is scoped to a genuinely selected vault (spec: settings take effect
    "when a vault with settings sources is selected"). A set-but-missing vault root
    is treated as no-vault here rather than raising — startup must never crash on a
    misconfigured root; the missing-vault posture is already surfaced elsewhere."""
    try:
        vault_root = resolve_optional_vault_root()
    except VaultRootMisconfiguredError:
        return None
    if vault_root is None:
        return None
    return vault_root / SETTINGS_SOURCE_DIR_NAME


def get_settings_ingestion_state() -> SettingsIngestionState:
    with _STATE_LOCK:
        return _STATE


def _set_state(state: SettingsIngestionState) -> None:
    global _STATE
    with _STATE_LOCK:
        _STATE = state


def reset_settings_ingestion_state() -> None:
    """Reset to the boot default. Test-support only — not used by production code."""
    _set_state(SettingsIngestionState(state=STATE_NO_VAULT, source="defaults"))


def ingest_settings(
    *, reason: str, vault_settings_dir: Path | None = None
) -> SettingsIngestionState:
    """Resolve vault-authored settings into the effective bundle.

    Called at service startup (API lifespan, watcher, worker) and by the watcher
    on a settings-source edit. Invalid sources never substitute code defaults
    while a last-valid bundle exists — they degrade loudly instead.

    ``reason`` is a free-text provenance tag for observability; it does not change
    behavior.
    """
    # Ingest the *selected* vault's @Settings, not the packaged compiler.VAULT
    # convention — so a test/boot with no selected settings sources stays on typed
    # defaults instead of silently compiling the repo fixture into the live bundle.
    sources_dir = (
        vault_settings_dir
        if vault_settings_dir is not None
        else _selected_settings_source_dir()
    )
    prior = get_settings_ingestion_state()
    had_valid = prior.state in _VALID_PRIOR_STATES

    if sources_dir is None or not _has_settings_sources(sources_dir):
        # No-vault boot is unchanged: the bundle builds from typed defaults, no
        # error, no ./vault fallback. Only assert no_vault on a genuine cold boot;
        # do not clobber a previously-loaded valid bundle on a transient empty read.
        if not had_valid:
            _set_state(
                SettingsIngestionState(
                    state=STATE_NO_VAULT, source="defaults", loaded_at=_now_iso()
                )
            )
        return get_settings_ingestion_state()

    try:
        # compile_all parses + hydrates every source before writing any yaml, so an
        # invalid source raises here BEFORE the runtime projection is touched — the
        # last-valid in-memory bundle stays intact. On success it emits
        # settings.changed for other bus subscribers; we then reload the bundle
        # explicitly (the same existing loader the bus path uses — not a second
        # one) so ingestion never depends on the global subscription still being
        # registered to actually take effect.
        compiler.compile_all(auto_heal=False, vault_dir=sources_dir)
        reload_settings_bundle()
    except Exception as exc:
        if had_valid:
            degraded = SettingsIngestionState(
                state=STATE_DEGRADED,
                source="vault",
                loaded_at=prior.loaded_at,
                error=str(exc),
            )
        else:
            # No last-valid bundle to fall back to: boot on defaults, but say so
            # loudly (distinct from ok) instead of pretending the sources loaded.
            degraded = SettingsIngestionState(
                state=STATE_INVALID,
                source="defaults",
                loaded_at=_now_iso(),
                error=str(exc),
            )
        _set_state(degraded)
        return degraded

    _set_state(
        SettingsIngestionState(state=STATE_OK, source="vault", loaded_at=_now_iso())
    )
    return get_settings_ingestion_state()


__all__ = [
    "SettingsIngestionState",
    "STATE_OK",
    "STATE_DEGRADED",
    "STATE_INVALID",
    "STATE_NO_VAULT",
    "ingest_settings",
    "get_settings_ingestion_state",
    "reset_settings_ingestion_state",
]
