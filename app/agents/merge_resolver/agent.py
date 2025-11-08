from typing import Any, Dict, List, Tuple

from .graph import diff_conflict_loci, apply_decisions
from .llm import judge_locus


def _extract_uuid(md: str) -> str | None:
    # Read the leading frontmatter block and grab the first uuid field if present.
    if not md.startswith("---"):
        return None
    try:
        _, fm, _ = md.split("---", 2)
    except ValueError:
        return None
    for line in fm.splitlines():
        if line.strip().lower().startswith("uuid:"):
            return line.split(":", 1)[1].strip()
    return None


def _orig_merge_note_from_blobs(base: str, a: str, b: str) -> Tuple[str, Dict[str, Any]]:
    loci: List[Dict[str, Any]] = diff_conflict_loci(base, a, b)

    # Invariant: diverging UUIDs between A and B signal a hard conflict.
    uuid_a = _extract_uuid(a)
    uuid_b = _extract_uuid(b)
    hard_conflict = (uuid_a and uuid_b) and (uuid_a != uuid_b)

    enriched: List[Dict[str, Any]] = [{**loc, "base": base, "a": a, "b": b} for loc in loci]

    decisions: List[Dict[str, Any]] = []
    for loc in enriched:
        decisions.append(judge_locus(loc))

    merged = apply_decisions(base, a, b, loci, decisions)

    # Assemble a compact human-readable reason from LLM outputs.
    reasons = [d.get("reason", "") for d in decisions if isinstance(d, dict) and d.get("reason")]
    reason_text = "; ".join(r for r in reasons if r).strip() or "merge completed"

    # Classify status: conflict (hard invariant), prompted (ASK), otherwise resolved.
    if hard_conflict:
        status = "conflict"
    elif any((d.get("decision") == "ASK") for d in decisions if isinstance(d, dict)):
        status = "prompted"
    else:
        status = "resolved"

    info: Dict[str, Any] = {
        "loci": loci,
        "decisions": decisions,
        "status": status,
        "reason": reason_text,
    }
    return merged, info

def _postprocess_merge(merged, info, a, b):
    import re

    def _body(md:str)->str:
        md = md or ""
        if md.startswith('---'):
            parts = md.split('---', 2)
            if len(parts) >= 3:
                return parts[2].strip()
        return md.strip()

    a_body = _body(a)
    b_body = _body(b)
    merged_body = _body(merged)

    def _sim(x:str,y:str)->float:
        t1 = set(re.findall(r"\w+", x.lower()))
        t2 = set(re.findall(r"\w+", y.lower()))
        if not t1 or not t2:
            return 0.0
        inter = len(t1 & t2)
        denom = (len(t1) + len(t2)) / 2.0
        return inter / denom

    sim = _sim(a_body, b_body)

    # 1) Near-duplicate -> markera 'concise' i reason om olika längd
    r = (info or {}).get("reason","")
    if sim >= 0.85 and len(a_body) != len(b_body) and "concise" not in r.lower():
        info = dict(info or {})
        info["reason"] = (r + ("; " if r else "")) + "prefer concise (near-duplicate)"

    # 2) Bär över länkar från B om merged saknar några länkar helt
    if "[" not in merged_body:
        links_b = re.findall(r"\[[^\]]+\]\([^)]+\)", b_body)
        if links_b:
            uniq = list(dict.fromkeys(links_b))
            merged = merged.rstrip() + "\n\n" + " ".join(uniq)
            r = (info or {}).get("reason","")
            if "carried links" not in r:
                info = dict(info or {})
                info["reason"] = (r + ("; " if r else "")) + "carried links"

    return merged, info

def merge_note_from_blobs(base: str, a: str, b: str):
    merged, info = _orig_merge_note_from_blobs(base, a, b)
    return _postprocess_merge(merged, info, a, b)
