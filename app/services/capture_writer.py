from __future__ import annotations
from typing import Dict, Any, List
import re
import textwrap

def _link_entities(text: str, entities: List[Dict[str, Any]]) -> str:
    """
    Byt ut entitynamn i fri text till [[Name]] så Obsidian autolänkar.
    Vi gör enkel greedy match på hela ord med versalstart.
    Vi försöker undvika att länka samma sak flera gånger i rad.
    """
    if not entities:
        return text

    # sortera längsta namn först så att "OpenTelemetry" inte först blir "Open"
    names = sorted({e["name"] for e in entities if e.get("name")}, key=len, reverse=True)

    def repl(match):
        word = match.group(0)
        for n in names:
            if word == n:
                return f"[[{n}]]"
        return word

    # ersätt bara exakta case-sensitiva träffar på ordgräns
    pattern = r"\b(" + "|".join(re.escape(n) for n in names) + r")\b"
    return re.sub(pattern, repl, text)

def _tasks_md(tasks: List[Dict[str, Any]]) -> str:
    if not tasks:
        return ""
    lines = []
    for t in tasks:
        owner = t.get("owner","?")
        text = t.get("text","").strip()
        # Obsidian-style checkbox and lightweight assignee
        lines.append(f"- [ ] {text}  @{owner}")
    return "\n".join(lines)

def _decisions_md(decisions: List[Dict[str, Any]]) -> str:
    if not decisions:
        return ""
    out = []
    for d in decisions:
        out.append(f"- {d.get('text','').strip()}")
    return "\n".join(out)

def _entities_md(entities: List[Dict[str, Any]]) -> str:
    if not entities:
        return ""
    out = []
    for e in entities:
        nm = e.get("name","?")
        ty = e.get("entity_type","unknown")
        out.append(f"- [[{nm}]] ({ty})")
    return "\n".join(out)

def bundle_to_markdown(bundle: Dict[str, Any]) -> str:
    """
    Tar triage-bundle och gör en Obsidian-vänlig anteckning:
    - YAML-frontmatter (uuid, kind:capture, review_state:inbox, etc)
    - rubriker: Summary / Tasks / Decisions / Entities / Raw capture
    - entity-länkning i summary och raw
    """
    cap_id = bundle.get("capture_id","cap-unknown")
    summary = (bundle.get("summary") or "").strip()
    tasks = bundle.get("tasks",[])
    decisions = bundle.get("decisions",[])
    entities = bundle.get("entities",[])
    raw = bundle.get("raw","").strip()

    # linkify summary + raw
    summary_linked = _link_entities(summary, entities)
    raw_linked = _link_entities(raw, entities)

    # frontmatter
    frontmatter = textwrap.dedent(f"""\
    ---
    uuid: {cap_id}
    kind: capture
    review_state: inbox
    ---
    """)

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
        body_parts.append("## Raw capture\n" + "```text\n" + raw_linked + "\n```")

    body = "\n\n".join(part.strip() for part in body_parts if part.strip())

    return (frontmatter.rstrip() + "\n\n" + body.strip() + "\n")
