from pathlib import Path
from typing import Dict, Any, List
import re
from .fs import archive_path
from app.components.reasoning import ReasoningTaskKind, get_reasoning_facade
from app.events.types import CLEANUP_DONE
from app.knowledge.write_ops import default_vault_root_for_path, write_note_from_absolute
from app.services.events import emit

_link_re = re.compile(r"\[[^\]]+\]\([^)]+\)")

def classify_and_act(
    note: Dict[str, Any],
    *,
    trace_id: str | None = None,
    reasoning_facade: Any | None = None,
) -> Dict[str, Any]:
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
        fixed = salvage_summary(
            body,
            summary_override=_summary_from_reasoning(
                body,
                object_uuid=str(uuid or ""),
                trace_id=trace_id,
                reasoning_facade=reasoning_facade,
            ),
        )
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
    root = default_vault_root_for_path(resolved)
    write_note_from_absolute(resolved, txt, vault_root=root)

def _first_sentence(text:str)->str:
    txt = " ".join(l.strip() for l in text.splitlines() if l.strip())
    for sep in [". ", "! ", "? "]:
        if sep in txt:
            return txt.split(sep)[0].strip()
    return txt[:160].strip()

def _links(md:str)->List[str]:
    return _link_re.findall(md or "")

def _summary_from_reasoning(
    body: str,
    *,
    object_uuid: str,
    trace_id: str | None = None,
    reasoning_facade: Any | None = None,
) -> str | None:
    try:
        facade = reasoning_facade or get_reasoning_facade()
        result = facade.reason(
            ReasoningTaskKind.REVIEW,
            {"text": body, "object_uuid": object_uuid, "_agent": "note_hygiene"},
            trace_id=trace_id,
        )
        if hasattr(result, "model_dump"):
            data = result.model_dump(mode="json")
            summary = data.get("summary")
            if isinstance(summary, str):
                cleaned = summary.strip()
                return cleaned or None
    except Exception:
        return None
    return None

def salvage_summary(body:str, *, summary_override: str | None = None)->str:
    lines = [l for l in body.splitlines() if l.strip()]
    heading = next((l for l in lines if l.startswith("#")), None)
    title = heading.lstrip("# ").strip() if heading else (lines[0] if lines else "Note")
    summary = summary_override or _first_sentence("\n".join(lines[1:]) if heading else "\n".join(lines))
    links = _links(body)
    pointers = "\n".join(f"- {m}" for m in dict.fromkeys(links)) if links else "- "
    return f"## Summary\n\n{summary or title}\n\n## Pointers\n{pointers}\n"
