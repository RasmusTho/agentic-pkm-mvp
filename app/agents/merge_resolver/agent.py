import re
from typing import Any, Dict, List, Tuple

from .graph import diff_conflict_loci, apply_decisions
from .llm import judge_locus


# Optional leading "!" so image embeds are recognized too: the carryover
# heuristic only appends plain links, so an incoming image can never be
# "carried" verbatim and the lossless check below fails closed to a conflict.
_MD_LINK_RE = re.compile(r"!?\[[^\]]+\]\([^)]+\)")


def _token_similarity(x: str, y: str) -> float:
    t1 = set(re.findall(r"\w+", x.lower()))
    t2 = set(re.findall(r"\w+", y.lower()))
    if not t1 or not t2:
        return 0.0
    inter = len(t1 & t2)
    denom = (len(t1) + len(t2)) / 2.0
    return inter / denom


def _normalized_nonlink_text(body: str) -> str:
    """Whitespace-normalized body text with markdown links removed."""
    return " ".join(_MD_LINK_RE.sub(" ", body).split())


def _carried_links_are_lossless(merged_body: str, b_body: str) -> bool:
    """True only when THEIRS' (b) entire body survives in the merged body.

    The link-carryover heuristic appends THEIRS' markdown links to the merged
    text. That reconciles the divergence only when links are the entire
    difference THEIRS brings: every one of THEIRS' links must be present
    verbatim in the merged body, and THEIRS' remaining non-link prose must
    already appear (whitespace-normalized, contiguous, in order) inside the
    merged body's non-link prose. Anything less means distinct incoming prose
    is being dropped while the merge still reports "resolved" -- the P1
    content-loss finding from PR #4604 review r3700682703 (#4616).
    """
    if not all(link in merged_body for link in _MD_LINK_RE.findall(b_body)):
        return False
    # Space-padded containment keeps the match word-aligned: THEIRS' "enabled"
    # must not count as preserved because OURS happens to contain "unenabled".
    b_nonlink = _normalized_nonlink_text(b_body)
    merged_nonlink = _normalized_nonlink_text(merged_body)
    return f" {b_nonlink} " in f" {merged_nonlink} "


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

    sim = _token_similarity(a_body, b_body)

    # 1) Near-duplicate -> markera 'concise' i reason om olika längd
    r = (info or {}).get("reason","")
    if sim >= 0.85 and len(a_body) != len(b_body) and "concise" not in r.lower():
        info = dict(info or {})
        info["reason"] = (r + ("; " if r else "")) + "prefer concise (near-duplicate)"


    # 1b) Om merged == A (eller B) och den valda varianten är kortare -> uttryckligen motivera
    # 'prefer concise'. Gated on the same genuine near-duplicate threshold as (1): without it,
    # this fires purely because the (always-default-to-A) chosen side happens to be shorter,
    # mislabeling arbitrary content loss as an intentional "prefer concise" pick.
    r = (info or {}).get("reason","")
    if sim >= 0.85 and "concise" not in r.lower():
        if merged_body == a_body and len(a_body) < len(b_body):
            info = dict(info or {})
            info["reason"] = (r + ("; " if r else "")) + "prefer concise"
        elif merged_body == b_body and len(b_body) < len(a_body):
            info = dict(info or {})
            info["reason"] = (r + ("; " if r else "")) + "prefer concise"

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

def _body(md: str) -> str:
    md = md or ""
    if md.startswith("---"):
        parts = md.split("---", 2)
        if len(parts) >= 3:
            return parts[2].strip()
    return md.strip()


def _guard_content_loss(merged, info, a, b):
    """Refuse to silently resolve a merge that discards one side's real body content.

    Scope note: this guard compares note *bodies*. Frontmatter divergence
    beyond the uuid hard-conflict invariant (e.g. THEIRS-only tags or a
    review_state change) is still resolved by `apply_decisions` keeping OURS'
    frontmatter -- a pre-existing gap outside this guard's contract.

    Issue #4505 added this fail-safe for repository documentation (no `uuid:`
    frontmatter): the near-duplicate / "prefer concise" heuristic could pick one
    side wholesale, report MERGE_STATUS=resolved, and exit 0 -- discarding the
    other side's committed content with no conflict and no warning.

    That guard originally exempted vault notes (`uuid:` frontmatter present) on
    the assumption that vault-note merging is real semantic merging and therefore
    safe. It is not: `judge_locus` is a stub that never returns a resolvable
    per-locus decision, so `apply_decisions` always keeps OURS (%A) regardless of
    what THEIRS contains, and still reports "resolved". Once the driver's %A-write
    contract was fixed (#4561), that silent, always-keep-OURS "resolve" started
    reaching the real working tree on every vault-note merge with a genuine,
    non-trivial divergence -- see
    tests/cli/test_merge_driver.py::test_end_to_end_git_rebase_plain_prose_vault_note_divergence_is_not_silently_dropped.

    The only mechanisms trusted to resolve a divergence are the ones that
    provably preserve the discarded side's real body content (#4616, PR #4604
    reviews r3700682703 / r3700682705):

    - An exact body match: nothing to lose.
    - The markdown-link-carryover heuristic below, but only when it is
      verifiably lossless -- THEIRS' links all landed in the merged text AND
      THEIRS' remaining non-link prose already appears in the merged body.
      Carrying the links while dropping distinct incoming prose is exactly the
      false-clean merge this guard exists to prevent.
    - A near-duplicate pick (token similarity >= 0.85), scoped to vault notes
      (uuid identity on both sides). Set-of-tokens similarity ignores order,
      repetition, and negation ("deployment is enabled" vs "deployment is not
      enabled" clears the threshold), so it is only accepted for vault notes,
      where near-duplicate device-sync copies of one identified note are the
      expected input. Repository documentation never resolves through it.

    Any other divergence is not provably safe and must raise a conflict
    instead of silently discarding a side -- the same conservative default
    #4505 already established, now applied uniformly instead of only to
    non-vault content.
    """
    info = dict(info or {})
    if info.get("status") != "resolved":
        return merged, info

    a_body = _body(a)
    b_body = _body(b)
    if a_body == b_body:
        # Bodies are identical; nothing to lose by resolving.
        return merged, info

    reason = info.get("reason", "")
    if "carried links" in reason.lower() and _carried_links_are_lossless(
        _body(merged), b_body
    ):
        # Link carryover reconciled the divergence and provably preserved all
        # of THEIRS' body content (#4616: lossy carryover no longer resolves).
        return merged, info
    if (
        # Truthiness, not `is not None`: a bare `uuid:` key with no value is
        # not vault identity, matching the hard-conflict check above.
        _extract_uuid(a)
        and _extract_uuid(b)
        and _token_similarity(a_body, b_body) >= 0.85
    ):
        # Genuine vault-note near-duplicate: negligible content to lose either
        # way. Intentionally scoped to vault identity (#4616); repository docs
        # with high token overlap but distinct bodies conflict instead.
        return merged, info

    info["status"] = "conflict"
    info["reason"] = (
        (reason + "; " if reason else "")
        + "content diverges without a verified-safe resolution; "
        "refusing to silently discard a side, raising a conflict instead"
    )
    return merged, info


def merge_note_from_blobs(base: str, a: str, b: str):
    merged, info = _orig_merge_note_from_blobs(base, a, b)
    merged, info = _postprocess_merge(merged, info, a, b)
    return _guard_content_loss(merged, info, a, b)
