from __future__ import annotations

SYSTEM_PROMPT = """You are a reasoning engine that extracts structured JSON from meeting notes.
Return strict JSON matching:
{
  "claims": [{"id": "...", "object_uuid": "...", "text": "...", "modality": "assertion|question|hypothesis", "confidence": 0-1}],
  "evidence": [{"id": "...", "object_uuid": "...", "source_ref": "...", "kind": "document|observation|metric", "strength": 0-1}],
  "inferences": [{"id": "...", "premises": ["claim ids"], "conclusion_id": "claim id", "type": "support|contradiction|mitigation", "rationale": "..."}]
}
Do not include commentary or markdown. Always respond with valid JSON.
"""


def build_user_prompt(text: str, relations: list[dict]) -> str:
    rel_lines = []
    for rel in relations:
        rel_lines.append(f"- {rel['type']} -> {rel['target']}")
    rel_block = "\n".join(rel_lines) if rel_lines else "none"
    return f"NOTE:\n{text}\n\nRELATIONS:\n{rel_block}\n\nRespond with JSON only."


__all__ = ["SYSTEM_PROMPT", "build_user_prompt"]
