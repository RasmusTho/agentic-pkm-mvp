from __future__ import annotations

from typing import Dict, Optional

from .schema import ToolDescriptor

MCP_TOOL_DESCRIPTORS: Dict[str, ToolDescriptor] = {
    "mcp.vault.append_note": ToolDescriptor(
        name="mcp.vault.append_note",
        kind="mcp",
        schema={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Note title"},
                "body": {"type": "string", "description": "Markdown body"},
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional tags",
                },
                "metadata": {"type": "object", "description": "Optional metadata"},
            },
            "required": ["title", "body"],
        },
        allowed_args={"title": "string", "body": "string", "content": "string", "tags": "array", "metadata": "object"},
        mock_result={"status": "ok", "note_path": "vault/_mcp/mock-note.md"},
    ),
    "mcp.search.objects": ToolDescriptor(
        name="mcp.search.objects",
        kind="mcp",
        schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "k": {"type": "integer", "minimum": 1, "maximum": 20},
            },
            "required": ["query"],
        },
        allowed_args={"query": "string", "k": "integer"},
        mock_result={"status": "ok", "results": []},
    ),
    "internal.ingest_external": ToolDescriptor(
        name="internal.ingest_external",
        kind="internal",
        schema={
            "type": "object",
            "properties": {
                "root_dir": {"type": "string", "description": "Path to external drop folder"},
                "limit": {"type": "integer", "description": "Optional max files to ingest"},
            },
            "required": ["root_dir"],
        },
        allowed_args={"root_dir": "string", "limit": "integer"},
        mock_result={"status": "ok", "ingested": 0},
    ),
}


def get_tool_descriptor(name: str) -> Optional[ToolDescriptor]:
    return MCP_TOOL_DESCRIPTORS.get(name)


__all__ = ["MCP_TOOL_DESCRIPTORS", "get_tool_descriptor"]
