from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import List, Tuple

# future: real entity linker / NER via LLM
# right now: naive capitalized tokens and acronyms that look important
def _guess_entities(raw: str) -> List[str]:
    candidates = set()
    # simple heuristic: grab WordsWithCaps, ALLCAPS, things-with-dash like NVR-port
    for tok in re.findall(r"\b[A-ZÅÄÖ][A-Za-z0-9ÅÄÖåäö\-]{2,}\b", raw):
        candidates.add(tok.strip())
    # also grab VLAN, NVR, OPNsense-style
    for tok in re.findall(r"\b[A-Z0-9]{2,}[-/][A-Z0-9\-]{1,}\b", raw):
        candidates.add(tok.strip())
    return sorted(candidates)

def _link_entities(text: str, ents: List[str]) -> str:
    linked = text
    # longest first to avoid partial collisions
    for e in sorted(ents, key=len, reverse=True):
        # skip if already [[...]]
        pat = r"\b" + re.escape(e) + r"\b"
        linked = re.sub(pat, f"[[{e}]]", linked)
    return linked

def _extract_tasks(raw: str) -> List[str]:
    lines = raw.splitlines()
    out = []
    for ln in lines:
        m = re.match(r"\s*-\s*\[\s*\]\s*(.+)", ln)
        if m:
            out.append(m.group(1).strip())
    return out

def _extract_decisions(raw: str) -> List[str]:
    out = []
    # Swedish "Beslut:" or English "Decision:"
    for line in raw.splitlines():
        m = re.match(r"\s*(Beslut|Decision)\s*:\s*(.+)", line, flags=re.IGNORECASE)
        if m:
            out.append(m.group(2).strip())
    return out

def _first_sentence(raw: str) -> str:
    # crude summary fallback: first non-empty line(s)
    for ln in raw.splitlines():
        stripped = ln.strip()
        if stripped:
            return stripped
    return raw.strip()

@dataclass
class CaptureBundle:
    capture_uuid: str
    summary: str
    tasks: List[str]
    decisions: List[str]
    entities: List[str]
    raw: str
    quality: str  # "ai" or "rule"

def _llm_summarize(raw: str) -> Tuple[str, List[str], List[str], List[str]]:
    # stub: soon we'll call local LLM here
    # contract: return (summary, tasks, decisions, entities)
    raise RuntimeError("LLM summarize not wired yet")

def capture_triage(raw: str, allow_llm: bool = False) -> CaptureBundle:
    cap_uuid = f"cap-{uuid.uuid4().hex[:12]}"

    # try LLM if allowed
    if allow_llm:
        try:
            summary, tasks_ai, decisions_ai, ents_ai = _llm_summarize(raw)
            linked_summary = _link_entities(summary, ents_ai)
            return CaptureBundle(
                capture_uuid=cap_uuid,
                summary=linked_summary.strip(),
                tasks=tasks_ai,
                decisions=decisions_ai,
                entities=sorted(set(ents_ai)),
                raw=raw.rstrip(),
                quality="ai",
            )
        except Exception:
            pass

    # deterministic fallback
    ents = _guess_entities(raw)
    tasks = _extract_tasks(raw)
    decisions = _extract_decisions(raw)
    summary = _first_sentence(raw)
    linked_summary = _link_entities(summary, ents)

    return CaptureBundle(
        capture_uuid=cap_uuid,
        summary=linked_summary.strip(),
        tasks=tasks,
        decisions=decisions,
        entities=ents,
        raw=raw.rstrip(),
        quality="rule",
    )
