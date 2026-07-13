"""Cross-process settings reload signal for the compose runtime topology.

The API, worker, and registry watcher are distinct processes.  Their in-process
event bus remains useful locally, but cannot carry a settings edit between
containers.  This module uses the already-shared runtime-artifact volume as a
small, derived invalidation signal; vault markdown remains the sole authority.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from time import time_ns
from typing import Any


_SIGNAL_ENV = "SETTINGS_RELOAD_SIGNAL_PATH"
_DEFAULT_SIGNAL_PATH = Path("/app/tmp/settings-reload.json")


@dataclass(frozen=True)
class ReloadSignal:
    generation: str
    state: str
    source: str
    loaded_at: str | None
    error: str | None


def signal_path() -> Path:
    raw = os.getenv(_SIGNAL_ENV, "").strip()
    return Path(raw).expanduser() if raw else _DEFAULT_SIGNAL_PATH


def publish_reload_signal(
    *, state: str, source: str, loaded_at: str | None, error: str | None
) -> ReloadSignal:
    """Atomically publish the result of a watcher settings-source reload."""
    signal = ReloadSignal(
        generation=str(time_ns()),
        state=state,
        source=source,
        loaded_at=loaded_at,
        error=error,
    )
    target = signal_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(signal.__dict__, sort_keys=True), encoding="utf-8")
    temporary.replace(target)
    return signal


def read_reload_signal() -> ReloadSignal | None:
    """Return the newest valid signal, treating a missing/corrupt one as absent."""
    try:
        payload: Any = json.loads(signal_path().read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return None
        generation = payload.get("generation")
        state = payload.get("state")
        source = payload.get("source")
        if not all(isinstance(value, str) and value for value in (generation, state, source)):
            return None
        loaded_at = payload.get("loaded_at")
        error = payload.get("error")
        return ReloadSignal(
            generation=generation,
            state=state,
            source=source,
            loaded_at=loaded_at if isinstance(loaded_at, str) else None,
            error=error if isinstance(error, str) else None,
        )
    except (OSError, ValueError, TypeError):
        return None


__all__ = ["ReloadSignal", "publish_reload_signal", "read_reload_signal", "signal_path"]
