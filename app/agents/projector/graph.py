from __future__ import annotations

from typing import Any

from app.agents.projector.agent import run as projector_run


def invoke(object_id: str, *, trace_id: str, set_name: str) -> dict[str, Any]:
    """
    Minimal wrapper to match test expectations:
    returns {"output": {...}} där {...} innehåller event, promote, etc.
    """
    out = projector_run(object_id, trace_id=trace_id, set_name=set_name)
    return {"output": out}
