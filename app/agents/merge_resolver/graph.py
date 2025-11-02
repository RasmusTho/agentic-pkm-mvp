from typing import Any, Dict, List, Tuple

def _split(md: str) -> Tuple[str, str]:
    """
    Return (frontmatter_text_without_dashes, body_text).
    If multiple frontmatter blocks are stacked accidentally
    (--- fm ---\n--- fm ---\nbody...), strip all but the first.
    """
    if not md.startswith("---"):
        return "", md.lstrip()

    parts = md.split("---")
    if len(parts) < 3:
        return "", md.lstrip()

    fm = parts[1].strip()
    body = parts[2].lstrip("\n")

    # guard against accidental second fm block
    if body.startswith("---"):
        subparts = body.split("---")
        if len(subparts) >= 3:
            body = subparts[2].lstrip("\n")

    return fm, body


def _join(fm: str, body: str) -> str:
    """
    Reassemble markdown as:
    ---\n<fm>\n---\n<body>
    (no forced blank line after fm; body is placed immediately,
     matching fixture format in tests.)
    """
    fm = fm.strip()
    # body in fixtures starts with '# ...' on its own line right after ---
    # so we ensure exactly one newline between the fm block and the body text
    body = body.lstrip("\n")
    if fm:
        return f"---\n{fm}\n---\n{body}"
    else:
        return body


def diff_conflict_loci(base: str, a: str, b: str) -> List[Dict[str, Any]]:
    """
    Minimal locus detector:
    - always returns two loci: one for yaml, one for body.
    Later we can refine to paragraph-level.
    """
    fm_base, body_base = _split(base)
    fm_a, body_a = _split(a)
    fm_b, body_b = _split(b)

    loci: List[Dict[str, Any]] = []

    loci.append({
        "kind": "yaml",
        "base_yaml": fm_base,
        "yaml_a": fm_a,
        "yaml_b": fm_b,
    })

    loci.append({
        "kind": "body",
        "base_body": body_base,
        "body_a": body_a,
        "body_b": body_b,
    })

    return loci


def apply_decisions(base: str,
                    a: str,
                    b: str,
                    loci: List[Dict[str, Any]],
                    decisions: List[Dict[str, Any]]) -> str:
    """
    Combine YAML/body decisions from LLM (or heuristics) into one merged note.
    We NEVER emit duplicate frontmatter blocks.
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
                _, sanitized_body = _split(dec["hybrid"]["merged_text"])
                chosen_body = sanitized_body
            else:
                chosen_body = bodyA

    return _join(chosen_fm, chosen_body)
