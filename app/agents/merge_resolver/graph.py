from typing import Tuple, List, Dict

def _split(text: str) -> Tuple[str, str]:
    if text.startswith("---"):
        try:
            _, fm, rest = text.split("---", 2)
            return fm.strip(), rest.lstrip("\n")
        except ValueError:
            pass
    return "", text

def _join(fm: str, body: str) -> str:
    fm_block = f"---\n{fm}\n---\n" if fm else ""
    return f"{fm_block}{body}"

def diff_conflict_loci(base: str, a: str, b: str) -> List[Dict[str, str]]:
    """
    Minimal, deterministisk lokusupptäckt:
    - 'yaml' om frontmatter skiljer sig
    - 'body' om brödtext skiljer sig
    """
    fmA, bodyA = _split(a)
    fmB, bodyB = _split(b)
    loci: List[Dict[str, str]] = []
    if fmA.strip() != fmB.strip():
        loci.append({"kind": "yaml"})
    if bodyA.strip() != bodyB.strip():
        loci.append({"kind": "body"})
    return loci

def apply_decisions(base: str, a: str, b: str, loci, decisions) -> str:
    """
    Kombinera YAML- och BODY-beslut och assemblar en enda not i slutet.
    """
    fmA, bodyA = _split(a)
    fmB, bodyB = _split(b)

    chosen_fm = fmA
    chosen_body = bodyA

    for loc, dec in zip(loci, decisions):
        kind = loc.get("kind")
        d = dec.get("decision")

        if kind == "yaml":
            if d == "B":
                chosen_fm = fmB

        elif kind == "body":
            if d == "B":
                chosen_body = bodyB
            elif d == "HYBRID" and dec.get("hybrid", {}).get("merged_text"):
                chosen_body = dec["hybrid"]["merged_text"]
            else:
                chosen_body = bodyA

    return _join(chosen_fm, chosen_body)
