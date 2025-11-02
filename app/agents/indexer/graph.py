from __future__ import annotations

from typing import Any
from app.agents.indexer.agent import run as index_run

def invoke(object_id: str, *, trace_id: str) -> dict[str, Any]:
    """
    Matchar kontraktet för övriga invoke()-helpers i testen.
    Dvs vi returnerar {"output": {...}}.
    """
    result = index_run(object_id, trace_id=trace_id)
    return {"output": result}
