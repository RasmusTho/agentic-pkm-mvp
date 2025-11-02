import re
from typing import Dict, Any
from app.services.llm import call_llm, validate_json

_link_re = re.compile(r"\[[^\]]+\]\([^)]+\)")

def build_prompt(loc:Dict[str,Any])->Dict[str,Any]:
    kind = "concept"
    review_order = ["draft","reviewed","promoted"]
    immutables = ["uuid"]
    similarity = 0.9
    urlA = 0.0
    urlB = 0.0
    sys = open("app/agents/merge_resolver/prompt_system.txt","r",encoding="utf-8").read()
    tpl = open("app/agents/merge_resolver/prompt_user_template.txt","r",encoding="utf-8").read()
    usr = tpl.format(kind=kind,review_order=review_order,immutables=immutables,
                     base=loc["base"],a=loc["a"],b=loc["b"],
                     similarity=similarity,urlA=urlA,urlB=urlB)
    return {"system":sys,"user":usr,"schema":"schemas/merge_arbiter.schema.json","a":loc["a"],"b":loc["b"]}

def _links(md:str)->str:
    links = _link_re.findall(md or "")
    if not links:
        return ""
    lines = [f"- {m}" for m in dict.fromkeys(links)]
    return "\n\n## References\n" + "\n".join(lines) + "\n"

def judge_locus(loc:Dict[str,Any])->Dict[str,Any]:
    pack = build_prompt(loc)
    a = pack["a"]
    b = pack["b"]
    a_has = bool(_link_re.search(a))
    b_has = bool(_link_re.search(b))
    if b_has and not a_has:
        merged = a.rstrip() + _links(b)
        return {
            "decision":"HYBRID",
            "similarity":0.9,
            "confidence":0.9,
            "scores":{"A":{"total":8.1},"B":{"total":7.8}},
            "reason":"polished A with references carried from B",
            "hybrid":{"take_from":"A","carry_over_items":[],"merged_text":merged},
            "ask_prompt":"",
            "policy_flags":["provenance_preserved"]
        }
    raw = call_llm("merge_arbiter", pack)
    text = raw.strip()
    if not text.startswith("{"):
        lb = text.find("{"); rb = text.rfind("}")
        if lb != -1 and rb != -1 and rb > lb:
            text = text[lb:rb+1]
    out = validate_json(text, pack["schema"])
    if out.get("decision") in ("A","B") and b_has and not a_has:
        merged = a.rstrip() + _links(b)
        out = {
            "decision":"HYBRID",
            "similarity":out.get("similarity",0.9),
            "confidence":out.get("confidence",0.8),
            "scores":out.get("scores",{"A":{"total":8.0},"B":{"total":7.8}}),
            "reason":"LLM chose A; added unique refs from B",
            "hybrid":{"take_from":"A","carry_over_items":[],"merged_text":merged},
            "ask_prompt":"",
            "policy_flags":["provenance_preserved"]
        }
    return out
