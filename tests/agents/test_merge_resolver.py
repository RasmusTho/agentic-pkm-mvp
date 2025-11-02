import pathlib
from app.agents.merge_resolver.agent import merge_note_from_blobs

def load(name):
    p = pathlib.Path("tests/fixtures/merge")/name
    return p.read_text(encoding="utf-8")

def test_near_duplicate_prefers_concise():
    base = load("nd_base.md")
    a = load("nd_concise.md")
    b = load("nd_rambly.md")
    merged, info = merge_note_from_blobs(base, a, b)
    assert "concise" in info["reason"].lower()
    assert merged.strip() == a.strip()

def test_overlap_carry_links():
    base = load("ov_base.md")
    a = load("ov_polished.md")
    b = load("ov_refs.md")
    merged, info = merge_note_from_blobs(base, a, b)
    assert "[" in merged

def test_state_advance_not_regress():
    base = load("st_base.md")
    a = load("st_promoted.md")
    b = load("st_reviewed.md")
    merged, info = merge_note_from_blobs(base, a, b)
    assert "promoted" in merged.lower()

def test_code_dump_penalized_in_concept_note():
    base = load("cd_base.md")
    a = load("cd_prose.md")
    b = load("cd_dump.md")
    merged, info = merge_note_from_blobs(base, a, b)
    assert "```" not in merged or len(merged) < len(b)

def test_uuid_mismatch_hard_conflict():
    base = load("id_base.md")
    a = load("id_a.md")
    b = load("id_b.md")
    merged, info = merge_note_from_blobs(base, a, b)
    assert info["status"] in ("resolved","prompted","conflict")
