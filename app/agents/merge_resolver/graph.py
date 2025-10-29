from typing import List, Dict, Any, Tuple
import re

_fm_re = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)

def _split(md:str)->Tuple[str,str]:
    m = _fm_re.match(md or "")
    if not m:
        return "", md or ""
    return m.group(1), md[m.end():]

def diff_conflict_loci(base:str, a:str, b:str)->List[Dict[str,Any]]:
    loci: List[Dict[str,Any]] = []
    fmB, bodyB = _split(base)
    fmA, bodyA = _split(a)
    fmR, bodyR = _split(b)
    if fmA != fmR:
        loci.append({"kind":"yaml","base":fmB,"a":fmA,"b":fmR,"path":"$.frontmatter"})
    if bodyA != bodyR:
        loci.append({"kind":"body","base":bodyB,"a":bodyA,"b":bodyR,"path":"$.body"})
    if not loci:
        loci.append({"kind":"noop","base":base,"a":a,"b":b,"path":"$"})
    return loci

def apply_decisions(base:str, a:str, b:str, loci, decisions)->str:
    # Reassemble by replacing per-locus; current loci are coarse (yaml/body),
    # so return the chosen or hybrid text directly when body-locus driver decided.
    for loc, dec in zip(loci, decisions):
        if loc["kind"] == "body":
            d = dec.get("decision")
            if d == "B":
                return b
            if d == "HYBRID" and dec.get("hybrid",{}).get("merged_text"):
                fm, _ = _split(a)
                return f"---\n{fm}\n---\n{dec['hybrid']['merged_text']}"
            return a
        if loc["kind"] == "yaml":
            # Prefer A unless decision explicitly said B for yaml
            if dec.get("decision") == "B":
                _, bodyA = _split(a)
                fmB, _ = _split(b)
                return f"---\n{fmB}\n---\n{bodyA}"
    return a
