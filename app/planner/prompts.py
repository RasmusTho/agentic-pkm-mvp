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
      "step_class": "plain|llm_transform|validation|authority_check|governed_effect|receipt",
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
All fields must be present even if empty. Keep plans short (<=5 steps) and grounded in the supplied goal and context. One append chain plus one LLM transform and its validation fits this bound.
step_class is REQUIRED on every step. Use "llm_transform" for a step whose output is LLM-generated content,
and add a "validation" step depending on it before any other step consumes it. Use "governed_effect" for a
step that mutates durable state; it must depend (directly or transitively) on an "authority_check" step and
be followed by a "receipt" step that depends on it. Use "plain" for everything else.

For every tool_call whose tool is exactly "mcp.vault.append_note", emit the complete structural R2 chain:
1. An upstream decision step with step_class "authority_check", tool exactly "mcp.vault.append_note",
   and tool_args identical to the append step's tool_args. Set its metadata.append_effect_step_id to
   the append step id. Copy every prerequisite of the append step onto this authority step.
2. The append step has step_class "governed_effect", metadata.authority_check_step_id set to the
   authority step id, and depends_on including that authority step id.
3. A downstream note step has step_class "receipt", metadata.receipt_from_step set to the append
   step id, depends_on including the append step id, and verify "result:execution_result".
The authority and append steps MUST resolve to the same effective actor: explicit agent_id, then
step metadata.agent_id, then plan context agent_id, then flow default. Prefer the same explicit
agent_id on both. If relying on fallback resolution, do not specify different step metadata agent_id
values. These metadata fields are structural references only: runtime policy and WriteGuard perform
the authority check, and the executor produces the receipt result. Never treat plan metadata as
permission or invent a receipt reference.
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
