from __future__ import annotations

import asyncio
from typing import Mapping, Sequence
from uuid import UUID

from app.plugins.base import Tool, ToolContext, ToolResult

from .actions import PlannedAction
from .repository import AgentRepository


async def execute_plan(
    actions: Sequence[PlannedAction],
    ctx: ToolContext,
    tools: Mapping[str, Tool],
    repository: AgentRepository,
) -> list[ToolResult]:
    results: list[ToolResult] = []
    for action in actions:
        tool = tools.get(action.tool)
        if tool is None:
            await asyncio.to_thread(
                repository.log_event,
                ctx.run_id,
                "tool_missing",
                {"tool": action.tool},
                None,
            )
            continue
        task_id: UUID = await asyncio.to_thread(
            repository.register_task,
            ctx.run_id,
            action.tool,
            action.args,
        )
        try:
            result = await tool.arun(ctx, **action.args)
            results.append(result)
            await asyncio.to_thread(
                repository.complete_task,
                task_id,
                "completed",
                getattr(result, "output", None),
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            await asyncio.to_thread(
                repository.complete_task,
                task_id,
                "failed",
                {"error": str(exc)},
            )
            await asyncio.to_thread(
                repository.log_event,
                ctx.run_id,
                "tool_error",
                {"tool": action.tool, "error": str(exc)},
                task_id,
            )
    return results
