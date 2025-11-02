from app.agents.merge_resolver.graph import apply_decisions

A = """---
uuid: u-1
kind: concept
review_state: draft
---
# A
alpha
"""

B = """---
uuid: u-1
kind: concept
review_state: reviewed
---
# B
bravo
"""

def test_yaml_B_and_body_B_respected():
    loci = [{"kind":"yaml"},{"kind":"body"}]
    decisions = [{"decision":"B"}, {"decision":"B"}]
    merged = apply_decisions("", A, B, loci, decisions)
    assert "review_state: reviewed" in merged
    assert "# B" in merged
    assert "bravo" in merged

def test_yaml_A_and_body_hybrid_respected():
    loci = [{"kind":"yaml"},{"kind":"body"}]
    decisions = [
        {"decision":"A"},
        {"decision":"HYBRID","hybrid":{"merged_text":"# A\nalpha\n\n## References\n- [x](y)\n"}}
    ]
    merged = apply_decisions("", A, B, loci, decisions)
    assert "review_state: draft" in merged
    assert "## References" in merged
