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
                "note_id": {"type": "string", "description": "Vault note identifier"},
                "content": {"type": "string", "description": "Markdown content to append"},
            },
            "required": ["note_id", "content"],
        },
        allowed_args={"note_id": "string", "content": "string"},
        mock_result={"status": "ok", "appended_characters": 0},
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
}


def get_tool_descriptor(name: str) -> Optional[ToolDescriptor]:
    return MCP_TOOL_DESCRIPTORS.get(name)


__all__ = ["MCP_TOOL_DESCRIPTORS", "get_tool_descriptor"]
