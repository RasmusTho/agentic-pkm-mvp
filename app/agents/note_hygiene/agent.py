from pathlib import Path
from typing import Dict, Any, List
import re
from .fs import archive_path
from app.events.types import CLEANUP_DONE
from app.knowledge.locators import make_note_locator_from_absolute
from app.knowledge.service import resolve_knowledge_port
from app.services.events import emit

_link_re = re.compile(r"\[[^\]]+\]\([^)]+\)")

def classify_and_act(note:Dict[str,Any])->Dict[str,Any]:
    body = note.get("body","")
    fm = note.get("fm",{})
    uuid = fm.get("uuid")
    title = _title_from_body(body) or fm.get("title","Note")
    tokens = len(body.split())
    if tokens == 0:
        path = archive_path(title)
        _write(path, body, fm)
        emit(CLEANUP_DONE, {"uuid": uuid, "action":"archive", "path": path})
        return {"action":"archive","body":body,"path":path}
    if tokens <= 80:
        fixed = salvage_summary(body)
        emit(CLEANUP_DONE, {"uuid": uuid, "action":"fix_structure"})
        return {"action":"fix_structure","body":fixed}
    emit(CLEANUP_DONE, {"uuid": uuid, "action":"keep"})
    return {"action":"keep","body":body}

def _title_from_body(body:str)->str:
    for l in body.splitlines():
        if l.startswith("#"):
            return l.lstrip("# ").strip()
    return ""

def _write(path:str, body:str, fm:Dict[str,Any])->None:
    fm_lines = ["---"]
    for k,v in fm.items():
        fm_lines.append(f"{k}: {v}")
    fm_lines.append("---")
    txt = "\n".join(fm_lines) + "\n" + (body or "") + ("\n" if body and not body.endswith("\n") else "")
    resolved = Path(path).expanduser().resolve()
    root = Path(resolved.anchor) if resolved.anchor else Path("/")
    locator = make_note_locator_from_absolute(resolved, vault_root=root)
    port = resolve_knowledge_port(vault_root=root)
    port.write_note(locator, txt)

def _first_sentence(text:str)->str:
    txt = " ".join(l.strip() for l in text.splitlines() if l.strip())
    for sep in [". ", "! ", "? "]:
        if sep in txt:
            return txt.split(sep)[0].strip()
    return txt[:160].strip()

def _links(md:str)->List[str]:
    return _link_re.findall(md or "")

def salvage_summary(body:str)->str:
    lines = [l for l in body.splitlines() if l.strip()]
    heading = next((l for l in lines if l.startswith("#")), None)
    title = heading.lstrip("# ").strip() if heading else (lines[0] if lines else "Note")
    summary = _first_sentence("\n".join(lines[1:]) if heading else "\n".join(lines))
    links = _links(body)
    pointers = "\n".join(f"- {m}" for m in dict.fromkeys(links)) if links else "- "
    return f"## Summary\n\n{summary or title}\n\n## Pointers\n{pointers}\n"
