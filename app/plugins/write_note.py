from __future__ import annotations

import asyncio
from datetime import timezone, datetime

from .base import Tool, ToolContext, ToolResult


class WriteNoteTool:
    name = "write_note"

    async def arun(
        self,
        ctx: ToolContext,
        *,
        text: str,
        tags: list[str] | None = None,
        layer: str = "long_term",
    ) -> ToolResult:
        payload = {
            "text": text,
            "tags": tags or [],
            "created_at": datetime.now(tz=timezone.utc).isoformat(),
        }
        provenance = {"tool": self.name}
        memory_id = await asyncio.to_thread(
            ctx.repository.add_memory,
            ctx.run_id,
            layer,
            payload,
            provenance,
        )
        payload["memory_id"] = str(memory_id)
        return ToolResult(name=self.name, output=payload)


tool: Tool = WriteNoteTool()
