from __future__ import annotations

import os
from typing import Literal

DeciderMode = Literal["rule", "llm"]


def get_panel_agent_decider() -> DeciderMode:
    value = (os.getenv("PANEL_AGENT_DECIDER") or "rule").strip().lower()
    if value not in {"rule", "llm"}:
        return "rule"
    return value  # type: ignore[return-value]


__all__ = ["get_panel_agent_decider", "DeciderMode"]
