from __future__ import annotations

from collections.abc import Sequence

from app.plugins.base import ToolResult

from .actions import PlannedAction


def summarize_plan(actions: Sequence[PlannedAction]) -> str:
    return "\n".join(action.description or action.tool for action in actions)


def summarize_results(results: Sequence[ToolResult]) -> str:
    lines: list[str] = []
    for result in results:
        if result.metadata and "error" in result.metadata:
            lines.append(f"{result.name}: error={result.metadata['error']}")
        else:
            lines.append(f"{result.name}: success")
    return "\n".join(lines)
