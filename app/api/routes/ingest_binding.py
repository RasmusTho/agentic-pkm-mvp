"""Ingest-binding visibility check (#3119).

Vault *selection* (``VaultManager`` in-process state, set by
``POST /api/companion/vault/select`` / ``/vault/initialize``) and vault
*ingest binding* (the watcher/worker's own boot-time ``WATCHER_VAULT_PATH``,
see ``app/watcher/config.py``) are two independent binding slots by design
(#2476 — "document the split, do not converge"). A container topology with no
prior ``VAULT_HOST_ROOT``/``WATCHER_VAULT_PATH`` binding can therefore accept
a vault selection through the Companion UI while the watcher/worker continue
watching a different path (or nothing at all) — with no error surfaced
anywhere (#3119).

This module does not change that architecture. It makes the divergence
*visible*: it compares the API's currently selected vault path against the
path the watcher last reported itself bound to via its heartbeat file
(``app/watcher/heartbeat.py :: write_registry_heartbeat``, which already
carries a ``vault_path`` field). Callers use :func:`ingest_binding_status` to
decide whether to surface a warning instead of a bare success acknowledgement.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from app.watcher.heartbeat import resolve_heartbeat_path

IngestBindingState = Literal["bound", "unbound", "diverged", "unknown"]

_DEFAULT_STALE_SECONDS = 60.0


def _env_float(name: str, fallback: float) -> float:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return fallback
    try:
        return float(raw)
    except ValueError:
        return fallback


def _normalized(path_str: str | None) -> str | None:
    """Normalize a path string for comparison across processes.

    Both sides may express the same vault as an absolute path with or without
    a trailing slash, or via ``~`` expansion. Comparison is done on the
    expanded, string form rather than ``Path.resolve()`` — the API process may
    not be able to ``stat`` a path that only exists from the watcher
    container's perspective (or vice versa) under the full-host mount model
    (docs/ENVIRONMENTS.md :: Full-host access for in-process vault selection).
    """

    if not path_str:
        return None
    return str(Path(path_str).expanduser()).rstrip("/")


@dataclass(frozen=True)
class IngestBindingStatus:
    """Result of comparing the selected vault against the watcher's binding."""

    state: IngestBindingState
    selected_vault_path: str | None
    watcher_vault_path: str | None
    watcher_heartbeat_seen: bool
    watcher_heartbeat_fresh: bool
    detail: str
    rebind_schema: str | None = None
    rebind_phase: str | None = None
    rebind_desired_revision: int | None = None
    rebind_applied_revision: int | None = None
    rebind_lifecycle_posture: str | None = None
    rebind_failure_posture: str | None = None

    @property
    def is_bound(self) -> bool:
        return self.state == "bound"


def _read_watcher_heartbeat(heartbeat_path: Path) -> dict[str, object] | None:
    if not heartbeat_path.exists():
        return None
    try:
        raw = json.loads(heartbeat_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return raw if isinstance(raw, dict) else None


def _rebind_status() -> dict[str, object | None]:
    """Read durable rebind truth without making health depend on it."""

    registry_value = os.getenv("INSTANCE_VAULT_REGISTRY_PATH", "").strip()
    if not registry_value:
        return {}
    try:
        registry_path = Path(registry_value).expanduser()
        if not registry_path.is_file():
            return {}
        from app.instance.settings_rebind import SettingsRebindRecord
        from app.instance.vault_registry import VaultRegistryStore

        snapshot = VaultRegistryStore(registry_path).load()
        if snapshot.settings_rebind is None:
            return {}
        record = SettingsRebindRecord.from_payload(snapshot.settings_rebind)
        return {
            "rebind_schema": record.as_payload()["schema"],
            "rebind_phase": record.phase,
            "rebind_desired_revision": record.desired_revision,
            "rebind_applied_revision": record.applied_revision,
            "rebind_lifecycle_posture": record.lifecycle_posture,
            "rebind_failure_posture": (
                "awaiting_watcher"
                if record.phase == "prepared"
                else "awaiting_resume"
                if record.phase == "committed"
                else "none"
            ),
        }
    except Exception:
        return {"rebind_failure_posture": "invalid_record"}


def ingest_binding_status(
    *,
    selected_vault_path: str | None,
    now: float | None = None,
    heartbeat_path: Path | None = None,
    stale_seconds: float | None = None,
) -> IngestBindingStatus:
    """Compare the API's selected vault against the watcher's bound vault.

    Returns a state rather than raising: this check is advisory visibility,
    never a gate on the capture/selection write itself (the write already
    succeeded through the governed pipeline before this is consulted).

    - ``"unknown"``: no vault is selected yet (nothing to compare against).
    - ``"unbound"``: a vault is selected but the watcher has never reported a
      heartbeat, or its last heartbeat is stale — ingest is not confirmed
      running at all.
    - ``"diverged"``: the watcher is alive and reporting a *different* vault
      path than the one currently selected.
    - ``"bound"``: the watcher is alive and reports the same vault path.
    """

    now_ts = now if now is not None else time.time()
    resolved_heartbeat_path = heartbeat_path if heartbeat_path is not None else resolve_heartbeat_path()
    stale_after = stale_seconds if stale_seconds is not None else _env_float(
        "WATCHER_HEARTBEAT_STALE_SECONDS", _DEFAULT_STALE_SECONDS
    )
    rebind = _rebind_status()

    selected_norm = _normalized(selected_vault_path)
    if selected_norm is None:
        return IngestBindingStatus(
            state="unknown",
            selected_vault_path=selected_vault_path,
            watcher_vault_path=None,
            watcher_heartbeat_seen=False,
            watcher_heartbeat_fresh=False,
            detail="no vault is selected",
            **rebind,
        )

    raw = _read_watcher_heartbeat(resolved_heartbeat_path)
    if raw is None:
        return IngestBindingStatus(
            state="unbound",
            selected_vault_path=selected_vault_path,
            watcher_vault_path=None,
            watcher_heartbeat_seen=False,
            watcher_heartbeat_fresh=False,
            detail=(
                "watcher has not reported a heartbeat yet; captures to this "
                "vault will not be ingested until the watcher/worker are bound"
            ),
            **rebind,
        )

    watcher_vault_path = raw.get("vault_path")
    watcher_vault_path = str(watcher_vault_path) if isinstance(watcher_vault_path, str) else None

    ts_raw = raw.get("ts")
    try:
        ts_value = float(ts_raw)  # type: ignore[arg-type]
        fresh = (now_ts - ts_value) <= stale_after
    except (TypeError, ValueError):
        fresh = False

    if not fresh:
        return IngestBindingStatus(
            state="unbound",
            selected_vault_path=selected_vault_path,
            watcher_vault_path=watcher_vault_path,
            watcher_heartbeat_seen=True,
            watcher_heartbeat_fresh=False,
            detail=(
                "watcher heartbeat is stale; captures to this vault may not "
                "be ingested until the watcher/worker are confirmed running"
            ),
            **rebind,
        )

    watcher_norm = _normalized(watcher_vault_path)
    if watcher_norm != selected_norm:
        return IngestBindingStatus(
            state="diverged",
            selected_vault_path=selected_vault_path,
            watcher_vault_path=watcher_vault_path,
            watcher_heartbeat_seen=True,
            watcher_heartbeat_fresh=True,
            detail=(
                "the watcher/worker are bound to a different vault than the "
                "one currently selected; captures here will not be ingested, "
                "indexed, or made findable until the watcher/worker are "
                "rebound to this vault"
            ),
            **rebind,
        )

    return IngestBindingStatus(
        state="bound",
        selected_vault_path=selected_vault_path,
        watcher_vault_path=watcher_vault_path,
        watcher_heartbeat_seen=True,
        watcher_heartbeat_fresh=True,
        detail="watcher/worker are bound to the selected vault",
        **rebind,
    )


__all__ = [
    "IngestBindingState",
    "IngestBindingStatus",
    "ingest_binding_status",
]
