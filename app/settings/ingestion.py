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

import hashlib
import json
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config.environment import active_environment
from app.config.paths import VaultRootMisconfiguredError, resolve_optional_vault_root
from app.settings import compiler
from app.settings import runtime
from app.settings.locations import (
    CANONICAL_SETTINGS_DIR_NAME,
    canonical_settings_root,
    resolve_compiled_sources,
)
from app.settings.reload_signal import publish_reload_signal, read_reload_signal
from app.settings.runtime import reload_settings_bundle

# Vault-relative settings-source directory (compiled into the effective bundle).
SETTINGS_SOURCE_DIR_NAME = CANONICAL_SETTINGS_DIR_NAME

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
    # This is compiled-generation metadata, not a new user setting.  It keeps
    # explain output bound to the same selected source that produced the active
    # (or retained last-valid) bundle.
    tts_origin: str = "registry default"

    def to_payload(self) -> dict[str, Any]:
        # The reload signal deliberately carries only cross-process invalidation
        # state.  Source provenance stays process-local with the generation it
        # describes, so a fresh process cannot claim another process's bundle.
        return {
            "state": self.state,
            "source": self.source,
            "loaded_at": self.loaded_at,
            "error": self.error,
        }


# Boot default: nothing ingested yet. Truthful "no_vault" on defaults until the
# first ingest runs; never claims a vault source before an ingest succeeds.
_STATE = SettingsIngestionState(state=STATE_NO_VAULT, source="defaults")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _has_settings_sources(vault_settings_dir: Path) -> bool:
    return vault_settings_dir.exists() and any(vault_settings_dir.rglob("*.md"))


def _selected_settings_source_dir() -> Path | None:
    """The canonical settings dir of the selected vault, or None when unbound.

    Ingestion is scoped to a genuinely selected vault (spec: settings take effect
    "when a vault with settings sources is selected"). A set-but-missing vault root
    is treated as no-vault here rather than raising — startup must never crash on a
    misconfigured root; the missing-vault posture is already surfaced elsewhere."""
    try:
        vault_root = resolve_optional_vault_root(environment=active_environment())
    except VaultRootMisconfiguredError:
        return None
    if vault_root is None:
        return None
    return canonical_settings_root(vault_root)


def _compiled_generation_tts_origin() -> str | None:
    """Recover TTS provenance for a fresh process reading a compiled bundle.

    ``settings explain`` may run without this process having performed ingestion.
    The runtime projection proves that a compiled generation is available; the
    selected source map identifies whether that generation included ``tts.md``.
    This keeps provenance tied to the selected settings spine rather than to a
    repository-relative path probe.
    """
    source_dir = _selected_settings_source_dir()
    manifest_path = runtime.RUNTIME / "sources.json"
    if (
        source_dir is None
        or not (runtime.RUNTIME / "tts.yaml").is_file()
        or not manifest_path.is_file()
    ):
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected = manifest["sources"]
        if manifest.get("version") != 1 or not isinstance(expected, dict):
            return None
        sources = resolve_compiled_sources(source_dir.parent)
        tts_source = sources.get(Path("tts.md"))
        actual_tts = (
            hashlib.sha256(tts_source.read_bytes()).hexdigest()
            if tts_source is not None
            else None
        )
    except (OSError, TypeError, ValueError, KeyError):
        return None
    if expected.get("tts.md") != actual_tts:
        return None
    return "vault-shared" if Path("tts.md") in sources else "registry default"


def get_compiled_generation_tts_origin() -> str | None:
    """Return provenance only when the published generation matches its sources."""
    return _compiled_generation_tts_origin()


def get_settings_ingestion_state() -> SettingsIngestionState:
    # A watcher reload runs in a different container.  Its signal carries
    # error evidence, but not this process's in-memory bundle history: a fresh
    # API must not claim ``degraded_last_valid`` when it actually booted on
    # defaults against invalid sources.
    signal = read_reload_signal()
    prior = _get_local_ingestion_state()
    if signal is not None and signal.state != STATE_OK and prior.state in _VALID_PRIOR_STATES:
        _set_state(
            SettingsIngestionState(
                state=STATE_DEGRADED,
                source="vault",
                loaded_at=prior.loaded_at,
                error=signal.error,
                tts_origin=prior.tts_origin,
            )
        )
    with _STATE_LOCK:
        return _STATE


def _set_state(state: SettingsIngestionState) -> None:
    global _STATE
    with _STATE_LOCK:
        _STATE = state


def _get_local_ingestion_state() -> SettingsIngestionState:
    """Return this process's state without importing a watcher's signal.

    Degradation semantics depend on whether *this process* has a last-valid
    bundle. A previous watcher generation must not make a fresh process claim
    it has retained a bundle it never loaded.
    """
    with _STATE_LOCK:
        return _STATE


def reset_settings_ingestion_state() -> None:
    """Reset to the boot default. Test-support only — not used by production code."""
    _set_state(SettingsIngestionState(state=STATE_NO_VAULT, source="defaults"))


def ingest_settings(
    *,
    reason: str,
    vault_settings_dir: Path | None = None,
    vault_root: Path | None = None,
    publish_signal: bool = False,
) -> SettingsIngestionState:
    """Resolve vault-authored settings into the effective bundle.

    Called at service startup (API lifespan, watcher, worker) and by the watcher
    on a settings-source edit. Invalid sources never substitute code defaults
    while a last-valid bundle exists — they degrade loudly instead.

    ``reason`` is a free-text provenance tag for observability; it does not change
    behavior.
    """
    # Ingest the selected vault's canonical settings (plus bounded compatibility), not compiler.VAULT
    # convention — so a test/boot with no selected settings sources stays on typed
    # defaults instead of silently compiling the repo fixture into the live bundle.
    if vault_settings_dir is not None and vault_root is not None:
        raise ValueError("pass vault_settings_dir or vault_root, not both")
    sources_dir = vault_settings_dir if vault_settings_dir is not None else _selected_settings_source_dir()
    selected_root = Path(vault_root) if vault_root is not None else (sources_dir.parent if sources_dir else None)
    prior = _get_local_ingestion_state()
    had_valid = prior.state in _VALID_PRIOR_STATES

    has_sources = False
    if selected_root is not None:
        has_sources = bool(resolve_compiled_sources(selected_root))
    elif sources_dir is not None:
        has_sources = _has_settings_sources(sources_dir)
    if not has_sources:
        # No-vault boot is unchanged: the bundle builds from typed defaults, no
        # error, no ./vault fallback. Only assert no_vault on a genuine cold boot;
        # do not clobber a previously-loaded valid bundle on a transient empty read.
        if not had_valid:
            _set_state(
                SettingsIngestionState(
                    state=STATE_NO_VAULT, source="defaults", loaded_at=_now_iso()
                )
            )
        with _STATE_LOCK:
            result = _STATE
        if publish_signal:
            publish_reload_signal(**result.to_payload())
        return result

    try:
        # compile_all parses + hydrates every source before writing any yaml, so an
        # invalid source raises here BEFORE the runtime projection is touched — the
        # last-valid in-memory bundle stays intact. On success it emits
        # settings.changed for other bus subscribers; we then reload the bundle
        # explicitly (the same existing loader the bus path uses — not a second
        # one) so ingestion never depends on the global subscription still being
        # registered to actually take effect.
        if selected_root is not None:
            compiled_sources = resolve_compiled_sources(selected_root)
            compiler.compile_all(auto_heal=False, vault_root=selected_root)
            tts_origin = (
                "vault-shared"
                if Path("tts.md") in compiled_sources
                else "registry default"
            )
        else:
            compiler.compile_all(auto_heal=False, vault_dir=sources_dir)
            tts_origin = "vault-shared" if (sources_dir / "tts.md").exists() else "registry default"
        reload_settings_bundle()
    except Exception as exc:
        if had_valid:
            degraded = SettingsIngestionState(
                state=STATE_DEGRADED,
                source="vault",
                loaded_at=prior.loaded_at,
                error=str(exc),
                tts_origin=prior.tts_origin,
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
        if publish_signal:
            publish_reload_signal(**degraded.to_payload())
        return degraded

    result = SettingsIngestionState(
        state=STATE_OK,
        source="vault",
        loaded_at=_now_iso(),
        tts_origin=tts_origin,
    )
    _set_state(result)
    if publish_signal:
        publish_reload_signal(**result.to_payload())
    return result


__all__ = [
    "SettingsIngestionState",
    "STATE_OK",
    "STATE_DEGRADED",
    "STATE_INVALID",
    "STATE_NO_VAULT",
    "ingest_settings",
    "get_settings_ingestion_state",
    "get_compiled_generation_tts_origin",
    "reset_settings_ingestion_state",
]
