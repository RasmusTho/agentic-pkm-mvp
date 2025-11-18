from __future__ import annotations

from typing import Any, Dict, Sequence

PLANNER_SYSTEM_PROMPT = """You are the Planner Agent for a research assistant.
Return a JSON object that matches this schema:
{
  "id": "plan-uuid",
  "meta": {
    "goal": "...",
    "source_object_uuid": "...",
    "created_by": "planner.llm",
    "trace_id": "optional"
  },
  "steps": [
    {
      "id": "step-1",
      "kind": "agent_call|tool_call|decision|note",
      "description": "...",
      "agent": "optional agent name",
      "intent": "optional agent intent",
      "tool": "optional tool name like mcp.vault.append_note",
      "tool_args": {},
      "depends_on": [],
      "metadata": {}
    }
  ]
}
All fields must be present even if empty.  Keep plans short (<=4 steps) and grounded in the supplied goal and context.
"""


def build_planner_user_prompt(
    *,
    goal: str,
    object_text: str,
    relations: Sequence[Dict[str, Any]] | None = None,
    metadata: Dict[str, Any] | None = None,
    planning_guidance: Dict[str, Any] | None = None,
) -> str:
    rel_section = "\n".join(
        f"- {rel.get('type')}: {rel.get('source')} -> {rel.get('target')}" for rel in (relations or [])
    )
    meta_lines = "\n".join(f"- {k}: {v}" for k, v in (metadata or {}).items())
    prompt = (
        f"Goal:\n{goal}\n\n"
        f"Object text:\n{object_text.strip() or '(empty)'}\n\n"
        f"Relations:\n{rel_section or '(none)'}\n\n"
        f"Metadata:\n{meta_lines or '(none)'}\n\n"
        "Respond with JSON that matches the schema."
    )
    if planning_guidance:
        import json as _json

        prompt += "\n\nFlow guidance:\n" + _json.dumps(planning_guidance, sort_keys=True)
    return prompt


__all__ = ["PLANNER_SYSTEM_PROMPT", "build_planner_user_prompt"]
