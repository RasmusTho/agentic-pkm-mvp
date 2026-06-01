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
    "mcp.builderops.list_records": ToolDescriptor(
        name="mcp.builderops.list_records",
        kind="mcp",
        schema={
            "type": "object",
            "properties": {"object_type": {"type": "string"}},
            "required": [],
        },
        allowed_args={"object_type": "string"},
        mock_result={"status": "ok", "records": []},
    ),
    "mcp.builderops.read_record": ToolDescriptor(
        name="mcp.builderops.read_record",
        kind="mcp",
        schema={
            "type": "object",
            "properties": {"record_id": {"type": "string"}},
            "required": ["record_id"],
        },
        allowed_args={"record_id": "string"},
        mock_result={"status": "ok", "record": {}},
    ),
    "mcp.builderops.create_worklog": ToolDescriptor(
        name="mcp.builderops.create_worklog",
        kind="mcp",
        schema={
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "body": {"type": "string"},
                "task_context": {"type": "object"},
                "source_refs": {"type": "array"},
                "created_by": {"type": "object"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["summary", "body", "source_refs"],
        },
        allowed_args={
            "summary": "string",
            "body": "string",
            "task_context": "object",
            "source_refs": "array",
            "created_by": "object",
            "idempotency_key": "string",
        },
        mock_result={"status": "ok", "record": {"object_type": "AgentWorklog"}},
    ),
    "mcp.builderops.create_learning_signal": ToolDescriptor(
        name="mcp.builderops.create_learning_signal",
        kind="mcp",
        schema={
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "content": {"type": "string"},
                "signal_type": {"type": "string"},
                "source_refs": {"type": "array"},
                "created_by": {"type": "object"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["summary", "content", "signal_type", "source_refs"],
        },
        allowed_args={
            "summary": "string",
            "content": "string",
            "signal_type": "string",
            "source_refs": "array",
            "created_by": "object",
            "idempotency_key": "string",
        },
        mock_result={"status": "ok", "record": {"object_type": "LearningSignal"}},
    ),
    "mcp.builderops.create_promotion_intent": ToolDescriptor(
        name="mcp.builderops.create_promotion_intent",
        kind="mcp",
        schema={
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "target_authority_surface": {"type": "string"},
                "target_action": {"type": "string"},
                "target_ref": {"type": "string"},
                "target_authority_class": {"type": "string"},
                "intended_output": {"type": "string"},
                "source_refs": {"type": "array"},
                "created_by": {"type": "object"},
                "idempotency_key": {"type": "string"},
            },
            "required": [
                "summary",
                "target_authority_surface",
                "target_action",
                "target_ref",
                "target_authority_class",
                "intended_output",
                "source_refs",
            ],
        },
        allowed_args={
            "summary": "string",
            "target_authority_surface": "string",
            "target_action": "string",
            "target_ref": "string",
            "target_authority_class": "string",
            "intended_output": "string",
            "source_refs": "array",
            "created_by": "object",
            "idempotency_key": "string",
        },
        mock_result={"status": "ok", "record": {"object_type": "PromotionIntent"}},
    ),
    "mcp.builderops.append_receipt": ToolDescriptor(
        name="mcp.builderops.append_receipt",
        kind="mcp",
        schema={
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "event_type": {"type": "string"},
                "actor": {"type": "object"},
                "occurred_at": {"type": "string"},
                "target_refs": {"type": "array"},
                "action": {"type": "string"},
                "receipt_body": {"type": "string"},
                "idempotency_key": {"type": "string"},
                "source_refs": {"type": "array"},
                "created_by": {"type": "object"},
            },
            "required": [
                "summary",
                "event_type",
                "actor",
                "occurred_at",
                "target_refs",
                "action",
                "receipt_body",
                "idempotency_key",
                "source_refs",
            ],
        },
        allowed_args={
            "summary": "string",
            "event_type": "string",
            "actor": "object",
            "occurred_at": "string",
            "target_refs": "array",
            "action": "string",
            "receipt_body": "string",
            "idempotency_key": "string",
            "source_refs": "array",
            "created_by": "object",
        },
        mock_result={"status": "ok", "record": {"object_type": "BuilderOpsReceipt"}},
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
    "promotion.emit_intent": ToolDescriptor(
        name="promotion.emit_intent",
        kind="internal",
        schema={
            "type": "object",
            "properties": {
                "note_uuid": {"type": "string", "description": "UUID of the note to promote"},
                "action_id": {"type": "string", "description": "Canonical panel action id"},
                "action_label": {"type": "string", "description": "Label of the action"},
                "downstream_event": {"type": "string", "description": "Downstream event name"},
                "maturity": {"type": "string", "description": "Desired maturity state"},
                "instruction": {"type": "string", "description": "Panel instruction context"},
            },
            "required": ["note_uuid", "action_id"],
        },
        allowed_args={
            "note_uuid": "string",
            "action_id": "string",
            "action_label": "string",
            "downstream_event": "string",
            "maturity": "string",
            "instruction": "string",
        },
        mock_result={"status": "ok"},
    ),
}


def get_tool_descriptor(name: str) -> Optional[ToolDescriptor]:
    return MCP_TOOL_DESCRIPTORS.get(name)


__all__ = ["MCP_TOOL_DESCRIPTORS", "get_tool_descriptor"]
