from fastapi import FastAPI, Query
from pathlib import Path
import json, uuid

app = FastAPI(title="WS API")


def _load_golden():
    base = Path("/app/golden")
    notes = []
    for p in base.glob("*.md"):
        # naive: read frontmatter block and body
        txt = p.read_text(encoding="utf-8")
        if txt.startswith("---"):
            fm_end = txt.find("\n---", 3)
            fm = txt[3:fm_end].strip()
            body = txt[fm_end+4:].strip()
            notes.append({"path": str(p), "frontmatter": fm, "body": body})
    return notes


@app.get("/query")
def query(q: str = Query(...)):
    # WS fake retrieval: just return first golden note with provenance
    notes = _load_golden()
    if not notes:
        return {"answer": "", "citations": [], "confidence": 0.0}
    n = notes[0]
    trace_id = str(uuid.uuid4())
    return {
        "answer": f"WS answer for '{q}': {n['body'][:140]}",
        "citations": [{"id":"00000000-0000-4000-8000-000000000001","href": n["path"],"span":"0-140"}],
        "confidence": 0.8,
        "provenance": {"trace_id": trace_id, "chunks": [{"id":"00000000-0000-4000-8000-000000000001","offset":[0,140]}]},
        "policy": {"trust_mix":{"evergreen":0.6,"curated":0.3,"external":0.1}}
    }
