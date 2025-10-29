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


def merge_note_from_blobs(base: str, a: str, b: str) -> Tuple[str, Dict[str, Any]]:
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
