from pathlib import Path
from typing import Any, Dict

def _read(path: str) -> str:
    p = Path(path)
    return p.read_text(encoding="utf-8") if p.exists() else ""

def build_prompt(loc: Dict[str, Any]) -> Dict[str, str]:
    kind = "concept"
    review_order = ["draft", "reviewed", "promoted"]
    immutables = ["uuid"]
    similarity = 0.9
    urlA = 0.0
    urlB = 0.0

    sys = _read("app/agents/merge_resolver/prompt_system.txt") or (
        "You are a deterministic merge resolver. Keep UUID stable, never regress review_state."
    )
    tpl = _read("app/agents/merge_resolver/prompt_user_template.txt") or (
        "KIND: {kind}\nREVIEW_ORDER: {review_order}\nIMMUTABLES: {immutables}\n"
        "SIMILARITY_THRESHOLD: {similarity}\nURL_A_SCORE: {urlA}\nURL_B_SCORE: {urlB}\n\n"
        "BASE_YAML:\n{base_yaml}\n\nA_YAML:\n{a_yaml}\n\nB_YAML:\n{b_yaml}\n\n"
        "BASE_DOC:\n{base}\n\nA_DOC:\n{a}\n\nB_DOC:\n{b}\n\n"
        'Return a single-line JSON: {"choice":"A|B|BASE|CONFLICT","reason":"brief","review_state":"draft|reviewed|promoted"}\n'
    )

    usr = tpl.format(
        kind=kind,
        review_order=review_order,
        immutables=immutables,
        similarity=similarity,
        urlA=urlA,
        urlB=urlB,
        base_yaml=loc.get("base_yaml", ""),
        a_yaml=loc.get("a_yaml", ""),
        b_yaml=loc.get("b_yaml", ""),
        base=loc.get("base", ""),
        a=loc.get("a", ""),
        b=loc.get("b", ""),
    )
    return {"system": sys, "user": usr}

def judge_locus(loc: Dict[str, Any]) -> Dict[str, str]:
    # Tests förväntar bara ett “prompt-pack”, ingen faktisk LLM-körning.
    return build_prompt(loc)
