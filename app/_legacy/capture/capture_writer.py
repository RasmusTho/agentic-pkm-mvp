from __future__ import annotations

import re
import textwrap
from typing import Any, Dict, List


def _link_entities(text: str, entities: List[Dict[str, Any]]) -> str:
    if not entities:
        return text
    names = sorted({e["name"] for e in entities if e.get("name")}, key=len, reverse=True)

    def repl(match):
        word = match.group(0)
        for candidate in names:
            if word == candidate:
                return f"[[{candidate}]]"
        return word

    pattern = r"\b(" + "|".join(re.escape(name) for name in names) + r")\b"
    return re.sub(pattern, repl, text)


def _tasks_md(tasks: List[Dict[str, Any]]) -> str:
    if not tasks:
        return ""
    lines = []
    for task in tasks:
        owner = task.get("owner", "?")
        text = task.get("text", "").strip()
        lines.append(f"- [ ] {text}  @{owner}")
    return "\n".join(lines)


def _decisions_md(decisions: List[Dict[str, Any]]) -> str:
    if not decisions:
        return ""
    return "\n".join(f"- {d.get('text', '').strip()}" for d in decisions)


def _entities_md(entities: List[Dict[str, Any]]) -> str:
    if not entities:
        return ""
    return "\n".join(f"- [[{e.get('name', '?')}]] ({e.get('entity_type', 'unknown')})" for e in entities)


def bundle_to_markdown(bundle: Dict[str, Any]) -> str:
    capture_id = bundle.get("capture_id", "cap-unknown")
    summary = (bundle.get("summary") or "").strip()
    tasks = bundle.get("tasks", [])
    decisions = bundle.get("decisions", [])
    entities = bundle.get("entities", [])
    raw = bundle.get("raw", "").strip()

    summary_linked = _link_entities(summary, entities)
    raw_linked = _link_entities(raw, entities)

    frontmatter = textwrap.dedent(
        f"""\
        ---
        uuid: {capture_id}
        kind: capture
        review_state: inbox
        ---
        """
    )

    body_parts: List[str] = []
    if summary_linked:
        body_parts.append("## Summary\n" + summary_linked)
    tasks_block = _tasks_md(tasks)
    if tasks_block:
        body_parts.append("## Tasks\n" + tasks_block)
    decisions_block = _decisions_md(decisions)
    if decisions_block:
        body_parts.append("## Decisions\n" + decisions_block)
    entities_block = _entities_md(entities)
    if entities_block:
        body_parts.append("## Entities\n" + entities_block)
    if raw_linked:
        body_parts.append("## Raw capture\n```text\n" + raw_linked + "\n```")

    body = "\n\n".join(part.strip() for part in body_parts if part.strip())
    return (frontmatter.rstrip() + "\n\n" + body.strip() + "\n")
