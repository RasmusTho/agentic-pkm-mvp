from __future__ import annotations

import asyncio

from app.components.embeddings import get_embedding_client
from app.search.service import search_hybrid

from .base import Tool, ToolContext, ToolResult


class RetrieverTool:
    name = "retriever"

    async def arun(self, ctx: ToolContext, *, query: str, k: int = 5) -> ToolResult:
        client = get_embedding_client("deterministic")
        embedding = await asyncio.to_thread(client.embed_text, query)
        hits = await asyncio.to_thread(search_hybrid, query, embedding, k=k)
        payload = [
            {
                "object_id": str(hit.object_id),
                "score": hit.score,
                "payload": hit.payload,
            }
            for hit in hits
        ]
        return ToolResult(name=self.name, output=payload)


tool: Tool = RetrieverTool()
