"""Issue #4505: the semanticmd resolver must never silently discard committed
repository documentation. A repo doc (no `uuid:` frontmatter, e.g. docs/**,
README.md, AGENTS.md) whose two sides diverge must resolve to a conflict rather
than have the near-duplicate / "prefer concise" heuristic pick one side wholesale
and report MERGE_STATUS=resolved.
"""
import pathlib

from app.agents.merge_resolver.agent import merge_note_from_blobs


def load(name):
    p = pathlib.Path("tests/fixtures/merge") / name
    return p.read_text(encoding="utf-8")


def test_repo_doc_merge_never_silently_drops_a_side():
    base = load("rd_base.md")
    a = load("rd_a.md")
    b = load("rd_b.md")

    merged, info = merge_note_from_blobs(base, a, b)

    # Neither side carries vault-note identity (no `uuid:` frontmatter) and the
    # bodies diverge, so the resolver must refuse to silently pick a side.
    assert info["status"] == "conflict"


def test_repo_doc_identical_sides_still_resolve():
    # No divergence, no vault identity -> nothing to lose, safe to resolve.
    base = load("rd_base.md")
    a = load("rd_a.md")
    b = load("rd_a.md")

    merged, info = merge_note_from_blobs(base, a, b)

    assert info["status"] == "resolved"


def test_vault_note_merge_behavior_is_unchanged():
    # Same near-duplicate scenario as test_near_duplicate_prefers_concise in
    # tests/agents/test_merge_resolver.py, using fixtures that carry `uuid:`
    # frontmatter (vault-note identity). The guard added for #4505 must not
    # touch this path: it should still resolve and still prefer the concise side.
    base = load("nd_base.md")
    a = load("nd_concise.md")
    b = load("nd_rambly.md")

    merged, info = merge_note_from_blobs(base, a, b)

    assert info["status"] == "resolved"
    assert "concise" in info["reason"].lower()
    assert merged.strip() == a.strip()
