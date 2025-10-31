from __future__ import annotations
from datetime import datetime, timezone
from typing import Dict, Any, List

def _obs_links(text: str, entities: List[dict]) -> str:
    # naive pass 1: ersätt rena namn med [[namn]]
    # (senare kan vi bli smartare och bara länka första förekomsten etc)
    if not text:
        return ""
    out = text
    for ent in entities:
        name = ent.get("name")
        if not name:
            continue
        out = out.replace(name, f"[[{name}]]")
    return out

def generate_notes(bundle: Dict[str, Any]) -> Dict[str, Any]:
    """
    Tar en CaptureTriageBundle (enligt capture_triage.schema.json)
    och bygger markdown-strängar + frontmatter som ska sparas i vaulten.

    Returnerar en dict med minst:
    {
      "capture": {
        "slug": <capture_id>,
        "frontmatter": {...},
        "body": "...markdown..."
      }
    }

    Just nu genererar vi bara en 'capture'-note.
    Senare kan vi också generera todo-/decision-/entity-noter separat.
    """

    # tidsstämpel mest för framtida spårbarhet
    now = datetime.now(timezone.utc).isoformat()

    # --- bygg huvudtexten ---
    body_lines: List[str] = []

    body_lines.append("# Capture Summary")
    body_lines.append(_obs_links(bundle.get("summary", ""), bundle.get("entities", [])))
    body_lines.append("")

    # Tasks
    tasks = bundle.get("tasks", [])
    if tasks:
        body_lines.append("## Tasks")
        for t in tasks:
            t_txt = _obs_links(t.get("text", ""), t.get("entities", []))
            owner = t.get("owner", "")
            deadline = t.get("deadline", "")
            meta_bits = []
            if owner:
                meta_bits.append(f"owner: {owner}")
            if deadline:
                meta_bits.append(f"due: {deadline}")
            meta = (" (" + ", ".join(meta_bits) + ")") if meta_bits else ""
            body_lines.append(f"- [ ] {t_txt}{meta}")
        body_lines.append("")

    # Decisions
    decisions = bundle.get("decisions", [])
    if decisions:
        body_lines.append("## Decisions")
        for d in decisions:
            d_txt = _obs_links(d.get("text", ""), d.get("entities", []))
            body_lines.append(f"- {d_txt}")
        body_lines.append("")

    # Entities block (explicit surfacing for context)
    ents = bundle.get("entities", [])
    if ents:
        body_lines.append("## Entities")
        for e in ents:
            name = e.get("name", "")
            etype = e.get("entity_type", "")
            note = e.get("notes", "")
            body_lines.append(f"- [[{name}]] ({etype}) {note}".rstrip())
        body_lines.append("")

    # Raw dump at the end
    body_lines.append("---")
    body_lines.append("## Raw")
    body_lines.append(bundle.get("raw", "").rstrip())
    body_lines.append("")
    body_lines.append(f"_captured_at: {now}_")
    body_lines.append("")

    body = "\n".join(body_lines)

    # --- bygg frontmatter ---
    fm = {
        "uuid": bundle["capture_id"],
        "kind": "capture",
        "review_state": "inbox",
        "areas": bundle.get("areas", []),
        "signal_quality": bundle.get("signal_quality", "unknown")
    }

    return {
        "capture": {
            "slug": bundle["capture_id"],
            "frontmatter": fm,
            "body": body
        }
    }
