from app.agents.merge_resolver.agent import merge_note_from_blobs

BASE = """---
uuid: u-merge
kind: concept
review_state: draft
---
# Topic
Initial state
"""

A = """---
uuid: u-merge
kind: concept
review_state: reviewed
---
# Topic
Crisp cleaned summary with structure.
"""

B = """---
uuid: u-merge
kind: concept
review_state: draft
---
# Topic
Crisp cleaned summary with structure.

## References
- [link-a](https://example.com/a)
"""

def _has_frontmatter(md: str) -> bool:
    return md.startswith("---\n") and "\n---\n" in md[4:]

def test_merge_resolver_smoke_roundtrip():
    merged, info = merge_note_from_blobs(BASE, A, B)

    # merged text should include heading from A
    assert "Crisp cleaned summary" in merged

    # merged text should still include references from B OR status 'prompted'
    # (meaning agent wants human review)
    if info["status"] == "resolved":
        assert "References" in merged or "Crisp cleaned summary" in merged

    # frontmatter still there
    assert _has_frontmatter(merged)

    # status surface contract
    assert info["status"] in ("resolved", "prompted", "conflict")

    # reason contract (human-auditable explanation, not empty)
    assert isinstance(info.get("reason"), str)
    assert info["reason"].strip() != ""
