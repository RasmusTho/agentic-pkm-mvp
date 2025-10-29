from dataclasses import dataclass
from typing import Tuple, Dict, Any, List
from .graph import diff_conflict_loci, apply_decisions
from .llm import judge_locus
from app.services.policy import invariants_ok, compute_hashes, version_vector
from app.services.events import emit, new_trace_id

@dataclass
class MergeResult:
    merged: str
    meta: Dict[str, Any]

def merge_note_from_blobs(base:str, a:str, b:str)->Tuple[str,dict]:
    loci = diff_conflict_loci(base, a, b)
    decisions: List[Dict[str,Any]] = []
    auto_prompts = 0
    for loc in loci:
        out = judge_locus(loc)
        if out.get("decision") in ("ASK","ABSTAIN"):
            auto_prompts += 1
        decisions.append(out)
    merged = apply_decisions(base, a, b, loci, decisions)
    if not invariants_ok(merged):
        emit("merge.conflict", {"reason":"invariant breach"})
        return base, {"status":"conflict","reason":"invariant breach"}
    h = compute_hashes(merged)
    vv = version_vector(a, b)
    reason = ";".join(d.get("reason","") for d in decisions if d.get("reason"))
    evt = "merge.prompt" if auto_prompts else "merge.resolved"
    emit(evt, {"parents": vv, "hash": h, "reason": reason, "loci": len(loci), "auto_prompts": auto_prompts}, new_trace_id())
    return merged, {"status":"prompted" if auto_prompts else "resolved","reason":reason,"hash":h,"parents":vv}
