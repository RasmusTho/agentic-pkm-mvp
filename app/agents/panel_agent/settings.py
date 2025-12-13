from __future__ import annotations

import os
from typing import Literal

DeciderMode = Literal["rule", "llm"]
PipelineMode = Literal["direct", "planner"]


def get_panel_agent_decider() -> DeciderMode:
    value = (os.getenv("PANEL_AGENT_DECIDER") or "rule").strip().lower()
    if value not in {"rule", "llm"}:
        return "rule"
    return value  # type: ignore[return-value]


def get_panel_agent_pipeline() -> PipelineMode:
    value = (os.getenv("PANEL_AGENT_PIPELINE") or "direct").strip().lower()
    if value not in {"direct", "planner"}:
        return "direct"
    return value  # type: ignore[return-value]


__all__ = ["get_panel_agent_decider", "get_panel_agent_pipeline", "DeciderMode", "PipelineMode"]
