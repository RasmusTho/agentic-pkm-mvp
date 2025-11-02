from __future__ import annotations

from typing import Any, Dict

from app.agents.chunker.agent import run as chunker_run

def invoke(object_id: str,
           *,
           trace_id: str,
           max_tokens: int,
           overlap: int,
           strategy: str = "heading_first") -> dict[str, Any]:
    """
    Thin wrapper that mirrors the shape expected by the test:
    returns {"output": <agent run dict>}
    """
    res = chunker_run(
        object_id,
        trace_id=trace_id,
        max_tokens=max_tokens,
        overlap=overlap,
        strategy=strategy,
    )
    return {"output": res}
