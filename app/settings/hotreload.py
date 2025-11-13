from __future__ import annotations

from typing import Any, Callable, Dict

from app.events.bus import subscribe


def init_hot_reload(callback: Callable[[Dict[str, Any]], None]) -> None:
    """Register a callback that runs whenever compiled settings change."""
    subscribe("settings.changed", callback)
