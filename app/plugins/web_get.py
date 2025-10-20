from __future__ import annotations

import httpx

from .base import Tool, ToolContext, ToolResult


class WebGetTool:
    name = "web_get"

    async def arun(self, ctx: ToolContext, *, url: str, timeout: float = 10.0) -> ToolResult:
        async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
            response = await client.get(url)
            response.raise_for_status()
        payload = {
            "url": url,
            "status_code": response.status_code,
            "content": response.text[:2000],
        }
        return ToolResult(name=self.name, output=payload)


tool: Tool = WebGetTool()
